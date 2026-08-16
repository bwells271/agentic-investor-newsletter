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


def title_period(data: dict) -> str:
    """The week the issue covers, as a readable range.

    A backfill has no meaningful window (it ranks the whole sheet regardless of
    date), so it falls back to the generation date rather than claiming to cover
    a week it did not.
    """
    gen = data.get("generated") or date.today().isoformat()
    gen_str = _long_date(date.fromisoformat(gen))

    if data.get("ignore_dates"):
        return gen_str

    start, end = data.get("window_start"), data.get("window_end")
    if not (start and end):
        return gen_str

    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a == b:
        return _long_date(b)
    if a.year != b.year:
        return f"{_long_date(a)} to {_long_date(b)}"
    if a.month != b.month:
        return f"{a.strftime('%B')} {a.day} to {_long_date(b)}"
    return f"{a.strftime('%B')} {a.day} to {b.day}, {b.year}"


def _long_date(d: date) -> str:
    # Built by hand rather than with %-d, which is not portable.
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def build_markdown(data: dict, title_date: str) -> str:
    kind = data["kind"]
    out = [f"# {TITLES[kind]} ({title_date})", "", INTROS[kind], ""]

    for cat in data["category_order"]:
        entries = [e for e in data["entries"] if e["category"] == cat]
        if not entries:
            continue
        out.append(f"### {cat}")
        out.append("")
        for e in entries:
            # Bold, not a heading. Substack renders even an h3 at display size,
            # which swamps a 50-entry digest. The company name only needs to
            # outrank body text, not shout.
            out.append(f"**{heading(e)}**")
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
        parts.append("<h3>%s</h3>" % esc(cat))
        for e in entries:
            parts.append(
                '<p style="margin:1.4em 0 0.4em"><strong style="font-size:1.15em">'
                "%s</strong></p>" % esc(heading(e))
            )
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
    return PAGE % {
        "title": esc("%s (%s)" % (TITLES[kind], title_date)),
        "body": body,
    }


# One button that puts the rendered article on the clipboard as rich text, so a
# Substack paste keeps bold, links and dividers. Copying the raw HTML source
# instead would paste as visible markup, and hand-dragging a 50-entry selection
# tends to clip the first or last line.
PAGE = """<!doctype html><meta charset="utf-8">
<title>%(title)s</title>
<style>
  /* Explicit light background. This page mirrors how the issue will look in
     Substack, which is light, and a viewer in dark mode would otherwise show
     dark text on its own dark ground. */
  html { background: #fff; }
  body { max-width: 44rem; margin: 2rem auto; padding: 0 1.25rem;
         font: 17px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Georgia, serif;
         color: #1a1a1a; background: #fff; }
  h1 { font-size: 1.9em; line-height: 1.2; }
  h3 { font-size: 1.05em; text-transform: uppercase; letter-spacing: .06em;
       color: #666; margin: 2.4em 0 .2em; font-weight: 600; }
  a { color: #1a1a1a; }
  hr { border: 0; border-top: 1px solid #e3e3e3; margin: 2em 0; }
  #bar { position: sticky; top: 0; background: #fff; padding: .9rem 0; z-index: 5;
         border-bottom: 1px solid #eee; margin-bottom: 1.5rem; }
  #copy { font: inherit; font-size: .95rem; padding: .55rem 1.1rem; cursor: pointer;
          border: 1px solid #1a1a1a; background: #1a1a1a; color: #fff; border-radius: 6px; }
  #copy:hover { background: #333; }
  #done { margin-left: .8rem; color: #157f3d; font-size: .9rem; visibility: hidden; }
</style>
<div id="bar">
  <button id="copy">Copy for Substack</button>
  <span id="done">Copied. Paste into the Substack editor.</span>
</div>
<article id="article">
%(body)s
</article>
<script>
document.getElementById('copy').addEventListener('click', async function () {
  var article = document.getElementById('article');
  var done = document.getElementById('done');

  function say(msg, ok) {
    done.textContent = msg;
    done.style.color = ok ? '#157f3d' : '#a3261b';
    done.style.visibility = 'visible';
    setTimeout(function () { done.style.visibility = 'hidden'; }, 4000);
  }

  // Rich HTML on the clipboard is what makes the Substack paste keep bold text,
  // links and dividers. Needs a secure context, which file:// satisfies in
  // Chrome and Safari but a data: URL does not.
  if (navigator.clipboard && navigator.clipboard.write && window.ClipboardItem) {
    try {
      await navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([article.innerHTML], {type: 'text/html'}),
        'text/plain': new Blob([article.innerText], {type: 'text/plain'})
      })]);
      say('Copied. Paste into the Substack editor.', true);
      return;
    } catch (err) { /* fall through */ }
  }

  // Select-and-copy works in more places and still carries formatting.
  try {
    var range = document.createRange();
    range.selectNodeContents(article);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    var ok = document.execCommand('copy');
    sel.removeAllRanges();
    if (ok) { say('Copied. Paste into the Substack editor.', true); return; }
  } catch (err) { /* fall through */ }

  // Last resort: leave the article selected so one keystroke finishes the job.
  var range2 = document.createRange();
  range2.selectNodeContents(article);
  var sel2 = window.getSelection();
  sel2.removeAllRanges();
  sel2.addRange(range2);
  say('Selected the whole issue. Press Cmd+C to copy.', false);
});
</script>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="newsletter JSON from newsletter_data.py")
    ap.add_argument("--out-dir", default=str(REPORTS_DIR))
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    kind = data["kind"]
    gen = data.get("generated") or date.today().isoformat()
    title_date = title_period(data)

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
