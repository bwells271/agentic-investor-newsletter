"""
newsletter_data.py

Builds the source data for the two weekly Substack newsletters by reading the
evaluated-pitches Google Sheet.

  --type special   Special Situation? = Yes,  grouped by situation type
  --type pitches   every pitch,               grouped by investment-idea type

The two issues overlap on purpose: a strong special situation can appear in both.

READ-ONLY CONTRACT
------------------
The sheet is user-owned and hand-curated: this module must never write to it.

Two read paths, selected with --source:

  csv (default)  Google's gviz CSV export over plain HTTPS. No credentials, no
                 OAuth, physically incapable of writing. This is what the cloud
                 routine uses, and it works anywhere the sheet URL resolves. The
                 column list skips Full Text (column E), which is ~60 MB of raw
                 article text nothing downstream needs.
  api            Authenticated Sheets API, for use if the sheet is ever locked
                 down so link-readers no longer work. See the note below.

The shared token.json was minted with the read-write "spreadsheets" scope (Gmail
ingestion needs the same token), and Google rejects a refresh that asks for a
scope the grant does not cover — so read-only cannot be enforced at the scope
level here. It is enforced structurally instead: read_rows() pulls the bound
values().batchGet method off the service and drops every other reference, so no
write method is reachable from this module. Do not add update/append/batchUpdate
calls, and do not return the raw service to callers.

To make it airtight at the scope level, mint a second token limited to
spreadsheets.readonly and point GOOGLE_OAUTH_READONLY_TOKEN_FILE at it; if that
variable is set, it is used in preference to the shared token.

Selection rules (set by the newsletter owner):
  * Window   — rows whose Date Ingested (fallback: Pitch Date) fall in the last
               N days. Rows dated "n.a." are legacy backlog and are always
               skipped, by design.
  * Quality  — rows must carry enough substance to write about (see passes_info_gate).
  * Rank     — Total Score, descending. Score decides order and inclusion only;
               it is never shown to readers.
  * Cap      — top N (default 50).

Verdict labels (No-Brainer / Interesting / Pass) and case-study analogies are
stripped here so they cannot leak into the newsletter copy.

Output: .tmp/newsletter_<type>_<YYYY-MM-DD>.json

Usage:
    python3 tools/newsletter_data.py --type special
    python3 tools/newsletter_data.py --type pitches --days 7 --limit 50
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

try:  # .env is local-only; the cloud routine runs without it.
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from categories import (
    SITUATION_CATEGORIES,
    STYLE_CATEGORIES,
    classify as classify_situation,
    classify_strategy,
)

# Deliberately not hard-coded. The sheet is readable by anyone holding its ID,
# so the ID is the secret: it must never live in this repo. Supply it with
# --sheet-id or the PITCHES_SHEET_ID environment variable.
SHEET_ID = os.environ.get("PITCHES_SHEET_ID", "")


def _require_sheet_id() -> str:
    if not SHEET_ID:
        sys.exit(
            "No sheet ID. Pass --sheet-id <id> or set PITCHES_SHEET_ID.\n"
            "It is kept out of this repo on purpose: anyone holding the ID can "
            "read the sheet."
        )
    return SHEET_ID
# gviz lets us name columns, so Full Text (E) is left on the server.
GVIZ_COLUMNS = "A,B,C,D,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X"
GVIZ_URL = (
    "https://docs.google.com/spreadsheets/d/{sid}/gviz/tq"
    "?tqx=out:csv&gid=0&tq={q}"
)
TOKEN_FILE = PROJECT_ROOT / os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", "token.json")
TMP_DIR = PROJECT_ROOT / ".tmp"

READONLY_TOKEN_FILE = os.environ.get("GOOGLE_OAUTH_READONLY_TOKEN_FILE")
READONLY_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# The sheet's Full Text column (E) holds ~60 MB of raw article text and is not
# needed downstream, so it is skipped: two ranges instead of one A:X pull.
RANGE_LEFT = "A2:D"      # Company Name, Ticker, Link, Pitch Date
RANGE_RIGHT = "F2:X"     # Brief Summary .. Reviewed  (skips E = Full Text)

LEFT_COLS = ["company", "ticker", "link", "pitch_date"]
RIGHT_COLS = [
    "brief_summary",
    "valuation", "valuation_explanation",
    "predictability", "predictability_explanation",
    "durability", "durability_explanation",
    "capital_allocation", "capital_allocation_explanation",
    "management_quality", "management_quality_explanation",
    "total_score", "total_evaluation",
    "special_situation", "no_brainer", "notes",
    "date_ingested", "pitch_id", "reviewed",
]

# ── sheet access ─────────────────────────────────────────────────────────────

def read_rows_csv() -> list[dict]:
    """Read the sheet over unauthenticated HTTPS via the gviz CSV export.

    Requires only that the sheet stays readable to anyone with the link. No
    credentials are involved, so there is no code path here that could write.
    """
    import csv as _csv
    import io
    import urllib.parse
    import urllib.request

    url = GVIZ_URL.format(sid=_require_sheet_id(), q=urllib.parse.quote(f"select {GVIZ_COLUMNS}"))
    with urllib.request.urlopen(url, timeout=300) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    _csv.field_size_limit(sys.maxsize)
    reader = _csv.reader(io.StringIO(raw))
    rows_in = list(reader)
    if not rows_in:
        raise RuntimeError("gviz export returned no rows; is the sheet still link-readable?")

    cols = LEFT_COLS + RIGHT_COLS
    out = []
    for i, raw_row in enumerate(rows_in[1:], start=2):
        rec = {c: (raw_row[j].strip() if j < len(raw_row) else "") for j, c in enumerate(cols)}
        rec["_sheet_row"] = i
        out.append(rec)
    return out


def _batch_get():
    """Return ONLY the bound values().batchGet callable.

    Everything else about the service — including every write method — goes out
    of scope when this function returns, so the rest of the module has no way to
    modify the sheet even by mistake.
    """
    # Imported here, not at module scope: the default csv path is pure stdlib
    # and must not require google-api-python-client to be installed.
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build as build_service

    if READONLY_TOKEN_FILE:
        creds = Credentials.from_authorized_user_file(
            str(PROJECT_ROOT / READONLY_TOKEN_FILE), READONLY_SCOPES
        )
    else:
        # Refresh must request exactly the scopes the token was granted.
        granted = json.loads(Path(TOKEN_FILE).read_text(encoding="utf-8")).get("scopes")
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), granted)
    service = build_service("sheets", "v4", credentials=creds, cache_discovery=False)
    return service.spreadsheets().values().batchGet


def read_rows_api() -> list[dict]:
    """Return every sheet row as a dict. Read-only; makes exactly one API call."""
    batch_get = _batch_get()
    resp = batch_get(spreadsheetId=_require_sheet_id(), ranges=[RANGE_LEFT, RANGE_RIGHT]).execute()
    left = resp["valueRanges"][0].get("values", [])
    right = resp["valueRanges"][1].get("values", [])

    rows = []
    for i in range(max(len(left), len(right))):
        lrow = left[i] if i < len(left) else []
        rrow = right[i] if i < len(right) else []
        rec = {c: (lrow[j].strip() if j < len(lrow) else "") for j, c in enumerate(LEFT_COLS)}
        rec.update({c: (rrow[j].strip() if j < len(rrow) else "") for j, c in enumerate(RIGHT_COLS)})
        rec["_sheet_row"] = i + 2
        rows.append(rec)
    return rows

# ── filtering ────────────────────────────────────────────────────────────────

def parse_date(value: str):
    """Parse a sheet date cell. Returns None for 'n.a.', blanks, junk."""
    v = (value or "").strip()
    if not v or v.lower() in {"n.a.", "n/a", "na", "none", "-"}:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(v[:len(v)], fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def row_date(r: dict):
    """Date Ingested is authoritative; Pitch Date is the fallback."""
    return parse_date(r.get("date_ingested", "")) or parse_date(r.get("pitch_date", ""))


def passes_info_gate(r: dict) -> bool:
    """True when a row carries enough substance to write a paragraph about.

    Three hard requirements: a written evaluation, a linkable source (readers
    are sent to the original pitch), and enough combined prose that the summary
    is not just a restatement of the company name.
    """
    if not r.get("total_evaluation"):
        return False
    if not r.get("link", "").startswith("http"):
        return False
    body = len(r.get("brief_summary", "")) + len(r.get("total_evaluation", "")) + len(r.get("notes", ""))
    return body >= 900


def score_of(r: dict) -> int:
    try:
        return int(float(r.get("total_score") or 0))
    except (TypeError, ValueError):
        return 0

# ── text cleaning ────────────────────────────────────────────────────────────

VERDICT_LEAD = re.compile(
    r"^\s*(?:this\s+(?:pitch|company|situation)\s+(?:is|scores)\s+)?"
    r"(no[-\s]?brainer|interesting(?:\s+but\s+not\s+a\s+no[-\s]?brainer)?|pass)"
    r"\s*[.:—–-]+\s*",
    re.I,
)
SCORE_FRAGMENT = re.compile(r"\b(?:scores?\s+)?\d{1,2}\s*/\s*50\b|\b[VPDM]:\s*\d{1,2}\b|\bCA:\s*\d{1,2}\b", re.I)
CASE_STUDY_MARKERS = re.compile(
    r"case[-\s]?stud|case_studies|resembles?\b|analog|mirrors\b|"
    r"pattern matches|alignment check|index\.md|this session's",
    re.I,
)
SPECIAL_TAG = re.compile(r"\bSPECIAL SITUATION:\s*(?:Yes|No)\.?", re.I)
# Internal pipeline plumbing that must never reach a reader.
PID_REF = re.compile(r"\(?\bpid\s+[0-9a-f]{6,}\)?", re.I)
INTERNAL_MARKERS = re.compile(
    r"same article as|evaluated separately as pitches|meta\.json|"
    r"per this project's|this session's|\bpids\b",
    re.I,
)
VERDICT_WORD = re.compile(r"\b(no[-\s]?brainer|clears the bar|does not clear the bar)\b", re.I)


def strip_editorial(text: str) -> str:
    """Remove verdict labels, numeric scores and case-study analogies.

    The newsletter shows neither the verdict nor the score, and the owner asked
    for case-study comparisons to be dropped, so this runs before the copy is
    ever drafted rather than relying on the writer to omit them.
    """
    if not text:
        return ""
    t = PID_REF.sub("", SPECIAL_TAG.sub(" ", text))
    t = VERDICT_LEAD.sub("", t.strip())
    sentences = re.split(r"(?<=[.!?])\s+", t)
    kept = [
        s for s in sentences
        if s.strip()
        and not CASE_STUDY_MARKERS.search(s)
        and not VERDICT_WORD.search(s)
        and not INTERNAL_MARKERS.search(s)
    ]
    out = " ".join(kept)
    out = SCORE_FRAGMENT.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([.,;])", r"\1", out)
    out = re.sub(r"\(\s*[,;]?\s*\)", "", out).strip()
    return out

# ── build ────────────────────────────────────────────────────────────────────

def read_rows(source: str = "csv") -> list[dict]:
    return read_rows_csv() if source == "csv" else read_rows_api()


def build(kind: str, days: int, limit: int, as_of: date, ignore_dates: bool = False,
          source: str = "csv") -> dict:
    rows = read_rows(source)
    cutoff = as_of - timedelta(days=days)

    stats = {"total_rows": len(rows), "undated": 0, "out_of_window": 0,
             "wrong_type": 0, "failed_info_gate": 0}

    candidates = []
    for r in rows:
        if not r.get("company") and not r.get("ticker"):
            continue
        d = row_date(r)
        if d is None:
            # Legacy backlog: the sheet only started carrying dates in Aug 2026,
            # and undated rows are deliberately never pulled by the weekly run.
            if not ignore_dates:
                stats["undated"] += 1
                continue
        elif not (cutoff <= d <= as_of) and not ignore_dates:
            stats["out_of_window"] += 1
            continue
        # The special-situations issue is a strict subset; the pitches issue covers
        # everything, ranked purely by score. Overlap between the two is intended —
        # a strong special situation can earn a place in both.
        if kind == "special" and not r.get("special_situation", "").lower().startswith("yes"):
            stats["wrong_type"] += 1
            continue
        if not passes_info_gate(r):
            stats["failed_info_gate"] += 1
            continue
        r["_date"] = d.isoformat() if d else ""
        r["_score"] = score_of(r)
        candidates.append(r)

    candidates.sort(key=lambda r: (r["_score"], r["_date"]), reverse=True)
    selected = candidates[:limit]

    categories = SITUATION_CATEGORIES if kind == "special" else STYLE_CATEGORIES
    fallback = "Other Corporate Action / Turnaround" if kind == "special" else "Other / Turnaround"

    entries = []
    for r in selected:
        payload = {
            "notes": r.get("notes", ""),
            "total_evaluation": r.get("total_evaluation", ""),
            "valuation_explanation": r.get("valuation_explanation", ""),
            "durability_explanation": r.get("durability_explanation", ""),
            "capital_allocation_explanation": r.get("capital_allocation_explanation", ""),
            "company": r.get("company", ""),
            "ticker": r.get("ticker", ""),
            "special_situation": r.get("special_situation", ""),
            "total_score": r.get("total_score", ""),
        }
        cat = classify_situation(payload) if kind == "special" else classify_strategy(payload)
        if cat not in categories:
            cat = fallback
        entries.append({
            "ticker": r.get("ticker", ""),
            "company": r.get("company", ""),
            "link": r.get("link", ""),
            "date": r["_date"],
            "category": cat,
            "_score": r["_score"],          # ordering only — never rendered
            "brief_summary": strip_editorial(r.get("brief_summary", "")),
            "evaluation": strip_editorial(r.get("total_evaluation", "")),
            "notes": strip_editorial(r.get("notes", "")),
            "pitch_id": r.get("pitch_id", ""),
        })

    grouped = {c: [e for e in entries if e["category"] == c] for c in categories}
    grouped = {c: v for c, v in grouped.items() if v}

    return {
        "kind": kind,
        "generated": as_of.isoformat(),
        # The renderer titles the issue with the window. A backfill ignores the
        # window entirely, so it must not be presented as a week's worth of news.
        "ignore_dates": ignore_dates,
        "window_start": cutoff.isoformat(),
        "window_end": as_of.isoformat(),
        "total_selected": len(entries),
        "candidates_in_window": len(candidates),
        "category_order": [c for c in categories if c in grouped],
        "counts": {c: len(v) for c, v in grouped.items()},
        "stats": stats,
        "entries": entries,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", dest="kind", choices=["special", "pitches"], required=True)
    ap.add_argument("--days", type=int, default=7, help="look-back window in days (default 7)")
    ap.add_argument("--limit", type=int, default=50, help="max entries (default 50)")
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD; defaults to today")
    ap.add_argument("--ignore-dates", action="store_true",
                    help="BACKFILL/TESTING ONLY: ignore the date window and rank the whole "
                         "sheet, including undated legacy rows. The weekly routine must never "
                         "use this — it would re-publish old pitches.")
    ap.add_argument("--sheet-id", default=None,
                    help="Google Sheet ID. Overrides PITCHES_SHEET_ID. Never committed to this repo.")
    ap.add_argument("--source", choices=["csv", "api"], default="csv",
                    help="csv (default): no-credential gviz export, used by the cloud routine. "
                         "api: authenticated Sheets API, needs token.json.")
    ap.add_argument("--out", default=None, help="output path (default .tmp/newsletter_<type>_<date>.json)")
    args = ap.parse_args()

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    if args.sheet_id:
        global SHEET_ID
        SHEET_ID = args.sheet_id

    data = build(args.kind, args.days, args.limit, as_of,
                 ignore_dates=args.ignore_dates, source=args.source)
    if args.ignore_dates:
        print("  !! --ignore-dates: date window disabled (backfill mode)")

    TMP_DIR.mkdir(exist_ok=True)
    out = Path(args.out) if args.out else TMP_DIR / f"newsletter_{args.kind}_{as_of.isoformat()}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    s = data["stats"]
    print(f"[{args.kind}] window {data['window_start']} .. {data['window_end']}")
    print(f"  sheet rows              {s['total_rows']}")
    print(f"  skipped (no date)       {s['undated']}")
    print(f"  skipped (out of window) {s['out_of_window']}")
    print(f"  skipped (wrong type)    {s['wrong_type']}")
    print(f"  skipped (thin content)  {s['failed_info_gate']}")
    print(f"  candidates              {data['candidates_in_window']}")
    print(f"  selected                {data['total_selected']}")
    for c in data["category_order"]:
        print(f"     {data['counts'][c]:3d}  {c}")
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
