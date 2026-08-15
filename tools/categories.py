"""
categories.py

The two category taxonomies the newsletters group by, and the keyword
classifiers that assign an entry to one.

Lifted verbatim from the Stock Picking Agent report generators
(generate_special_situations_report.py and generate_no_brainers_pdf.py) so the
newsletter pipeline does not have to import a PDF report builder just to reach
two pure functions. Both classifiers read only the plain-text fields of a pitch
dict, so they have no dependencies beyond the standard library.

If the taxonomies change upstream, update them here too.
"""

from __future__ import annotations

import re  # noqa: F401  (used by the classifiers below)

# ── Special situations: grouped by situation type ────────────────────────────

SITUATION_CATEGORIES = [
    "Announced M&A / Tender Offers",
    "Broken / Blocked M&A",
    "Odd-Lot Tender",
    "Spinoffs & Demergers",
    "Asset Sales / Divestitures",
    "Strategic Review",
    "Liquidation / Wind-Down",
    "Post-Bankruptcy Emergence",
    "Regulatory / Legal / Arbitration",
    "Activist / Proxy Fight",
    "Capital Return / Holdco / Contractual",
    "Other Corporate Action / Turnaround",
]

def classify(d: dict) -> str:
    text = " ".join([
        d.get("notes", ""),
        d.get("total_evaluation", ""),
        d.get("valuation_explanation", ""),
        d.get("capital_allocation_explanation", ""),
    ]).lower()

    # Order matters — more specific patterns first
    if any(x in text for x in ["odd-lot", "odd lot", "odd lot tender"]):
        return "Odd-Lot Tender"

    if any(x in text for x in ["post-bankruptcy", "post bankruptcy", "emerged from bankruptcy",
                                 "emerging from bankruptcy", "chapter 11", "chapter11",
                                 "reorganization plan", "emerged from chapter"]):
        return "Post-Bankruptcy Emergence"

    if any(x in text for x in ["icsid", "arbitration", "legal claim", "court order",
                                 "fcc approval", "fcc reconfiguration",
                                 "dpa authorization", "regulatory binary", "legal arbitration",
                                 "regulatory / legal", "regulatory/legal",
                                 "fca ruling", "fca final", "fca motor",
                                 "cpt code", "cpt category", "cms reimbursement", "cms cut",
                                 "fda approval", "fda pma", "fda pma granted",
                                 "reimbursement code", "cpb approval"]):
        return "Regulatory / Legal / Arbitration"

    if any(x in text for x in ["broken deal", "blocked deal", "failed acquisition",
                                 "ftc blocked", "deal break", "deal fell through",
                                 "broken m&a", "blocked m&a", "m&a chill",
                                 "acquisition artificially", "blocked by ftc",
                                 "deal was blocked", "deal blocked"]):
        return "Broken / Blocked M&A"

    if any(x in text for x in ["spinoff", "spin-off", "spin off", "demerger",
                                 "spun off", "spinning off", "demerges",
                                 "vivendi spinoff", "versigent", "stub trade",
                                 "separation of", "separation into"]):
        return "Spinoffs & Demergers"

    if any(x in text for x in ["proxy fight", "proxy battle", "activist campaign",
                                 "activist intervention", "activist-driven", "stonehouse capital",
                                 "altai capital", "proxy contest", "board contest",
                                 "activist pressure", "proxy card", "strategic capital activist",
                                 "activist / proxy", "activist holder", "kawa cooperation",
                                 "donerail", "activist bid", "activist-owned",
                                 "activist is pushing", "activist is pressuring",
                                 "activist pushing", "shareholder activist",
                                 "board fight", "board shake-up"]):
        return "Activist / Proxy Fight"

    if any(x in text for x in ["liquidation", "wind-down", "winding down", "wind down",
                                 "liquidating", "run-off", "runoff", "distributing assets",
                                 "asset distribution", "liquidation arb", "liquidation stub",
                                 "dissolution", "wind down approved", "liquidation plan",
                                 "wind-down since", "actively liquidat"]):
        return "Liquidation / Wind-Down"

    if any(x in text for x in ["holdco", "holding company", "holding co",
                                 "contractual put", "contractual payment",
                                 "envalior put", "put on envalior",
                                 "debt restructuring returning", "return of capital",
                                 "mlp distribution", "k-1", "master limited partnership"]):
        return "Capital Return / Holdco / Contractual"

    if any(x in text for x in ["nav discount", "nav of", "discount to nav"]):
        if any(x in text for x in ["buyback", "capital return", "holdco", "holding company",
                                    "closed-end", "investment trust", "b-share return"]):
            return "Capital Return / Holdco / Contractual"

    if any(x in text for x in ["definitive agreement", "definitive merger", "tender offer",
                                 "merger arb", "merger arbitrage", "announced acquisition",
                                 "acquisition agreement", "binding offer", "firm offer",
                                 "announced deal", "acquisition price", "deal spread",
                                 "arb spread", "going private", "take private",
                                 "scheme of arrangement", "formal offer",
                                 "lkcm", "pure casino", "gfl environmental", "beretta",
                                 "bally's intralot", "bally's has until"]):
        return "Announced M&A / Tender Offers"

    if any(x in text for x in ["strategic review", "strategic alternatives",
                                 "strategic process", "exploring a sale", "potential sale",
                                 "formal review", "sale process",
                                 "goldman sachs strategic", "strategic alternatives review"]):
        return "Strategic Review"

    if any(x in text for x in ["asset sale", "divestiture", "divestment", "divesting",
                                 "sale of division", "segment sale", "business sale",
                                 "selling assets", "asset disposal", "asset monetization",
                                 "forced asset sale", "sotp", "sum-of-parts",
                                 "sum of parts", "clean earth sale", "e&p sale",
                                 "ep sale", "colombian e&p"]):
        return "Asset Sales / Divestitures"

    if any(x in text for x in ["capital return", "special dividend",
                                 "return of capital", "holdco discount",
                                 "de-spac", "de spac", "spac warrant"]):
        return "Capital Return / Holdco / Contractual"

    return "Other Corporate Action / Turnaround"

