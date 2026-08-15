# Workflow: Weekly Substack Newsletter

Produces the two weekly Substack issues from the evaluated-pitches Google Sheet:

| Issue | `--type` | Contents | Grouping |
|---|---|---|---|
| Special Situations | `special` | rows where `Special Situation? = Yes` | situation type (12 categories) |
| Stock Pitches | `pitches` | every pitch in the window | investment-idea type (8 categories) |

The two issues **overlap on purpose** — a strong special situation can appear in both.

## Hard rules

1. **Never write to the Google Sheet.** It is user-owned and hand-curated. This
   workflow reads it and nothing else. Do not run `push_to_sheet.py` or
   `update_sheet_rows.py` as part of the newsletter run.
2. **Never show verdicts or scores.** No No-Brainer / Interesting / Pass, no
   `34/50`, no `V:8 P:7 …`. Total Score decides which pitches make the cut and
   what order they appear in — the reader never sees it. `newsletter_data.py`
   strips this language before you see the copy; do not reintroduce it.
3. **No case-study analogies.** No "resembles Timberland (1998)", no references
   to the case study library. That is internal evaluation machinery.
4. **Never invent numbers.** Every figure in a summary must appear in the source
   material for that entry. If the material is thin, write a shorter paragraph.
5. **Every entry links to its source.** Handled by the renderer.

## Where this runs

Both issues run as **cloud routines**, so the machine can be off. Everything the
pipeline needs travels with the repo:

* The sheet is read over plain HTTPS via Google's gviz CSV export
  (`--source csv`, the default). No OAuth, no `token.json`, no secrets.
* The whole path is Python **standard library only** — verified with `python3 -S`.
  There is nothing to `pip install`.
* `--source api` remains available for local runs and is the fallback if the
  sheet is ever locked down so link-readers stop working. It needs `token.json`
  and does not work in the cloud.

## Steps

### 1. Build the data

```
python3 tools/newsletter_data.py --type special --days 7 --limit 50
python3 tools/newsletter_data.py --type pitches --days 7 --limit 50
```

Writes `.tmp/newsletter_<type>_<YYYY-MM-DD>.json`. The tool reports how many rows
were skipped and why.

Rows whose `Date Ingested` / `Pitch Date` is `n.a.` are **legacy backlog and are
skipped by design** — the sheet only began carrying dates in August 2026. A large
"skipped (no date)" count is expected and correct, not a bug.

`--ignore-dates` exists for backfill and testing only. **The weekly run must never
use it** — it would republish old pitches.

If `selected` is 0, stop. Report that there was nothing new this week and do not
produce an empty issue.

### 2. Write the summaries

Read the JSON. Each entry carries `brief_summary`, `evaluation` and `notes`
(already stripped of verdict/score/case-study language) plus `ticker`, `company`,
`category` and `link`.

For each entry write **one paragraph, 60–110 words**, that answers: what the
company is, why the pitcher thinks it is mispriced, and the single most important
catch. Lead with the substance, not the company name boilerplate.

Then **invoke the `humanizer` skill** and run every summary through it. The raw
sheet copy is model-written and carries the usual tells — em-dash pile-ups, rule
of three, "not just X but Y", inflated verbs, `-ing` clause analyses. Specifically:

- Vary sentence length. Some short ones.
- Cut "significantly", "robust", "compelling", "underscores", "highlights",
  "stands as", "serves as", "notably", "it's worth noting".
- Kill negative parallelism ("It's not just a distributor — it's a platform").
- No three-item lists unless there are genuinely three things.
- Plain verbs. "Trades at 7x earnings", not "is currently trading at a
  compelling 7x earnings multiple".
- Keep the specifics: tickers, multiples, prices, dates, percentages.

Write each result into that entry's `summary` field and save the JSON.

Entries left without a `summary` fall back to raw sheet copy at render time,
which reads like AI. Do not skip entries.

The humanizer skill is vendored into this repo at `.claude/skills/humanizer/`,
so it is available to cloud runs that have no access to a local skills
directory. Use it; do not approximate it from memory.

### 3. Check the copy (do not skip)

```
python3 tools/check_humanized.py --input .tmp/newsletter_<type>_<date>.json --strict
```

This is the gate that makes the humanizer step real rather than aspirational.
It fails on em dashes, curly quotes, leaked verdicts or scores, case-study
analogies, internal pitch-id plumbing, chatbot artifacts, emoji, missing
summaries, AI vocabulary, negative parallelism, signposting and out-of-range
length.

Rewrite whatever it flags and run it again. **Do not render until it exits 0.**

### 4. Render

```
python3 tools/render_newsletter.py --input .tmp/newsletter_special_<date>.json
python3 tools/render_newsletter.py --input .tmp/newsletter_pitches_<date>.json
```

Writes to `reports/`:
- `newsletter_<type>_<date>.md` — source of record
- `newsletter_<type>_<date>.html` — **paste this one into Substack**; headings,
  links and dividers survive the paste

### 5. Report back

Give the file paths, the entry count per category, and anything skipped that the
owner should know about (thin content, missing links, an unusually small week).

## Edge cases

- **Fewer than 50 in the window** — fine, publish what there is. Do not widen the
  window to pad the issue.
- **Zero entries** — stop at step 1 and say so.
- **A category with one entry** — fine, keep it. The grouping is editorial.
- **`manual://` links** — filtered out by the info gate, since readers can't follow them.
- **Token refresh fails** — `token.json` needs re-auth; this is an owner action.
