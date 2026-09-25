"""Shared config for the PDF-only STEM corpus pipeline.

Edit EMAIL once -- it puts you in OpenAlex's polite pool (much higher rate limit).
"""
from __future__ import annotations
import os
import ssl

try:
    import certifi
    # Windows' root store as seen by CPython's `ssl` had only 61 anchors here and
    # lacked intermediates several repositories chain to, so ~1/3 of "unreachable"
    # URLs were really SSLCertVerificationError. certifi's bundle verifies them.
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = None            # no certifi -> platform default

EMAIL = os.environ.get("CORPUS_MAILTO", "replace-me@your-lab.edu")

# ---------------------------------------------------------------------------
# STEM scope. IMPORTANT: OpenAlex has only 4 domains (1 Life, 2 Social,
# 3 Physical, 4 Health) and NONE of them equals "STEM".
#   domain/3 "Physical Sciences" is actually S+T+E+M (it contains Engineering,
#     Computer Science, Math, Physics, Chem, Materials, Earth, Energy).
#   domain/4 "Health Sciences" = Medicine/Nursing/Dentistry/HP -> NOT STEM.
#   domain/2 "Social Sciences" = incl. Psychology/Econ/Business -> NOT STEM.
# So scope by *field*, not domain, and pull the life sciences out of domain/1.
# ---------------------------------------------------------------------------
F = "https://openalex.org/fields/"

# Science + Technology + Engineering + Mathematics, at field level.
STEM_FIELDS = {
    "mathematics": 26,
    "computer_science": 17,
    "physics": 31,
    "chemistry": 16,
    "engineering": 22,
    "chemical_eng": 15,
    "materials": 25,
    "energy": 21,
    "env_science": 23,
    "earth_planetary": 19,
    # from domain/1 (Life Sciences) -- keep the hard-science ones
    "biochemistry_genetics_molbio": 13,
    "immunology_microbiology": 24,
    "neuroscience": 28,
    "pharmacology_tox": 30,
    "agricultural_biological": 11,
}
# Explicitly excluded: 27 Medicine, 29 Nursing, 35 Dentistry, 36 Health
# Professions, 34 Veterinary, 32 Psychology, 33 Social Sciences, 20 Econ,
# 14 Business, 18 Decision Sciences, 12 Arts & Humanities.

STEM = "|".join(f"{F}{i}" for i in STEM_FIELDS.values())

DOMAINS = {
    "physical": "https://openalex.org/domains/3",
    "life": "https://openalex.org/domains/1",
    "health": "https://openalex.org/domains/4",
    "social": "https://openalex.org/domains/2",
    "stem_fields": STEM,
}

OPENALEX = "https://api.openalex.org"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 corpus-build/1.0")

OUT = os.environ.get("CORPUS_OUT", "/data/pdfcorpus/out")
STATE = os.environ.get("CORPUS_STATE", "/data/pdfcorpus/out/state.db")

# ---------------------------------------------------------------------------
# "PDF-only" definition
# ---------------------------------------------------------------------------
# A work counts as PDF-only when it has a retrievable PDF and *no* structured
# source we could parse instead. Rejection signals, strongest first:
#   pmcid            -> PubMed Central holds NISO JATS XML
#   .tex/.bz2 src    -> arXiv e-print source is LaTeX (only ~9% are PDF-only)
#   html source      -> publisher serves article-level HTML
# NOTE: absence of PMCID is a proxy, not proof. Use `2_probe_xml.py` to test
# each record for arXiv source, PMC JATS, and publisher HTML; never infer a
# corpus-wide PDF-only percentage from PMCID absence.
REJECT_SOURCES = (
    "pubmed central", "europe pmc", "europepmc", "pmc",
)

# Hosts that reliably serve bare PDFs to plain HTTP GET from a datacenter IP.
# MEASURED on a 60-record STEM sample (2026-09-24): 11/60 downloaded, and 10 of
# those 11 were *institutional repositories* (eprints.*, lirias.*, edoc.*,
# curis.*, repo.*). Publisher links from OpenAlex returned 403 (23) or an HTML
# paywall page (14). So repository-first ordering is the single biggest lever
# on yield -- do not rank publisher URLs ahead of these.
REPO_HOST_KEYS = (
    "eprints", "repository", "repo.", "dspace", "ir.", "iris.", "lirias",
    "edoc", "curis", "repositorio", "sfx", "ntrs", "citeseerx", "core.ac.uk",
    "hal.science", "hal.archives", "osf.io", "d-nb.info", "jstage.jst.go.jp",
    "arxiv.org", "scielo", "redalyc", "doaj.org", "mdpi.com", "frontiersin",
    "plos.org", "jstatsoft.org", "aimsciences", "projecteuclid", "numdam",
    "iucr.org", "copernicus.org", "aanda.org", "epj.org", "astro.lu",
    "dialnet", "pearl.plymouth", "kuleuven", "unima", "su.diva-portal",
    "diva-portal", "europepmc", "ncbi.nlm.nih.gov/pmc",
)
# Publisher CDN hosts that block datacenter IPs at high rate. Kept, but tried
# LAST and at low rps; --skip-publishers drops them entirely.
PUBLISHER_BLOCK = (
    "onlinelibrary.wiley.com", "sciencedirect.com", "link.springer",
    "nature.com", "cell.com", "ieeexplore.ieee", "pubs.acs.org",
    "tandfonline", "jamanetwork", "nejm.org", "academic.oup", "lww.com",
    "sagepub", "thelancet", "scitepress", "aps.org", "link.aps.org",
    "aip.scitation", "pubs.aip", "iovs", "arvojournals", "eurekaselect",
    "ingentaconnect", "worldscientific", "brill.com", "emerald",
)

# Per-host token bucket: requests per second, and max simultaneous connections.
RPS_DEFAULT = 1.5
RPS_OVERRIDES = {
    "arxiv.org": 0.4,        # arXiv is strict; 0.4 rps is the documented-safe zone
    "export.arxiv.org": 1.0,
}
MAX_CONN_DEFAULT = 4

MIN_PDF_BYTES = 8 * 1024      # below this it's an error page, not a paper
MAX_PDF_BYTES = 80 * 1024 * 1024
