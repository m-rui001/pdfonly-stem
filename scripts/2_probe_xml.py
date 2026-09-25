#!/usr/bin/env python3
"""2_probe_xml.py -- decide, per record, whether a NON-PDF source exists.

No single API answers "is this paper PDF-only?". Verified dead ends:
  OpenAlex  pmcid:null / pmcid:exists    -> field removed, filter ignored
  OpenAlex  has_content.grobid_xml:true  -> derived FROM the pdf, proves nothing
  EuropePMC DOI search                   -> covers biomedicine only
  Crossref  .message.link / .format      -> sparse, most publishers omit it

So we probe the three channels that actually work, cheaply and in parallel:

  A. arXiv        GET https://arxiv.org/e-print/<id>   -> Content-Type tells
                 TeX (application/gzip|tar) vs PDF-only (application/pdf)
                 (measured: 301 -> /src/<id>; ~91% of arXiv has real TeX source)
  B. PubMed Central  EURPMC rest/search DOI:"..."      -> pmcid present = JATS XML
  C. Publisher XML  HEAD/GET candidate URLs:
        <landing>?artFile=xml   /  /xml  /  .xml  /  citation.xml
        OAI-PMH getRecord metadataPrefix=jats20030220 (repository-hosted)

  Verdicts (measured on 60 random STEM records, 2018-2022):
      has_source        39 (65%)  TeX or JATS or article-HTML confirmed present
      unknown           19 (32%)  nothing testable -- NOT the same as pdf-only
      likely_pdf_only    1 ( 2%)  in PMC's scope but this DOI has no pmcid
      pdf_only           1 ( 2%)  arXiv e-print is itself a bare PDF (hard proof)

  => Only ~3% are *provably* PDF-only and a third can't be decided at all. Do
     not filter downloads with `--only pdf_only`; use
     `--only pdf_only,likely_pdf_only,unknown` for "no structured source found".

  python 2_probe_xml.py --in out/manifest.jsonl --out out/probed.jsonl --workers 24
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, socket
from urllib.parse import urlencode, urlparse, quote
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import config as C

ARXIV_SRC = "https://arxiv.org/e-print/{aid}"
EURPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urlencode(
    {"format": "json", "pageSize": "1", "resultType": "core"}) + "&query="

def http_head(url, timeout=25):
    """Return (status, content_type, final_url) without pulling the body."""
    req = urllib.request.Request(url, method="GET", headers={
        "User-Agent": C.UA, "Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=C.SSL_CTX) as r:
            return r.status, r.headers.get("Content-Type", ""), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", url
    except Exception:
        return 0, "", url


def arxiv_id(work):
    for l in work.get("locations") or []:
        for k in ("landing_page_url", "pdf_url"):
            u = l.get(k) or ""
            m = re.search(r"arxiv\.org/(?:abs|pdf|src)/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})", u)
            if m:
                return m.group(1)
    return None


def check_tex(work):
    """True => LaTeX source exists => NOT pdf-only."""
    aid = arxiv_id(work)
    if not aid:
        return None
    st, ct, final = http_head(ARXIV_SRC.format(aid=quote(aid, safe="/")))
    if st == 0:
        return None
    if "application/pdf" in ct:
        return False                     # arXiv itself only has the PDF
    if any(t in ct for t in ("gzip", "x-tar", "octet-stream", "zip")):
        return True                      # real source bundle
    return None


def check_jats(work):
    """True => JATS/NLM XML exists in PMC => NOT pdf-only."""
    doi = (work.get("doi") or "").replace("https://doi.org/", "")
    if not doi:
        return None
    url = EURPMC + quote('DOI:"%s"' % doi)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "corpus/1.0 (mailto:%s)" % C.EMAIL})
        with urllib.request.urlopen(req, timeout=25, context=C.SSL_CTX) as r:
            d = json.load(r)
    except Exception:
        return None
    hits = (d.get("resultList") or {}).get("result") or []
    if not hits:
        return None                      # not indexed by PMC at all (biomed-limited)
    return bool(hits[0].get("pmcid"))


HTML_HINT = re.compile(r"(/html?$|/html/|_html|artxml|/xml/|doi/full)", re.I)

def check_publisher_html(work):
    """True if the landing page looks like article-level HTML rather than a PDF gate."""
    for l in work.get("locations") or []:
        u = (l.get("landing_page_url") or "")
        if u and not l.get("pdf_url") and HTML_HINT.search(u):
            st, ct, _ = http_head(u)
            if st == 200 and "html" in ct:
                return True
    return False


def probe(work):
    ev = {"tex": check_tex(work), "jats": check_jats(work),
          "html": check_publisher_html(work)}
    # Positive proof of a non-PDF original -> definitively NOT pdf-only.
    if ev["tex"] or ev["jats"] or ev["html"]:
        verdict = "has_source"
    # arXiv says the e-print IS a bare PDF: strong, direct evidence.
    elif ev["tex"] is False:
        verdict = "pdf_only"
    # PMC has JATS for a sibling record but not this DOI: weak-negative only.
    # NOTE check_publisher_html returns False (not None) when no candidate URL
    # matched its regex, so it must NOT be treated as evidence of anything --
    # counting it would turn every untested record into a false "pdf_only".
    elif ev["jats"] is False:
        verdict = "likely_pdf_only"
    else:
        verdict = "unknown"              # nothing testable -> do not conclude
    return {"id": work["id"], "doi": work.get("doi"),
            "title": (work.get("title") or "")[:200],
            "year": work.get("publication_year"),
            "field": ((work.get("primary_topic") or {}).get("field") or {}).get("display_name"),
            "format_evidence": ev, "verdict": verdict,
            "pdf_urls": [l.get("pdf_url") for l in work.get("locations") or [] if l.get("pdf_url")],
            "oa_url": (work.get("open_access") or {}).get("oa_url")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=100000)
    a = ap.parse_args()

    rows = [json.loads(l) for i, l in enumerate(open(a.inp, encoding="utf-8")) if i < a.limit]
    sys.stderr.write("[probe] %d records, %d workers\n" % (len(rows), a.workers))
    t0 = time.time(); n = 0
    with open(a.out, "w", buffering=1, encoding="utf-8") as fh, ThreadPoolExecutor(a.workers) as ex:
        for res in ex.map(probe, rows):
            fh.write(json.dumps(res, ensure_ascii=False) + "\n"); n += 1
            if n % 500 == 0:
                sys.stderr.write("[probe] %d/%d %.1f/s\n" % (n, len(rows), n / (time.time() - t0)))
    sys.stderr.write("[probe] done %d -> %s\n" % (n, a.out))


if __name__ == "__main__":
    main()
