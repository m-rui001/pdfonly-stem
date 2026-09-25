#!/usr/bin/env python3
"""3b_enrich_urls.py -- add PDF candidates for records that had too few.

Measured on a 60-record STEM sample: 33/60 had exactly ONE pdf URL, and when
that host answered 403 the record died. Success rate for the pdf_only verdict
was only ~18% purely because of thin candidate lists, not because the papers
are unavailable. Two free enrichment channels fix most of it:

  1. Unpaywall API   GET https://api.unpaywall.org/v2/<doi>?email=...
       -> best_oa_location.url_for_pdf  (needs a REAL email, else HTTP 422)
  2. OpenAlex content mirror
       https://content.openalex.org/works/<W-id>.pdf?apikey=<key>
       -> requires a free API key from https://openalex.org/users
          (without one you get {"error":"API key required"})

  python 3b_enrich_urls.py --in out/probed.jsonl --out out/probed.enriched.jsonl \
      --email you@lab.edu --openalex-key $OA_KEY --workers 24
"""
from __future__ import annotations
import argparse, json, os, sys, time, threading
from urllib.parse import quote
import urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import config as C


def get_json(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": "corpus/1.0 (mailto:%s)" % C.EMAIL})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=C.SSL_CTX) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, "http_%d" % e.code
    except Exception as e:
        return None, type(e).__name__


def unpaywall_pdf(doi, email):
    if not doi:
        return None
    d, _ = get_json("https://api.unpaywall.org/v2/%s?email=%s"
                    % (quote(doi, safe=""), quote(email)))
    if not d:
        return None
    out = []
    loc = d.get("best_oa_location") or {}
    if loc.get("url_for_pdf"):
        out.append(loc["url_for_pdf"])
    for l in d.get("oa_locations") or []:
        if l.get("url_for_pdf"):
            out.append(l["url_for_pdf"])
    return out


def enrich(rec, email, oa_key):
    urls = list(rec.get("pdf_urls") or [])
    doi = (rec.get("doi") or "").replace("https://doi.org/", "")
    if len(urls) < 4:
        for u in (unpaywall_pdf(doi, email) or []):
            if u not in urls:
                urls.append(u)
    if oa_key:
        wid = rec["id"].rsplit("/", 1)[-1]
        mirror = "https://content.openalex.org/works/%s.pdf?apikey=%s" % (wid, oa_key)
        if mirror not in urls:
            urls.append(mirror)            # last: already-fetched, high hit rate
    rec = dict(rec)
    rec["pdf_urls"] = urls
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--email", default=os.environ.get("CORPUS_MAILTO", C.EMAIL))
    ap.add_argument("--openalex-key", default=os.environ.get("OPENALEX_KEY", ""))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--only-thin", type=int, default=4,
                    help="enrich records with fewer than N candidates (0 = all)")
    a = ap.parse_args()

    if "@" not in a.email or "replace-me" in a.email:
        sys.exit("Set a real email (Unpaywall returns 422 otherwise): --email you@lab.edu")

    recs = [json.loads(l) for l in open(a.inp, encoding="utf-8")]
    todo = [r for r in recs if a.only_thin == 0 or len(r.get("pdf_urls") or []) < a.only_thin]
    print("[enrich] %d/%d records to enrich" % (len(todo), len(recs)), file=sys.stderr)

    done = {}
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(lambda x: enrich(x, a.email, a.openalex_key), todo):
            done[r["id"]] = r
            if len(done) % 500 == 0:
                print("[enrich] %d %.0f/s" % (len(done), len(done) / (time.time() - t0)),
                      file=sys.stderr)
    n_before = sum(len(r.get("pdf_urls") or []) for r in recs)
    with open(a.out, "w", buffering=1, encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(done.get(r["id"], r), ensure_ascii=False) + "\n")
    n_after = sum(len(done.get(r["id"], r).get("pdf_urls") or []) for r in recs)
    print("[enrich] candidate URLs %d -> %d -> %s" % (n_before, n_after, a.out),
          file=sys.stderr)


if __name__ == "__main__":
    main()
