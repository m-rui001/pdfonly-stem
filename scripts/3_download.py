#!/usr/bin/env python3
"""3_download.py -- batch PDF fetch: per-host token bucket, resume, dedupe.

Consumes the probed JSONL from 2_probe_xml.py (needs pdf_urls / oa_url).
Candidate URLs per record are ranked (GOOD_HOSTS first, BAD_HOSTS last) and
tried until one yields a valid PDF.

  python 3_download.py --in out/probed.jsonl --only pdf_only --root out/pdfs --verify
  python 3_download.py --in out/probed.jsonl --root out/pdfs --workers 64

What actually matters at scale:
  * Per-host token bucket. Hammering one publisher CDN gets your whole IP
    RANGE blocked -- the single most common way a big run dies.
  * Per-record .part file, so concurrent workers never share a scratch path
    and an interrupted download resumes with HTTP Range instead of restarting.
  * Validate magic bytes + size; with --verify also get page count and whether
    a text layer exists (text-less = scan -> needs OCR before your HTML step).
  * SHA1 content dedupe: one paper mirrored in 3 repos is stored once.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, sqlite3, subprocess, sys, threading, time
from urllib.parse import urlparse
import urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import config as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, sha1 TEXT, host TEXT, url TEXT, path TEXT,
  status TEXT, bytes INTEGER, kind TEXT, pages INTEGER, err TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS ix_status ON jobs(status);
CREATE INDEX IF NOT EXISTS ix_sha1   ON jobs(sha1);
"""


class DB:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.c = sqlite3.connect(path, check_same_thread=False, timeout=120)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript(SCHEMA)
        self.c.commit()

    def done_ids(self):
        return {r[0] for r in self.c.execute(
            "SELECT id FROM jobs WHERE status IN ('ok','dup')")}

    def sha_seen(self):
        return {r[0] for r in self.c.execute(
            "SELECT sha1 FROM jobs WHERE sha1 IS NOT NULL")}

    def put(self, row):
        with self.lock:
            self.c.execute(
                "INSERT OR REPLACE INTO jobs"
                "(id,sha1,host,url,path,status,bytes,kind,pages,err,ts)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)", row + (time.time(),))
            self.c.commit()


class Bucket:
    """Token bucket; rps = sustained requests allowed for one host."""

    def __init__(self, rps):
        self.rps, self.tokens, self.t = float(rps), float(rps), time.time()
        self.lock = threading.Lock()

    def acquire(self, wait=None):
        """Take a token. With wait=None block forever (legacy); with a number of
        seconds, give up and return False instead of parking the caller."""
        deadline = None if wait is None else time.time() + wait
        while True:
            with self.lock:
                now = time.time()
                self.tokens = min(self.rps * 2, self.tokens + (now - self.t) * self.rps)
                self.t = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True
            if deadline is not None and now >= deadline:
                return False
            time.sleep(min(0.2, 1.0 / max(self.rps, 0.2)))


class Buckets:
    """Per-host rate limit AND per-host concurrency cap.

    The concurrency cap matters as much as the rps: without it one slow host
    (measured: www.osti.gov, 341 of 1334 remaining records) absorbs every worker
    in the pool, so the other ~270 hosts make no progress at all. A caller that
    cannot get a slot now returns False and the record is retried in a later
    round instead of blocking a thread."""

    def __init__(self):
        self.m, self.busy, self.lock = {}, {}, threading.Lock()

    def get(self, host):
        with self.lock:
            b = self.m.get(host)
            if b is None:
                rps = next((v for k, v in C.RPS_OVERRIDES.items()
                            if host == k or host.endswith("." + k)), C.RPS_DEFAULT)
                b = self.m[host] = Bucket(rps)
            return b

    @staticmethod
    def cap(host):
        return C.MAX_CONN_DEFAULT

    def reserve(self, host, wait=8.0):
        """Claim a connection slot + a token, or return False within ~wait."""
        deadline = time.time() + wait
        while True:
            with self.lock:
                n = self.busy.get(host, 0)
                if n < self.cap(host):
                    self.busy[host] = n + 1
                    break
            if time.time() >= deadline:
                return False
            time.sleep(0.05)
        if self.get(host).acquire(max(deadline - time.time(), 0.05)):
            return True
        self.release(host)
        return False

    def release(self, host):
        with self.lock:
            self.busy[host] = max(0, self.busy.get(host, 1) - 1)


def _dkey(u):
    """Dedupe key that ignores query strings and trailing junk, so the same
    file offered as both pdf_url and oa_url (?download=1) is tried once."""
    p = urlparse(u)
    return (p.netloc.lower(), p.path.rstrip("/").lower())


