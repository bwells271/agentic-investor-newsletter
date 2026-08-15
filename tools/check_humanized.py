"""
check_humanized.py

Gate on newsletter copy before it is rendered. Scans every entry's written
`summary` for the AI tells catalogued in the humanizer skill, plus the
project-specific rules (no verdicts, no scores), and exits non-zero if any
entry fails.

This exists because "run it through the humanizer" is easy to skip or do
half-way. The workflow is not finished until this passes.

Usage:
    python3 tools/check_humanized.py --input .tmp/newsletter_special_2026-08-15.json
    python3 tools/check_humanized.py --input ... --strict   # also fail on soft warnings
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Hard failures — these must never survive into a published issue.
HARD = [
    ("em/en dash", re.compile(r"[—–]")),
    ("curly quote", re.compile(r"[“”‘’]")),
    ("verdict label", re.compile(r"\b(no[-\s]?brainer|clears the bar)\b", re.I)),
    ("score", re.compile(r"\b\d{1,2}\s*/\s*50\b|\b[VPDM]:\s?\d|\bCA:\s?\d")),
    ("case-study analogy", re.compile(r"case[-\s]?stud|resembles\b|analog(?:ous|y)\b|pattern matches", re.I)),
    ("internal plumbing", re.compile(r"\bpid\s+[0-9a-f]{6,}|same article as|meta\.json", re.I)),
    ("chatbot artifact", re.compile(r"\b(I hope this helps|let me know|here'?s what you need to know|of course!)", re.I)),
    ("emoji", re.compile("[\U0001F300-\U0001FAFF✀-➿]")),
]

# Soft warnings — style tells worth a second look, not automatically fatal.
AI_WORDS = [
    "crucial", "pivotal", "underscore", "underscores", "highlights", "showcase",
    "showcases", "delve", "robust", "compelling", "significantly", "notably",
    "testament", "vibrant", "tapestry", "landscape of", "intricate", "foster",
    "fostering", "garner", "enhance", "enhances", "boasts", "stands as",
    "serves as", "it is worth noting", "it's worth noting", "in order to",
    "due to the fact", "at this point in time", "plays a key role",
    "plays a crucial role", "navigate the", "in the realm of",
]
SOFT = [
    ("AI vocabulary", re.compile(r"\b(" + "|".join(re.escape(w) for w in AI_WORDS) + r")\b", re.I)),
    ("negative parallelism", re.compile(
        r"not (?:just|only|merely)\b[^.]{0,80}?\b(?:but|it'?s|it is|they'?re|they are)\b"
        r"|isn'?t (?:just|merely|only)\b|aren'?t (?:just|merely|only)\b", re.I)),
    ("signposting", re.compile(r"\b(let'?s (dive|explore|break)|without further ado|here'?s the thing)\b", re.I)),
    ("hedge stack", re.compile(r"\b(could potentially|might possibly|may perhaps)\b", re.I)),
]

MIN_WORDS, MAX_WORDS = 45, 130


def check(entry: dict) -> tuple[list[str], list[str]]:
    label = entry.get("ticker") or entry.get("company") or "?"
    text = (entry.get("summary") or "").strip()
    hard, soft = [], []

    if not text:
        return [f"{label}: no written summary (would fall back to raw sheet copy)"], []

    for name, rx in HARD:
        for m in rx.finditer(text):
            hard.append(f"{label}: {name} -> {m.group(0)!r}")
    for name, rx in SOFT:
        seen = set()
        for m in rx.finditer(text):
            g = m.group(0).lower()
            if g not in seen:
                seen.add(g)
                soft.append(f"{label}: {name} -> {m.group(0)!r}")

    n = len(text.split())
    if n < MIN_WORDS:
        soft.append(f"{label}: only {n} words (target 60-110)")
    elif n > MAX_WORDS:
        soft.append(f"{label}: {n} words, too long (target 60-110)")

    return hard, soft


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--strict", action="store_true", help="treat soft warnings as failures too")
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    entries = data.get("entries", [])

    all_hard, all_soft = [], []
    for e in entries:
        h, s = check(e)
        all_hard += h
        all_soft += s

    print(f"checked {len(entries)} entries in {args.input}")
    if all_hard:
        print(f"\nFAIL — {len(all_hard)} hard problem(s):")
        for x in all_hard:
            print("  " + x)
    if all_soft:
        print(f"\n{len(all_soft)} soft warning(s):")
        for x in all_soft:
            print("  " + x)
    if not all_hard and not all_soft:
        print("clean — no AI tells detected")

    if all_hard or (args.strict and all_soft):
        print("\nRewrite the flagged summaries and run this again. Do not render until it passes.")
        sys.exit(1)
    print("\nPASS")


if __name__ == "__main__":
    main()
