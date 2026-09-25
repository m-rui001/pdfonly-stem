#!/usr/bin/env python3
"""4_export.py -- join state.db + probe verdicts into a handoff table.

Feeds an existing batch pdf->html pipeline. The one thing that will break it is
scanned PDFs (no text layer), so they are split into their own file for OCR.

  python 4_export.py --db out/state.db --probed out/probed.jsonl --prefix out/corpus
"""
from __future__ import annotations
import argparse, csv, json, os, sqlite3, sys
from collections import Counter

HDR = ["openalex_id", "doi", "year", "field", "verdict", "sha1", "bytes",
       "kind", "pages", "host", "path", "url"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--probed", required=True, help="JSONL from 2_probe_xml.py")
    ap.add_argument("--prefix", default="out/corpus")
    a = ap.parse_args()

    meta = {}
    for line in open(a.probed, encoding="utf-8"):
        r = json.loads(line)
        meta[r["id"]] = r

    con = sqlite3.connect(a.db)
    rows = con.execute(
        "SELECT id,sha1,host,url,path,status,bytes,kind,pages "
        "FROM jobs WHERE status='ok'").fetchall()

    outs = {}
    tally = Counter()
    try:
        for name in ("text", "scanned", "other"):
            outs[name] = open("%s.%s.tsv" % (a.prefix, name), "w", newline="",
                              encoding="utf-8")
            w = csv.writer(outs[name], delimiter="\t")
            outs[name + "_w"] = w
            w.writerow(HDR)
        for rid, sha1, host, url, path, _st, size, kind, pages in rows:
            m = meta.get(rid, {})
            bucket = kind if kind in ("text", "scanned") else "other"
            tally[bucket] += 1
            tally[m.get("verdict", "unknown")] += 1
            outs[bucket + "_w"].writerow([
                rid, m.get("doi") or "", m.get("year") or "", m.get("field") or "",
                m.get("verdict") or "", sha1, size, kind, pages, host, path, url])
    finally:
        for f in outs.values():
            if hasattr(f, "close"):
                f.close()

    print("wrote %s.{text,scanned,other}.tsv  (%d PDFs)" % (a.prefix, len(rows)),
          file=sys.stderr)
    for k in ("text", "scanned", "other", "pdf_only", "has_source", "unknown"):
        if tally[k]:
            print("  %-10s %d" % (k, tally[k]), file=sys.stderr)
    print("\nNext: pipe text.tsv straight into your pdf->html step; run "
          "ocrmypdf on scanned.tsv first (no text layer -> your extractor "
          "would emit empty HTML).", file=sys.stderr)


if __name__ == "__main__":
    main()