def rank_urls(rec, skip_publishers=False):
    """Repository/institutional copies first, publisher CDNs last (or dropped).

    Measured on a 60-record STEM sample: 10 of 11 successes were institutional
    repositories; publisher URLs produced essentially all 403/HTML failures.
    Ordering does not change final yield (every candidate is tried) but it cuts
    wasted requests and time-to-first-byte substantially.
    """
    cands = list(rec.get("pdf_urls") or [])
    if rec.get("oa_url"):
        cands.append(rec["oa_url"])
    out, seen = [], set()
    for u in cands:
        if not u:
            continue
        k = _dkey(u)
        if k in seen:
            continue
        seen.add(k)
        out.append(u)

    def tier(u):
        full = urlparse(u).netloc.lower() + urlparse(u).path.lower()
        if any(b in full for b in C.PUBLISHER_BLOCK):
            return 2
        if any(g in full for g in C.REPO_HOST_KEYS):
            return 0
        return 1

    kept = [u for u in out if not (skip_publishers and tier(u) == 2)]
    return sorted(kept, key=lambda u: (tier(u), _dkey(u)))


HDR = {"User-Agent": C.UA, "Accept": "application/pdf,*/*"}


def fetch(url, part, buckets, slot_wait=8.0, budget=150.0):
    """Stream url -> part (resuming). Returns (status_tag, bytes_or_None).

    slot_wait bounds how long we wait for that host to be free (False -> the
    record is deferred, not failed). budget bounds the whole attempt: the
    socket timeout only covers one recv, so a server that drips a byte every
    89s would otherwise hold a connection slot forever."""
    host = urlparse(url).netloc.lower()
    if not buckets.reserve(host, slot_wait):
        return "deferred", None
    started = time.time()
    try:
        return _fetch(url, part, host, started, budget)
    finally:
        buckets.release(host)


def _fetch(url, part, host, started, budget):
    have = os.path.getsize(part) if os.path.exists(part) else 0
    req = urllib.request.Request(url, headers=dict(HDR))
    if have:
        req.add_header("Range", "bytes=%d-" % have)
    try:
        with urllib.request.urlopen(req, timeout=90, context=C.SSL_CTX) as r:
            status = getattr(r, "status", 200)
            ct = r.headers.get("Content-Type", "")
            if "text/html" in ct.lower():
                return "html_instead", None          # paywall / redirect page
            resume = bool(have) and status == 206
            with open(part, "ab" if resume else "wb") as f:
                if not resume:
                    have = 0
                got = 0
                while True:
                    if time.time() - started > budget:
                        return "too_slow", None
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if have + got > C.MAX_PDF_BYTES:
                        return "too_big", None
        return "ok", have + got
    except urllib.error.HTTPError as e:
        if e.code == 416:                            # already complete
            return "ok", os.path.getsize(part) if os.path.exists(part) else None
        return "http_%d" % e.code, None
    except Exception as e:
        # Bare type names put "URLError" over TLS-verify, DNS and tunnel failures
        # alike, which is how a trust-store bug read as "host unreachable".
        r = getattr(e, "reason", None)
        tag = "%s:%s" % (type(e).__name__, getattr(r, "reason", r)) if r \
            else type(e).__name__
        return tag[:60], None


def probe_pdf(path):
    """Return (ok, pages, kind). kind in {text, scanned}."""
    with open(path, "rb") as f:
        if f.read(5) != b"%PDF-":
            return False, 0, None
    if os.path.getsize(path) < C.MIN_PDF_BYTES:
        return False, 0, None
    pages, layer = 0, True
    try:
        out = subprocess.run(["pdfinfo", path], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=20).stdout
        m = re.search(r"Pages:\s+(\d+)", out)
        pages = int(m.group(1)) if m else 0
        txt = subprocess.run(["pdftotext", "-f", "1",
                              "-l", str(min(pages or 1, 2)), path, "-"],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=40).stdout
        layer = len(txt.strip()) > 60
    except Exception:
        pass                                        # poppler absent -> skip check
    return True, pages, ("text" if layer else "scanned")


