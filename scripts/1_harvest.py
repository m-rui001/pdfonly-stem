#!/usr/bin/env python3
"""1_harvest.py -- build a STEM candidate manifest from OpenAlex.

  python 1_harvest.py --scope stem --group
  python 1_harvest.py --scope stem --year 2015-2020 --limit 50000 --out out/manifest.jsonl

NOTE on "only PDF" (verified 2026-09-24 against the live API):
  * `pmcid:null` is a DEAD filter -- accepted, silently ignored, count unchanged;
    `pmcid:exists` returns 0. `pmcid` is no longer a property of /works.
  * `has_content.grobid_xml:true` is NOT structured-source evidence; that XML is
    derived *from* the PDF by GROBID, so it is true for ~94% of PDFs.
  * `locations.landing_page_url:search:...` silently returns 0.
  => This script only narrows candidates and records format *signals*.
     The real decision happens in 2_probe_xml.py / 3_mark_pdfonly.py.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.request
from urllib.parse import urlencode

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import config as C

SELECT = ("id,doi,title,display_name,publication_year,publication_date,type,"
          "primary_topic,open_access,locations,best_oa_location,has_content,"
          "indexed_in,is_retracted,language,cited_by_count")


def api(url, tries=5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "corpus/1.0 (mailto:%s)" % C.EMAIL})
            with urllib.request.urlopen(req, timeout=90, context=C.SSL_CTX) as r:
                return json.load(r)
        except Exception as e:            # 502/503 are routine at scale
            last = e
            time.sleep(min(2 ** i, 30))
    raise last


def scope_filter(a):
    f = ["type:article"]
    sc = a.scope
    if sc == "stem":
        f.append("primary_topic.field.id:" + C.STEM)
    elif sc == "all":
        pass
    else:
        f.append("primary_topic.field.id:" + C.STEM)
    if a.year:
        lo, _, hi = a.year.partition("-")
        hi = hi or lo
        f.append("from_publication_date:%s-01-01" % lo)
        f.append("to_publication_date:%s-12-31" % hi)
    if a.oa_fulltext:
        f.append("open_access.is_oa:true")
        f.append("has_fulltext:true")
    if a.need_pdf:
        f.append("has_content.pdf:true")
    if a.retracted_ok is False:
        f.append("is_retracted:false")
    if a.cited:
        f.append("cited_by_count:>=%d" % a.cited)
    if a.extra:
        f.append(a.extra)
    return ",".join(f)


def show_groups(filt, keys):
    for gb in keys:
        d = api("%s/works?%s" % (C.OPENALEX,
                                 urlencode({"filter": filt, "group_by": gb})))
        rows = d.get("group_by") or []
        tot = d.get("meta", {}).get("count", 0)
        sys.stderr.write("=== group_by %s   (TOTAL %s)\n" % (gb, f"{tot:,}"))
        for x in sorted(rows, key=lambda r: -r["count"]):
            name = x.get("key_display_name") or x.get("key")
            sys.stderr.write("   %12s  %s\n" % (f"{x['count']:,}", name))


def harvest(filt, a):
    cursor, n, t0, wrote = "*", 0, time.time(), 0
    fh = open(a.out, "w", buffering=1, encoding="utf-8")
    try:
        while n < a.limit:
            q = {"filter": filt, "cursor": cursor, "per-page": 200,
                 "select": SELECT, "mailto": C.EMAIL}
            d = api("%s/works?%s" % (C.OPENALEX, urlencode(q)))
            res = d.get("results") or []
            if not res:
                break
            for w in res:
                if n >= a.limit:
                    break
                fh.write(json.dumps(w, ensure_ascii=False) + "\n")
                wrote += 1
                n += 1
            cursor = d.get("meta", {}).get("next_cursor")
            if not cursor:
                break
            if n % 20000 < 200:
                sys.stderr.write("[harvest] %s @ %.0f rec/s\n"
                                 % (f"{n:,}", n / max(time.time() - t0, 1e-6)))
    finally:
        fh.close()
    sys.stderr.write("[harvest] wrote %s -> %s (%.1fs)\n"
                     % (f"{wrote:,}", a.out, time.time() - t0))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scope", default="stem", choices=["stem", "all"])
    p.add_argument("--year", help="2015 or 2015-2020")
    p.add_argument("--limit", type=int, default=100000)
    p.add_argument("--out")
    p.add_argument("--group", action="store_true")
    p.add_argument("--no-oa-fulltext", dest="oa_fulltext", action="store_false")
    p.add_argument("--no-need-pdf", dest="need_pdf", action="store_false")
    p.add_argument("--allow-retracted", dest="retracted_ok", action="store_true")
    p.add_argument("--cited", type=int, help="min cited_by_count, good for quality-first sampling")
    p.add_argument("--extra", help="raw extra OpenAlex filter")
    p.set_defaults(oa_fulltext=True, need_pdf=True, retracted_ok=False)
    a = p.parse_args()

    filt = scope_filter(a)
    sys.stderr.write("[harvest] filter = %s\n\n" % filt)

    if a.group:
        show_groups(filt, ["primary_topic.field.id", "publication_year"])
        return
    if not a.out:
        p.error("--out is required unless --group")
    harvest(filt, a)


if __name__ == "__main__":
    main()