# ── Regular pitches: grouped by investment-idea type ─────────────────────────

STYLE_CATEGORIES = [
    "High-Quality Compounder",
    "Net-Net / Asset Discount",
    "Hidden Asset / SOTP",
    "Cyclical / Commodity Recovery",
    "Specialty Financials (Bank / Insurance / Broker)",
    "Special Situation (M&A / Liquidation / Conversion / Activist)",
    "Earnings-Cheap Microcap",
    "Other / Turnaround",
]

def classify_strategy(d: dict) -> str:
    """Classify a No-Brainer pitch by investment-style category.

    Order matters: more specific patterns checked first.
    """
    text = " ".join([
        d.get("notes", "") or "",
        d.get("total_evaluation", "") or "",
        d.get("valuation_explanation", "") or "",
        d.get("durability_explanation", "") or "",
        d.get("capital_allocation_explanation", "") or "",
        d.get("company", "") or "",
    ]).lower()

    ticker = (d.get("ticker", "") or "").lower()
    company = (d.get("company", "") or "").lower()
    is_special = (d.get("special_situation", "") or "").lower() == "yes"

    # 1) Specialty financials — banks, insurance, brokers (priority over special-sit)
    if any(k in text for k in [
        "community bank", "regional bank", "tangible book", "0.68x tbv", "0.7x tbv",
        "bancorp", "savings bank", "thrift", "insurance company",
        "brokerage", "broker", "deposit franchise", "community-bank",
        "core deposit", "loan book", "tier 1 leverage", "cancer of fdic",
    ]) or any(k in company for k in [
        "bank", "bancorp", "fintech", "financial", "insurance", "insurer",
    ]) or any(k in text for k in ["brokerage", "tiger brokers", "up fintech"]):
        # If it's also a special situation (thrift conversion, M&A bank), prefer Specialty Financials
        return "Specialty Financials (Bank / Insurance / Broker)"

    # 2) Special situations (announced M&A, liquidation, conversion, post-bankruptcy, activist)
    if is_special or any(k in text for k in [
        "definitive agreement", "announced acquisition", "tender offer",
        "merger arb", "going private", "take private",
        "liquidation", "wind-down", "winding down", "wind down",
        "thrift conversion", "mutual-to-stock", "mutual to stock",
        "post-bankruptcy", "emerged from bankruptcy", "chapter 11",
        "spinoff", "spin-off", "demerger",
        "strategic review", "strategic alternatives",
        "activist", "proxy fight", "cooperation agreement",
        "odd-lot", "warrant arbitrage", "stub trade",
    ]):
        return "Special Situation (M&A / Liquidation / Conversion / Activist)"

    # 3) Net-net / asset discount
    if any(k in text for k in [
        "net-net", "net net", "ncav", "sub-net-cash", "sub net cash",
        "below net cash", "net cash position", "sub-tangible book",
        "sub tangible book", "below tangible book", "0.21x book",
        "asset discount", "discount to net cash", "discount to liquidation",
        "discount to tangible book", "extreme asset discount",
    ]):
        return "Net-Net / Asset Discount"

    # 4) Hidden asset / SOTP
    if any(k in text for k in [
        "hidden asset", "hidden value", "sotp", "sum-of-parts", "sum of parts",
        "nav discount", "discount to nav", "holding company", "holdco discount",
        "spectrum", "real estate at cost", "minority stake",
        "embedded asset", "off-balance-sheet asset",
    ]):
        return "Hidden Asset / SOTP"

    # 5) Cyclical / commodity recovery
    if any(k in text for k in [
        "cyclical", "cycle low", "cycle trough", "commodity",
        "oil tanker", "shipping rate", "drilling", "e&p", "upstream oil",
        "commodity producer", "fertilizer", "mining", "lithium",
        "natural gas", "gas company", "utility monopoly",
        "cycle recovery", "cycle bottom", "trough multiple",
    ]):
        return "Cyclical / Commodity Recovery"

    # 6) High-quality compounder (PEG <1, durable franchise, share cannibal)
    if any(k in text for k in [
        "share cannibal", "buyback at trough", "buyback below intrinsic",
        "peg <1", "peg below 1", "peg of 0", "peg 0",
        "high-quality compounder", "high quality compounder",
        "durable franchise", "moat", "network effect", "high roic",
        "exceptional roic", "structural moat", "compounder",
        "two-sided network", "vertical market software", "vms",
    ]):
        return "High-Quality Compounder"

    # 7) Earnings-cheap microcap (sub-5x or sub-10x on smaller, less-quality biz)
    if any(k in text for k in [
        "sub-5x", "sub-10x", "single-digit p/e", "single digit p/e",
        "5x earnings", "low multiple",
        "microcap", "micro-cap", "obscure-otc", "obscure otc",
        "below market cap",
    ]):
        return "Earnings-Cheap Microcap"

    return "Other / Turnaround"