def _safe(name):
    """OpenAlex ids contain ':' ("https://openalex.org/W123"), which on Windows
    is an NTFS alternate-data-stream separator: the write silently succeeds into
    a hidden stream and the later os.replace() dies with WinError 87."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def do_one(rec, db, buckets, tmp, root, verify, sha_seen, lock, skip_pub=False):
    rid = rec["id"]
    urls = rank_urls(rec, skip_pub)
    if not urls:
        db.put((rid, None, None, None, None, "no_url", 0, None, 0, "no pdf candidates"))
        return "no_url"
    part = os.path.join(tmp, _safe(rid) + ".part")
    last = "unreachable"
    for u in urls:
        st, size = fetch(u, part, buckets)
        if st == "deferred":
            # Host busy: not a failure, so nothing is written to the db and the
            # .part file survives for a Range resume on the next round.
            return "deferred"
        if st != "ok":
            last = st
            if st in ("http_403", "http_404", "html_instead", "too_big"):
                if os.path.exists(part):
                    os.remove(part)
            continue
        # validate OUTSIDE the lock: pdfinfo/pdftotext are subprocesses and
        # would otherwise serialise the whole pool
        ok, pages, kind = probe_pdf(part) if verify else (
            open(part, "rb").read(5) == b"%PDF-", 0, "text")
        if not ok:
            os.remove(part)
            last = "invalid_pdf"
            continue
        with lock:                                  # only hash + dedupe is serial
            sha1 = hashlib.sha1(open(part, "rb").read()).hexdigest()
            if sha1 in sha_seen:
                os.remove(part)
                db.put((rid, sha1, urlparse(u).netloc, u, None,
                        "dup", size, None, 0, None))
                return "dup"
            host = urlparse(u).netloc.lower()
            path = os.path.join(root, _safe(host)[:3] or "unk", sha1[:2],
                                sha1 + ".pdf")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path):
                os.remove(part)                     # content already stored
            else:
                os.replace(part, path)
            sha_seen.add(sha1)
        db.put((rid, sha1, host, u, path, "ok", size, kind, pages, None))
        return "ok"
    db.put((rid, None, None, urls[0], None, "fail", 0, None, 0, last))
    return "fail"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--root", default="out/pdfs")
    ap.add_argument("--db", default="out/state.db")
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--only", help="comma list of verdicts, e.g. pdf_only,unknown")
    ap.add_argument("--verify", action="store_true",
                    help="pdfinfo/pdftotext check; tags scanned vs text")
    ap.add_argument("--skip-publishers", action="store_true",
                    help="drop publisher CDN URLs (403-prone); repos + arXiv only")
    ap.add_argument("--progress", type=int, default=25,
                    help="print every N records (keep small or the run looks hung)")
    ap.add_argument("--limit", type=int, default=100000000)
    a = ap.parse_args()

    tmp = os.path.join(a.root, ".tmp")
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(a.root, exist_ok=True)
    db = DB(a.db)
    sha_seen = db.sha_seen()
    done = db.done_ids()
    verdicts = set(v.strip() for v in a.only.split(",")) if a.only else None

    recs = []
    for line in open(a.inp, encoding="utf-8"):
        r = json.loads(line)
        if r["id"] in done:
            continue
        if verdicts and r.get("verdict") not in verdicts:
            continue
        recs.append(r)
        if len(recs) >= a.limit:
            break
    print("[dl] %d to fetch | %d already done | %d workers | verify=%s"
          % (len(recs), len(done), a.workers, a.verify), file=sys.stderr)

    lock = threading.Lock()
    buckets = Buckets()
    t0 = time.time()
    tally = {"ok": 0, "dup": 0, "fail": 0, "no_url": 0}
    crash_reasons = {}
    n = 0
    pending, rnd = recs, 0
    while pending:
        # Deferred records (host busy) are retried in a later round rather than
        # blocking a worker, which is what stops one slow repository from
        # freezing the whole pool.
        rnd += 1
        before = tally["ok"] + tally["dup"] + tally["fail"]
        deferred = []
        with ThreadPoolExecutor(a.workers) as ex:
            futs = {ex.submit(do_one, r, db, buckets, tmp, a.root, a.verify,
                              sha_seen, lock, a.skip_publishers): r
                    for r in pending}
            for f in futures_as_completed(futs):
                try:
                    tag = f.result()
                except Exception as e:
                    # Without this a whole failure class is invisible: the tally
                    # just says "crash" and nothing records why.
                    key = "%s: %s" % (type(e).__name__, e)
                    crash_reasons[key] = crash_reasons.get(key, 0) + 1
                    if crash_reasons[key] <= 2:
                        print("[dl] CRASH %s" % key, file=sys.stderr)
                    tally["crash"] = tally.get("crash", 0) + 1
                    n += 1
                    continue
                if tag == "deferred":
                    deferred.append(futs[f])
                    continue
                tally[tag] = tally.get(tag, 0) + 1
                n += 1
                if n % max(a.progress, 1) == 0:
                    rate = n / max(time.time() - t0, 1e-6)
                    left = len(recs) - n
                    print("[dl] %d/%d %.1f/s %s eta=%.0fm" % (
                        n, len(recs), rate, tally,
                        left / max(rate, 1e-6) / 60), file=sys.stderr)
        if not deferred:
            break
        if tally["ok"] + tally["dup"] + tally["fail"] == before:
            print("[dl] round %d stalled: %d records still rate-limited, giving up"
                  % (rnd, len(deferred)), file=sys.stderr)
            break
        print("[dl] round %d done, %d deferred (host busy)" % (rnd, len(deferred)),
              file=sys.stderr)
        pending = deferred
        time.sleep(2)
    print("[dl] DONE %s unresolved=%d in %.0fs"
          % (tally, len(pending), time.time() - t0), file=sys.stderr)
    for k, v in sorted(crash_reasons.items(), key=lambda kv: -kv[1]):
        print("[dl] crash x%-4d %s" % (v, k), file=sys.stderr)


def futures_as_completed(fs):
    from concurrent.futures import as_completed
    return as_completed(fs)


if __name__ == "__main__":
    main()
