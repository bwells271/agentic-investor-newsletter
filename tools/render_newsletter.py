"""
render_newsletter.py

Turns a newsletter JSON (from newsletter_data.py, after the writing step has
filled in each entry's "summary") into Substack-ready output.

Writes two files so either paste route works:
  reports/newsletter_<type>_<date>.md    markdown source of record
  reports/newsletter_<type>_<date>.html  paste this into the Substack editor;
                                           headings, links and rules survive intact

Entries with no written "summary" fall back to the sheet's Brief Summary, so a
draft is still produced if the writing step is skipped.

Deliberately absent from the output: verdict labels, factor scores, totals, and
case-study analogies. Score decides ordering only.

Usage:
    python3 tools/render_newsletter.py --input .tmp/newsletter_special_2026-08-15.json
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"

TITLES = {
    "special": "Special Situations",
    "pitches": "Stock Pitches",
}

INTROS = {
    "special": (
        "Corporate actions worth a look from this week's reading: mergers, spinoffs, "
        "liquidations, activist campaigns and the rest. Grouped by situation type. "
        "Every entry links back to the original pitch."
    ),
    "pitches": (
        "This week's stock pitches, grouped by the kind of idea they are. "
        "Every entry links back to the original write-up so you can go deeper on "
        "anything that catches your eye."
    ),
}

DISCLAIMER = (
    "*Nothing here is investment advice. These are summaries of other people's published "
    "pitches, collected and condensed. They are not recommendations, and not positions I hold "
    "unless I say so. Do your own work before risking money.*"
)


def entry_summary(e: dict) -> str:
    s = (e.get("summary") or "").strip()
    if s:
        return s
    # Fallback: sheet copy, already stripped of verdict/case-study language.
    return (e.get("brief_summary") or e.get("evaluation") or "").strip()


PLACEHOLDER_TICKERS = {"UNKNOWN", "N/A", "NA", "NONE", "TBD", "-", "?"}


def heading(e: dict) -> str:
    """`Company (TICKER)`, dropping placeholder tickers.

    Parentheses rather than a dash: em dashes are the most recognisable tell of
    machine-written copy, and the whole point of the humanizer pass is that this
    newsletter does not read that way. No separator in the template may use one.

    Some pitches are written about unnamed companies (thrift conversions, for
    instance), where the sheet carries UNKNOWN. Printing that in a headline
    looks like a bug, so fall back to the company name alone.
    """
    ticker = (e.get("ticker") or "").strip()
    company = (e.get("company") or "").strip()
    if ticker.upper() in PLACEHOLDER_TICKERS:
        ticker = ""
    if ticker and company:
        return f"{company} ({ticker})"
    return company or ticker or "Untitled"


def build_markdown(data: dict, title_date: str) -> str:
    kind = data["kind"]
    out = [f"# {TITLES[kind]} ({title_date})", "", INTROS[kind], ""]

    for cat in data["category_order"]:
        entries = [e for e in data["entries"] if e["category"] == cat]
        if not entries:
            continue
        out.append(f"## {cat}")
        out.append("")
        for e in entries:
            out.append(f"### {heading(e)}")
            out.append("")
            summary = entry_summary(e)
            if summary:
                out.append(summary)
                out.append("")
            link = (e.get("link") or "").strip()
            if link.startswith("http"):
                out.append(f"[Read the original pitch →]({link})")
                out.append("")
        out.append("---")
        out.append("")

    out.append(DISCLAIMER)
    out.append("")
    return "\n".join(out)


def build_html(data: dict, title_date: str) -> str:
    kind = data["kind"]
    esc = html.escape
    parts = [
        "<h1>%s (%s)</h1>" % (esc(TITLES[kind]), esc(title_date)),
        "<p>%s</p>" % esc(INTROS[kind]),
    ]
    for cat in data["category_order"]:
        entries = [e for e in data["entries"] if e["category"] == cat]
        if not entries:
            continue
        parts.append("<h2>%s</h2>" % esc(cat))
        for e in entries:
            parts.append("<h3>%s</h3>" % esc(heading(e)))
            summary = entry_summary(e)
            if summary:
                for para in re.split(r"\n{2,}", summary):
                    if para.strip():
                        parts.append("<p>%s</p>" % esc(para.strip()))
            link = (e.get("link") or "").strip()
            if link.startswith("http"):
                parts.append('<p><a href="%s">Read the original pitch →</a></p>' % esc(link, quote=True))
        parts.append("<hr>")
    parts.append("<p><em>%s</em></p>" % esc(DISCLAIMER.strip("*")))
    body = "\n".join(parts)
    return (
        "<!doctype html><meta charset=\"utf-8\">"
        "<title>%s (%s)</title>\n%s\n" % (esc(TITLES[kind]), esc(title_date), body)
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="newsletter JSON from newsletter_data.py")
    ap.add_argument("--out-dir", default=str(REPORTS_DIR))
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    kind = data["kind"]
    gen = data.get("generated") or date.today().isoformat()
    title_date = date.fromisoformat(gen).strftime("%B %d, %Y")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"newsletter_{kind}_{gen}.md"
    html_path = out_dir / f"newsletter_{kind}_{gen}.html"

    md = build_markdown(data, title_date)
    html = build_html(data, title_date)

    # Nothing reaches Substack with an em or en dash in it. The copy gate checks
    # the summaries, but the template used to smuggle its own in through the
    # headings, so the finished document is checked too.
    for label, text in (("markdown", md), ("html", html)):
        bad = [ln for ln in text.splitlines() if "\u2014" in ln or "\u2013" in ln]
        if bad:
            print(f"\n  refusing to write: {len(bad)} em/en dash(es) in the {label}:")
            for ln in bad[:5]:
                print("    " + ln.strip()[:100])
            sys.exit("  Fix the template or the copy, then render again.")

    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")

    written = sum(1 for e in data["entries"] if (e.get("summary") or "").strip())
    print(f"[{kind}] {data['total_selected']} entries across {len(data['category_order'])} categories")
    print(f"  written summaries: {written}/{data['total_selected']}"
          + ("  (rest fell back to sheet copy)" if written < data["total_selected"] else ""))
    print(f"  -> {md_path}")
    print(f"  -> {html_path}")


if __name__ == "__main__":
    main()
