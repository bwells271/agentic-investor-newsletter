# Agentic Investor — Newsletter Generator

Builds the two weekly Substack issues from the evaluated-pitches Google Sheet.

| Issue | Contents | Grouped by |
|---|---|---|
| Special Situations | rows flagged `Special Situation? = Yes` | situation type (12 categories) |
| Stock Pitches | every pitch in the window | investment-idea type (8 categories) |

The two overlap on purpose: a strong special situation can appear in both.

## How it runs

Two weekly cloud routines. Each one follows `workflows/weekly_newsletter.md`.

```
python3 tools/newsletter_data.py --type special --days 7 --limit 50
#   ... draft a summary per entry, run it through the humanizer skill ...
python3 tools/check_humanized.py --input .tmp/newsletter_special_<date>.json --strict
python3 tools/render_newsletter.py --input .tmp/newsletter_special_<date>.json
```

Output lands in `reports/` as both markdown and HTML. Paste the **HTML** into
Substack: headings, links and dividers survive the paste intact.

## Design notes

**No credentials.** The sheet is read over plain HTTPS through Google's gviz CSV
export, so there is no OAuth, no token, and nothing to leak. The column list
skips `Full Text`, which is roughly 60 MB of raw article text nothing downstream
needs.

**No dependencies.** The whole path is Python standard library. Verified with
`python3 -S`, which disables site-packages entirely.

**Read-only by construction.** `push_to_sheet.py` and `update_sheet_rows.py` are
the only code that can write to the sheet, and they are deliberately excluded
from this repo. A run here has no capability to modify it, whatever a prompt
might say.

**Undated rows are skipped on purpose.** The sheet only began carrying
`Date Ingested` / `Pitch Date` in August 2026. Everything before that reads
`n.a.` and is never republished. A large "skipped (no date)" count in the tool
output is expected, not a bug.

**Selection is by score, but score is never shown.** `Total Score` decides which
pitches make the cut and what order they appear in. Verdict labels
(No-Brainer / Interesting / Pass), factor scores and case-study analogies are
stripped before drafting, so the reader forms their own view.

**The humanizer is enforced, not requested.** The skill is vendored at
`.claude/skills/humanizer/` so cloud runs can reach it, and
`tools/check_humanized.py --strict` fails the run on em dashes, curly quotes,
leaked verdicts or scores, case-study analogies, AI vocabulary, negative
parallelism, signposting, chatbot artifacts, emoji and length drift. The
workflow forbids rendering until it exits 0.

## Files

```
tools/newsletter_data.py    read sheet, filter by date, rank, classify, strip editorial
tools/categories.py         the two taxonomies and their keyword classifiers
tools/check_humanized.py    AI-slop gate
tools/render_newsletter.py  Substack markdown + HTML
workflows/weekly_newsletter.md   the SOP both routines follow
```
