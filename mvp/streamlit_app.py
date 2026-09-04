"""Wishlist Decision Assistant — standalone Streamlit MVP.

Demo mode is fully offline (seeded JSON + deterministic rules).
Live mode makes one Groq chat call when a key is present in st.secrets.
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
SAMPLE_PATH = APP_DIR / "sample_wishlist.json"

LETTER_SIZES = ["XS", "S", "M", "L", "XL", "XXL"]
LETTER_TO_WAIST = {"XS": "26", "S": "28", "M": "30", "L": "32", "XL": "34", "XXL": "36"}

RUN_SMALL_KEYS = (
    "runs small",
    "run small",
    "sized small",
    "size up",
    "too tight",
    "quite snug",
)
RUN_LARGE_KEYS = (
    "runs large",
    "run large",
    "sized large",
    "size down",
    "too loose",
    "too baggy",
)
TRUE_SIZE_KEYS = (
    "true to size",
    "true-to-size",
    "perfect fit",
    "fits as expected",
    "as described",
)

GROQ_MODEL = "openai/gpt-oss-120b"

LIVE_DECISION_STATUSES = (
    "Ready to buy",
    "Check one thing first",
    "Compare first",
    "Worth waiting",
    "Reconsider this save",
    "Needs more information",
)

SYSTEM_PROMPT = """You are a wishlist decision assistant. The shopper already saved this item.

Use ONLY these supplied fields: size chart, measurements, reviews, save reason, intended use, occasion timing, comparison status, and unresolved questions. Optional stock notes, if present, are the user's own words — not live inventory.

Rules:
- Never invent a blocker that the user did not state.
- Never claim the user is price-watching unless they explicitly say they are watching price or waiting for a cheaper price.
- Never invent scarcity. Never treat stock notes as live inventory or as the sole reason to buy.
- Never recommend a discount, coupon, markdown, or waiting for a sale.
- If evidence is insufficient to recommend a size or a next action, set decision_status to "Needs more information".
- In fit_reason and decision_reason, explain which supplied evidence informed the recommendation. List those items in fit_evidence_used and decision_evidence_used.

Respond with ONLY valid JSON — no markdown, no code fences, no extra text. Exact schema:
{
  "fit_recommendation": "string",
  "fit_confidence": "High | Medium | Low",
  "fit_reason": "string",
  "fit_evidence_used": ["string"],
  "decision_status": "Ready to buy | Check one thing first | Compare first | Worth waiting | Reconsider this save | Needs more information",
  "decision_reason": "string",
  "next_step": "string",
  "decision_evidence_used": ["string"]
}
"""

CONF_COLORS = {"High": "#0f7b3c", "Medium": "#b45309", "Low": "#b42318"}

RESEARCH_INSIGHT = (
    "Wishlisted products often stall while shoppers resolve fit, compare "
    "alternatives or wait for a relevant need."
)
PROTO_BANNER = (
    "Prototype with simulated products, sample reviews, and simulated "
    "availability. This assistant supports your decision using available "
    "signals, but cannot guarantee fit. Simulated stock is not live inventory. "
    "No discounts or coupons."
)
FIT_NOTE = (
    "Supports your decision based on provided data, but cannot guarantee "
    "actual fit."
)

LETTER_SIZE_LABELS = {
    "XS": "XS (Extra Small)",
    "S": "S (Small)",
    "M": "M (Medium)",
    "L": "L (Large)",
    "XL": "XL (Extra Large)",
    "XXL": "XXL (2X Large)",
}

WISHLIST_ORDER = [
    "netplay-slim-shirt",
    "aurelia-printed-kurta",
    "dnmx-skinny-jeans",
    "and-aline-dress",
]

ITEM_VISUALS = {
    "netplay-slim-shirt": {
        "short_name": "Slim-Fit Cotton Work Shirt",
        "image": (
            "https://lh3.googleusercontent.com/aida-public/"
            "AB6AXuDT49GXGiWllsJ56CZveDhygcvvwxZj8LPw33Ti0-mgpczJlfHyzFNAVBEU"
            "EV5XsWFKRRU0jJ8KkmFqyrAl5Y7f1rwKSfjBfjYyOkz-slzxwtZ4xVjhQwf0QCnY"
            "3Zps9yQGdnxpXrhwpPxrKLlT9trX74n_wJHe42ygOnrMvKjbYJYKRdU5a0sTjg1h"
            "v2b-XLdM1GeMvGQX6sGevaD-8sImwbOgibHf2oQW6CQxEmksx1DczsEDUhWu"
        ),
        "detail_image": (
            "https://lh3.googleusercontent.com/aida-public/"
            "AB6AXuCPPCLwKFSpyU6huDFryYU85ci64vMWdLl3gwR7cEKI1gOvdxJDiyg593SH"
            "NR7JGFkGzUfCLUodrLk4Jk17oSkMOtG_FhvemsBVR1KtLk4mk62JNuA1zRWlq_rd"
            "i8f7ZTVF9Jta8Zmv9Lpz1V_GtdRjwwqUPRklX7evA3ByVZJ_GKbCavULyKO--"
            "68ha9Z2n4F0ghl9knykBUzj5v6yvDWxreLR-RMJjprg-rrZoTmRtnCTNc_U3Vqz"
        ),
        "reason_icon": "event_note",
    },
    "aurelia-printed-kurta": {
        "short_name": "Printed Straight Kurta",
        "image": (
            "https://lh3.googleusercontent.com/aida-public/"
            "AB6AXuCOzc0ka3UJAJT8sbg_eC8YP_ZlxV92Hlu_F4_5sB2O8YtEUwStQv_VP-nx"
            "FJ9cdcj761msuFlaHtDcdudOrxKy4-JHQ28s2OHPh2a2cZmUiLM79T5bFXfoyAkD"
            "Y3SgvlhinKeNbRppxdxZiDZx11DbPdOhkaueV7-hpT9g1GWensDAbGi0ZY0Oh3Ud"
            "6ym-F4VlhdnYMCQaqOEyJLEE6RQOz8hnmcohcEYUM4zgOqPX1jf0E5OlcPlU"
        ),
        "reason_icon": "favorite_border",
    },
    "dnmx-skinny-jeans": {
        "short_name": "Skinny-Fit Stretch Jeans",
        "image": (
            "https://lh3.googleusercontent.com/aida-public/"
            "AB6AXuCCcSCYpOokgNfRRlK5_P4OK6jUq4hI05iNS1IAJoWSfVSDWyOkqalmlds1"
            "QtYO07tvrf8RtBbfla7IRPbvMSByqHM_em0bZxAmBw_u6GkF4zCjAcEaQfPJYt41"
            "hpomvEfbJcwODIs-dWvJHcuo7ucG5H8awtTz20bWBinSS8EfMCjUWr2r9_4gmTp1"
            "arK2yQanSqLfnf5gOAmERU7P-UrNT6BfCUMt_W8cASygcNiZ46MjBb-x3hyL"
        ),
        "reason_icon": "tune",
    },
    "and-aline-dress": {
        "short_name": "Solid A-Line Midi Dress",
        "image": (
            "https://lh3.googleusercontent.com/aida-public/"
            "AB6AXuAwwjDM7ZtfuzHuv3jf_AF3FHuJwIT_Hwy0LgK5DdRaorwxr4PshwJ47hUa"
            "_P-3E8E1B4ffjQ38SHZrt8X7YQbeJ6ph4_3-KFVAAEWKqI4k6OTd-Z_Uqbx1b-Kl"
            "8bqY0aLq-_EaaAaWJf8L0y1DdWGrI1DSpFr0ePY6PJSU90smJUXAHgptXgIdjWZW"
            "0IWUglbHfe_184s6ubSxtbyaP5klKxQfkC3PxNDbfjqjN1cEXn-CuwTV4bcM"
        ),
        "reason_icon": "restaurant",
    },
}

LIVE_PLACEHOLDER_IMAGE = (
    "https://lh3.googleusercontent.com/aida-public/"
    "AB6AXuDChmYfmbufjUVH495kiFrm4w7VL6tC_DxLj1Sc0LTgOHqB9Xzt9ukQRR2v"
    "Ap5Yh_OSPG7QOcBTfg3xyHwU9QRB6ch8cQotlT-QcJy5xa5BMWxS7EjW5dP9dlMj"
    "54t3cCT37bSwcAyNBx1-wk3tLSMf6kcwIKqmxEndILut3oinFuLMBRYgC1Dz86xL"
    "dIrsgpPOscTONEtD4v6ZnO79r6PaUY7Wi1Dk-3OumfmZTiX4CVD8takKWvCw"
)
INSUFFICIENT_IMAGE = (
    "https://lh3.googleusercontent.com/aida-public/"
    "AB6AXuAYByki2jWB8e4J2GgBoyTf-g96SiYWXK8gt-eb3guB3uoGVrdqmnfDofgF"
    "sLjprfeh4hCUYOr7NdiAmopUbNUrXL-x2i3Mrfq0Ku5DdDHwN5LF6eyRN99mCYuG"
    "RhyuwdOwTXfjUBOKvuqZXhuj3-QQBSE-ztssJe0PXBV9BT3dREMashkIwNrpS69U"
    "u2MUsgK_JBrAxv7yAAhpzhMkaarpUdO70QT91fwI2EMPFXv7dYv30Z_PZTGI"
)

FIT_BADGE = {
    "High": ("verified", "High confidence", "#a8f2ce", "#002115"),
    "Medium": ("tune", "Medium confidence", "#d2e4ff", "#001c37"),
    "Low": ("help_outline", "Low confidence", "#ffdad6", "#93000a"),
}
FIT_HEAD_COLOR = {"High": "#003c29", "Medium": "#6c0029", "Low": "#ba1a1a"}

DECISION_BADGE = {
    "Ready to buy": ("check_circle", "Ready to buy", "#a8f2ce", "#002115"),
    "Worth waiting": ("hourglass_empty", "Worth waiting", "#e5e2e1", "#564145"),
    "Check one thing first": (
        "priority_high",
        "Check one thing first",
        "#d2e4ff",
        "#001c37",
    ),
    "Check fit first": ("priority_high", "Check fit first", "#d2e4ff", "#001c37"),
    "Compare first": ("compare_arrows", "Compare first", "#d2e4ff", "#001c37"),
    "Reconsider this save": (
        "inventory_2",
        "Reconsider this save",
        "#F8EAEA",
        "#934646",
    ),
    "Needs more information": (
        "help_center",
        "Needs more information",
        "#EEF0F3",
        "#596273",
    ),
}

DECISION_HEADLINES = {
    "Ready to buy": "Review once & complete",
    "Worth waiting": "Keep saved until occasion",
    "Check fit first": "Check fit before choosing",
    "Check one thing first": "Check one thing first",
    "Compare first": "Compare fabric & styling",
    "Reconsider this save": "Reconsider this save",
    "Needs more information": "Add the missing details",
}

DETAIL_FIT_BADGE = {
    "High": ("#EAF5EF", "#1F6B4F"),
    "Medium": ("#FFF4D6", "#946200"),
    "Low": ("#EEF0F3", "#596273"),
}
DETAIL_DECISION_BADGE = {
    "Ready to buy": ("#EAF5EF", "#1F6B4F"),
    "Worth waiting": ("#EEF0F3", "#596273"),
    "Check one thing first": ("#FFF4D6", "#946200"),
    "Check fit first": ("#FFF4D6", "#946200"),
    "Compare first": ("#EAF1F8", "#315C8C"),
    "Reconsider this save": ("#F8EAEA", "#934646"),
    "Needs more information": ("#EEF0F3", "#596273"),
}

ANALYSE_CATEGORIES = [
    "Men's Shirts",
    "Women's Ethnic Wear",
    "Jeans & Denim",
    "Dresses & Jumpsuits",
    "Footwear",
    "Outerwear & Jackets",
]
UNCERTAINTY_CHIPS = [
    "Fit or size",
    "Fabric or quality",
    "Reviews",
    "Styling",
    "Comparing alternatives",
    "Price or budget",
    "Nothing specific",
]

VIEWS = ("wishlist", "analyse", "detail", "live_result")

VERDICT_STYLES = {
    "Ready to buy": ("✅ Ready to buy", "#14532d", "#f0fdf4", "#86efac"),
    "Check fit first": ("⚠️ Check fit first", "#9a3412", "#fff7ed", "#fdba74"),
    "Check one thing first": (
        "⚠️ Check one thing first",
        "#9a3412",
        "#fff7ed",
        "#fdba74",
    ),
    "Compare first": ("🔍 Compare first", "#1e3a8a", "#eff6ff", "#93c5fd"),
    "Worth waiting": ("⏳ Worth waiting", "#92400e", "#fffbeb", "#fcd34d"),
    "Reconsider this save": (
        "🗂️ Reconsider this save",
        "#334155",
        "#f1f5f9",
        "#94a3b8",
    ),
    "Needs more information": (
        "ℹ️ Needs more information",
        "#334155",
        "#f8fafc",
        "#cbd5e1",
    ),
}

CHECK_QUESTION_KEYS = (
    "fit",
    "size",
    "sizing",
    "quality",
    "fabric",
    "authenticity",
    "authentic",
    "shrink",
    "waist",
    "chest",
    "runs small",
    "run small",
    "true to size",
)


# ---------------------------------------------------------------------------
# Data + secrets
# ---------------------------------------------------------------------------

def load_sample_wishlist() -> list[dict]:
    with SAMPLE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def get_groq_api_key() -> str | None:
    try:
        key = st.secrets["GROQ_API_KEY"]
    except Exception:
        return None
    if key is None:
        return None
    key = str(key).strip()
    return key or None


# ---------------------------------------------------------------------------
# Demo-mode rules (no API)
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def _keyword_hit(blob: str, key: str) -> bool:
    """True if key appears and is not clearly negated (e.g. 'didn't need to size up')."""
    idx = 0
    negations = ("didn't ", "did not ", "don't ", "do not ", "no need ")
    while True:
        i = blob.find(key, idx)
        if i < 0:
            return False
        prefix = blob[max(0, i - 28) : i]
        if any(n in prefix for n in negations):
            idx = i + len(key)
            continue
        return True


def _scan_reviews(snippets: list[str]) -> dict[str, bool]:
    blob = _norm(" ".join(snippets))
    return {
        "runs_small": any(_keyword_hit(blob, k) for k in RUN_SMALL_KEYS),
        "runs_large": any(_keyword_hit(blob, k) for k in RUN_LARGE_KEYS),
        "true_to_size": any(_keyword_hit(blob, k) for k in TRUE_SIZE_KEYS),
    }


def _nudge_size(size: str, delta: int) -> str:
    token = str(size).strip().upper()
    if token in LETTER_SIZES:
        idx = max(0, min(len(LETTER_SIZES) - 1, LETTER_SIZES.index(token) + delta))
        return LETTER_SIZES[idx]
    if token.isdigit():
        return str(max(24, int(token) + 2 * delta))
    return str(size)


def _usual_on_chart(usual_size: str, size_chart: dict) -> str:
    if usual_size in size_chart:
        return usual_size
    mapped = LETTER_TO_WAIST.get(usual_size)
    if mapped and mapped in size_chart:
        return mapped
    return usual_size


def _closest_chart_size(
    size_chart: dict,
    chest: float | None,
    waist: float | None,
) -> tuple[str | None, float | None, str | None]:
    """Return (size, abs_diff_inches, dim_used) or (None, None, None)."""
    best: tuple[str | None, float | None, str | None] = (None, None, None)
    for size, dims in size_chart.items():
        if not isinstance(dims, dict):
            continue
        candidates: list[tuple[str, float]] = []
        if chest is not None:
            for key in ("chest", "bust"):
                if key in dims:
                    candidates.append((key, abs(float(dims[key]) - chest)))
        if waist is not None and "waist" in dims:
            candidates.append(("waist", abs(float(dims["waist"]) - waist)))
        if not candidates:
            continue
        dim_used, diff = min(candidates, key=lambda x: x[1])
        if best[1] is None or diff < best[1]:
            best = (str(size), diff, dim_used)
    return best


def compute_fit(
    item: dict,
    usual_size: str,
    chest: float | None,
    waist: float | None,
) -> dict:
    size_chart = item.get("size_chart") or {}
    signals = _scan_reviews(item.get("review_snippets") or [])
    conflicting = (
        (signals["runs_small"] and signals["runs_large"])
        or (signals["runs_small"] and signals["true_to_size"])
        or (signals["runs_large"] and signals["true_to_size"])
    )

    base = _usual_on_chart(usual_size, size_chart)
    match_size, match_diff, match_dim = _closest_chart_size(size_chart, chest, waist)

    recommended = match_size or base
    if signals["runs_small"] and not conflicting:
        recommended = _nudge_size(recommended, 1)
    elif signals["runs_large"] and not conflicting:
        recommended = _nudge_size(recommended, -1)

    measurement_agrees = (
        match_size is not None
        and match_diff is not None
        and match_diff <= 1.0
    )
    has_clear_review = (
        (signals["true_to_size"] or signals["runs_small"] or signals["runs_large"])
        and not conflicting
    )

    if conflicting:
        confidence = "Low"
        reason = (
            f"Reviews disagree on sizing, so stay near {base} until you can try it "
            "or check a store."
        )
    elif measurement_agrees and has_clear_review:
        confidence = "High"
        if signals["runs_small"]:
            reason = (
                f"Your {match_dim} is closest to {match_size} on the chart, and "
                f"reviews say it runs small — {recommended} is the safer pick."
            )
        elif signals["runs_large"]:
            reason = (
                f"Your {match_dim} is closest to {match_size} on the chart, and "
                f"reviews say it runs large — {recommended} should sit better."
            )
        else:
            reason = (
                f"Your {match_dim} matches {match_size} on the size chart and "
                "reviewers call it true to size."
            )
    elif has_clear_review:
        confidence = "Medium"
        if signals["runs_small"]:
            reason = (
                f"Reviews say this runs small, so size up from {base} to "
                f"{recommended}. Add a measurement for a tighter read."
            )
        elif signals["runs_large"]:
            reason = (
                f"Reviews say this runs large, so size down from {base} to "
                f"{recommended}. A measurement would raise confidence."
            )
        else:
            reason = (
                f"Reviewers say true to size, so {recommended} (your usual) is "
                "the starting point — measurements would confirm it."
            )
    elif measurement_agrees:
        confidence = "Medium"
        reason = (
            f"Size chart puts you nearest {match_size} on {match_dim}, but "
            "reviews don't give a clear run-small / true-to-size signal."
        )
    else:
        confidence = "Low"
        reason = (
            f"Not enough to go on — using your usual {usual_size} as "
            f"{recommended}. Add measurements or more fit reviews."
        )

    return {
        "fit_recommendation": recommended,
        "fit_confidence": confidence,
        "fit_reason": reason,
    }


def _is_comparing(item: dict) -> bool:
    status = _norm(str(item.get("comparison_status") or ""))
    if not status or status in ("not_comparing", "none", "no"):
        return False
    return status.startswith("compar")


def _parse_occasion(item: dict) -> int | None:
    raw = item.get("occasion_days_remaining")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _unresolved_questions(item: dict) -> list[str]:
    raw = item.get("unresolved_questions") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(q).strip() for q in raw if str(q).strip()]


def _is_check_topic(question: str) -> bool:
    blob = _norm(question)
    return any(k in blob for k in CHECK_QUESTION_KEYS)


def _blocking_check_questions(item: dict) -> list[str]:
    return [q for q in _unresolved_questions(item) if _is_check_topic(q)]


def _likes_item(item: dict) -> bool:
    save = str(item.get("save_reason") or "").strip()
    use = str(item.get("intended_use") or "").strip()
    return bool(save or use)


def _decision(
    status: str,
    reason: str,
    next_step: str,
    evidence: list[str],
    item: dict,
) -> dict:
    """Simulated low stock is supporting context only — never the recommendation."""
    supporting: list[str] = []
    if item.get("stock_status") == "low_stock":
        tag = "simulated" if item.get("stock_is_simulated", True) else "reported"
        supporting.append(
            f"Simulated sample stock: limited sizes ({tag}) — not live inventory "
            "and not a verified fact. Supporting context only; never the reason to buy."
        )
    return {
        "decision_status": status,
        "decision_reason": reason,
        "next_step": next_step,
        "evidence_used": list(evidence),
        "supporting_context": supporting,
    }


def _important_info_missing(item: dict) -> list[str]:
    """Product facts still open — not 'no occasion yet' (that is Worth waiting)."""
    missing: list[str] = []
    chart = item.get("size_chart") or {}
    if not chart:
        missing.append("size_chart is missing")
    if _is_comparing(item):
        return missing
    missing.extend(_blocking_check_questions(item))
    return missing


def compute_next_action(item: dict, fit: dict) -> dict:
    """Situation → next action. Reasons cite only sample or user-supplied fields."""
    conf = fit["fit_confidence"]
    intent = _norm(str(item.get("intent_state") or ""))
    occasion = _parse_occasion(item)
    comparing = _is_comparing(item)
    days = item.get("saved_days_ago")
    try:
        days_n = int(days) if days is not None and days != "" else None
    except (TypeError, ValueError):
        days_n = None
    strong_fit = conf in ("High", "Medium")
    missing = _important_info_missing(item)

    # Low fit confidence → Check fit first
    if conf == "Low":
        evidence = [
            "fit_confidence: Low",
            f"fit_reason: {fit.get('fit_reason')}",
        ]
        if item.get("intent_state"):
            evidence.append(f"intent_state: {item.get('intent_state')}")
        return _decision(
            "Check fit first",
            "Fit confidence is Low on the size chart and reviews available for this item.",
            "Check fit (chart, suggested size based on available information, and any open size question) before buying.",
            evidence,
            item,
        )

    # Still comparing an alternative → Compare first
    # (before "missing info", so an active comparison is the action)
    if comparing:
        evidence = [
            f"comparison_status: {item.get('comparison_status')}",
            f"intent_state: {item.get('intent_state')}",
        ]
        if item.get("save_reason"):
            evidence.append(f"save_reason: {item.get('save_reason')}")
        return _decision(
            "Compare first",
            "This save is still being compared with another option, so buying this item now would skip that comparison.",
            "Compare the alternative named in the save context, then return to this item.",
            evidence,
            item,
        )

    # Important information missing → Check one thing first
    if missing:
        gap = missing[0]
        return _decision(
            "Check one thing first",
            f"Important information is still missing or open on this save: {gap}",
            "Resolve that one gap before buying.",
            [f"missing_or_open: {gap}", f"fit_confidence: {conf}"],
            item,
        )

    # Active intent + upcoming need + strong fit → Ready to buy
    # (never from stock or saved_days_ago alone)
    if (
        intent == "active"
        and occasion is not None
        and 0 <= occasion <= 30
        and strong_fit
        and not missing
        and not comparing
    ):
        evidence = [
            f"intent_state: {item.get('intent_state')}",
            f"occasion_days_remaining: {occasion}",
            f"fit_confidence: {conf}",
            f"fit_recommendation: {fit.get('fit_recommendation')}",
        ]
        if item.get("intended_use"):
            evidence.append(f"intended_use: {item.get('intended_use')}")
        if item.get("save_reason"):
            evidence.append(f"save_reason: {item.get('save_reason')}")
        return _decision(
            "Ready to buy",
            f"Intent is active, there is an upcoming need in {occasion} day{'s' if occasion != 1 else ''}, "
            f"and fit confidence is {conf}.",
            f"Buy in suggested size {fit.get('fit_recommendation')} (based on available information) if this is still the outfit for that occasion.",
            evidence,
            item,
        )

    # Stale save + weakened intent → Reconsider this save
    if intent == "stale" or (intent == "uncertain" and not _likes_item(item)):
        evidence = [f"intent_state: {item.get('intent_state')}"]
        if days_n is not None:
            evidence.append(
                f"saved_days_ago: {days_n} (age of the save; not a buy trigger)"
            )
        if item.get("save_reason"):
            evidence.append(f"save_reason: {item.get('save_reason')}")
        return _decision(
            "Reconsider this save",
            "This save is marked stale or the intent looks weakened, so it may no longer be a real purchase.",
            "Reconsider whether to keep it on the list, or drop it if the need has passed.",
            evidence,
            item,
        )

    # No immediate need → Worth waiting
    evidence = [
        f"intent_state: {item.get('intent_state') or '(none)'}",
        f"occasion_days_remaining: {occasion}",
    ]
    if item.get("save_reason"):
        evidence.append(f"save_reason: {item.get('save_reason')}")
    if days_n is not None:
        evidence.append(
            f"saved_days_ago: {days_n} (how long this sample has sat; not a buy trigger)"
        )
    return _decision(
        "Worth waiting",
        "There is no immediate need (no dated occasion in the next 30 days) and the item can stay saved.",
        "Keep the save. Revisit when you have a use date; do not wait for a sale or coupon.",
        evidence,
        item,
    )


def _safe_str(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        parts = [_safe_str(v) for v in value]
        return "; ".join(p for p in parts if p) or default
    if isinstance(value, dict):
        return default
    text = str(value).strip()
    return text or default


def _safe_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            text = _safe_str(item)
            if text:
                out.append(text)
        return out
    text = _safe_str(value)
    return [text] if text else []


def _map_decision_status(raw: str, fit_confidence: str = "") -> str:
    token = _norm(raw)
    aliases = {
        "ready to buy": "Ready to buy",
        "buy now": "Ready to buy",
        "check one thing first": "Check one thing first",
        "check fit first": "Check fit first",
        "compare first": "Compare first",
        "worth waiting": "Worth waiting",
        "wait": "Worth waiting",
        "reconsider this save": "Reconsider this save",
        "reconsider": "Reconsider this save",
        "needs more information": "Needs more information",
        "needs more info": "Needs more information",
    }
    mapped = aliases.get(token, "")
    if mapped:
        return mapped
    return "Needs more information"


def verdict_kind(result: dict) -> str:
    status = result.get("decision_status") or ""
    if status in VERDICT_STYLES:
        return status
    action = str(result.get("buy_or_wait") or "")
    conf = result.get("fit_confidence") or "Low"
    mapped = _map_decision_status(action, conf)
    return mapped if mapped in VERDICT_STYLES else "Needs more information"


def compose_why_line(result: dict) -> str:
    """Visible why line: engine reason, else a short grounded fallback."""
    reason = (result.get("decision_reason") or "").strip()
    if reason:
        return reason
    return (
        (result.get("buy_wait_reason") or "").strip()
        or (result.get("fit_reason") or "").strip()
        or "Not enough detail yet to explain this call."
    )


def wishlist_health_line(rows: list[dict]) -> str:
    n = len(rows)
    stale = sum(1 for x in rows if _norm(str(x.get("intent_state") or "")) == "stale")
    stale += sum(
        1
        for x in rows
        if _norm(str(x.get("intent_state") or "")) != "stale"
        and int(x.get("saved_days_ago") or 0) >= 60
    )
    comparing = sum(1 for x in rows if _is_comparing(x))
    uncertain = sum(1 for x in rows if x.get("fit_confidence") in ("Low", "Medium"))
    return (
        f"Fictional sample · {n} item{'s' if n != 1 else ''} saved · "
        f"{stale} sitting 60+ days or stale · "
        f"{comparing} still comparing · "
        f"{uncertain} with fit uncertainty"
    )


# ---------------------------------------------------------------------------
# Live mode (one Groq call)
# ---------------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _parse_model_json(raw: str) -> dict:
    """Best-effort JSON object parse. Never raises."""
    cleaned = _strip_code_fences(raw)
    if not cleaned:
        return {}
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _build_live_user_prompt(payload: dict) -> str:
    def field(label: str, key: str) -> str:
        val = str(payload.get(key) or "").strip()
        return f"{label}: {val if val else '(not provided)'}"

    return (
        "Advise on this wishlisted fashion item using only the fields below. "
        "If a field is (not provided), do not invent it. "
        "If evidence is insufficient, use decision_status \"Needs more information\". "
        "Return ONLY the JSON object.\n\n"
        f"{field('Product name / brand', 'product')}\n"
        f"{field('Category', 'category')}\n"
        f"{field('Price', 'price')}\n"
        f"{field('Why they saved it', 'why_saved')}\n"
        f"{field('Is it for a particular occasion?', 'occasion_for')}\n"
        f"{field('When they need it', 'occasion_timing')}\n"
        f"{field('What they are still unsure about', 'unresolved_questions')}\n"
        f"{field('Are they comparing another item?', 'comparison_status')}\n"
        f"{field('Size and optional measurements', 'size_info')}\n"
        f"{field('Size chart', 'size_chart')}\n"
        f"{field('Availability notes (user-reported, not live inventory)', 'availability')}\n"
        f"{field('Additional context', 'extra_context')}\n"
        f"Review snippets:\n{payload.get('reviews') or '(not provided)'}\n"
    )


def _live_payload_too_thin(payload: dict) -> bool:
    """True when there is not enough user-supplied evidence to ground an answer.

    Category, usual size, default 'not comparing', and default 'no occasion'
    are always present after form validation — they do not count as evidence.
    Availability notes are not live inventory and are not enough on their own.
    """
    size_info = _norm(str(payload.get("size_info") or ""))
    has_measurement = "chest" in size_info or "waist" in size_info
    questions = _norm(str(payload.get("unresolved_questions") or ""))
    has_questions = bool(questions) and questions not in (
        "nothing specific",
        "(not provided)",
    )
    comparing = _norm(str(payload.get("comparison_status") or ""))
    has_compare = bool(comparing) and comparing not in (
        "not_comparing",
        "not comparing",
        "none",
        "no",
        "(not provided)",
    )
    occasion_for = _norm(str(payload.get("occasion_for") or ""))
    has_occasion = bool(occasion_for) and occasion_for not in (
        "no specific occasion",
        "no",
        "(not provided)",
    )
    optional = (
        str(payload.get("size_chart") or "").strip(),
        str(payload.get("reviews") or "").strip(),
        str(payload.get("why_saved") or "").strip(),
        str(payload.get("occasion_timing") or "").strip(),
        str(payload.get("extra_context") or "").strip(),
    )
    return not (
        any(optional)
        or has_measurement
        or has_questions
        or has_compare
        or has_occasion
    )


def call_groq(payload: dict, api_key: str) -> dict:
    from groq import Groq

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_live_user_prompt(payload)},
        ],
        temperature=0.3,
        max_tokens=700,
    )
    try:
        raw = (response.choices[0].message.content or "").strip()
    except (AttributeError, IndexError, TypeError):
        return {}
    return _parse_model_json(raw)


def _live_fallback_result(message: str = "") -> dict:
    reason = (
        message
        or "Not enough supplied evidence to recommend a size or a next action."
    )
    return {
        "fit_recommendation": "—",
        "fit_confidence": "Low",
        "fit_reason": reason,
        "fit_evidence_used": ["Insufficient supplied evidence"],
        "decision_status": "Needs more information",
        "decision_reason": reason,
        "next_step": (
            "Add a size chart, measurements, reviews, save reason, or what is "
            "blocking you, then try again."
        ),
        "decision_evidence_used": ["Insufficient supplied evidence"],
        "evidence_used": ["Insufficient supplied evidence"],
        "name": "Your item",
        "brand": "",
        "category": "Custom paste",
        "price": None,
        "saved_days_ago": None,
        "stock_status": None,
        "review_snippets": [],
        "is_live": True,
    }


def normalize_live_result(parsed: dict) -> dict:
    """Coerce model JSON into the live schema. Never raises."""
    try:
        if not isinstance(parsed, dict) or not parsed:
            return _live_fallback_result()

        conf = _safe_str(parsed.get("fit_confidence"), "Low").title()
        if conf not in ("High", "Medium", "Low"):
            conf = "Low"

        status = _map_decision_status(
            _safe_str(parsed.get("decision_status")),
            conf,
        )
        if status not in VERDICT_STYLES:
            status = "Needs more information"

        fit_ev = _safe_str_list(parsed.get("fit_evidence_used"))
        dec_ev = _safe_str_list(
            parsed.get("decision_evidence_used") or parsed.get("evidence_used")
        )
        if not fit_ev:
            fit_ev = ["No fit evidence listed by the model"]
        if not dec_ev:
            dec_ev = ["No decision evidence listed by the model"]

        return {
            "fit_recommendation": _safe_str(parsed.get("fit_recommendation"), "—") or "—",
            "fit_confidence": conf,
            "fit_reason": _safe_str(
                parsed.get("fit_reason"),
                "No fit reason returned from the supplied fields.",
            ),
            "fit_evidence_used": fit_ev,
            "decision_status": status,
            "decision_reason": _safe_str(
                parsed.get("decision_reason"),
                "No decision reason returned from the supplied fields.",
            ),
            "next_step": _safe_str(
                parsed.get("next_step"),
                "Add more of the supplied fields and try again.",
            ),
            "decision_evidence_used": dec_ev,
            "evidence_used": dec_ev,
            "name": "Your item",
            "brand": "",
            "category": "Custom paste",
            "price": None,
            "saved_days_ago": None,
            "stock_status": None,
            "review_snippets": [],
            "is_live": True,
        }
    except Exception:
        return _live_fallback_result(
            "The live response could not be read. No blocker was assumed."
        )


# ---------------------------------------------------------------------------
# UI helpers — Stitch "Mindful Curation" screens
# ---------------------------------------------------------------------------

def md(fragment: str) -> None:
    st.markdown(fragment, unsafe_allow_html=True)


def icon(name: str, size: int = 16) -> str:
    return (
        f'<span class="material-symbols-outlined" '
        f'style="font-size:{size}px;line-height:1;vertical-align:middle">'
        f"{html.escape(name)}</span>"
    )


def visual_for(item: dict) -> dict:
    return ITEM_VISUALS.get(str(item.get("id") or ""), {})


def display_name(item: dict) -> str:
    return visual_for(item).get("short_name") or item.get("name") or "Item"


def item_image(item: dict, *, detail: bool = False) -> str:
    vis = visual_for(item)
    if detail:
        return vis.get("detail_image") or vis.get("image") or LIVE_PLACEHOLDER_IMAGE
    return vis.get("image") or item.get("image_url") or LIVE_PLACEHOLDER_IMAGE


def reason_icon_name(item: dict) -> str:
    vis = visual_for(item)
    if vis.get("reason_icon"):
        return vis["reason_icon"]
    if item.get("occasion_days_remaining") is not None:
        return "event_note"
    if _is_comparing(item):
        return "compare_arrows"
    if _norm(str(item.get("intent_state") or "")) == "stale":
        return "tune"
    return "favorite_border"


def stock_chip(item: dict) -> str:
    status = item.get("stock_status")
    if not status:
        return ""
    if status == "low_stock":
        return "Simulated stock: Limited sizes (not live)"
    return "Simulated stock: In stock (not live)"


def current_view() -> str:
    raw = st.query_params.get("view", "wishlist")
    if isinstance(raw, list):
        raw = raw[0] if raw else "wishlist"
    view = str(raw or "wishlist")
    return view if view in VIEWS else "wishlist"


def go(view: str, **extra) -> None:
    payload = {"view": view}
    for key, val in extra.items():
        if val is not None and val != "":
            payload[key] = str(val)
    st.query_params.from_dict(payload)


def inject_css() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Manrope:wght@400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap');

html, body, .stApp, [data-testid="stAppViewContainer"] {
  background: #fcf9f8 !important;
  color: #1c1b1b;
  font-family: Manrope, sans-serif;
}
.material-symbols-outlined {
  font-family: 'Material Symbols Outlined' !important;
  font-weight: 400;
  font-style: normal;
  display: inline-block;
  line-height: 1;
  text-transform: none;
  letter-spacing: normal;
  white-space: nowrap;
  word-wrap: normal;
  direction: ltr;
  -webkit-font-smoothing: antialiased;
  font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 20;
}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
header[data-testid="stHeader"], .stDeployButton { display: none !important; }
[data-testid="stAppViewContainer"] > .main { background: #fcf9f8 !important; }
.block-container {
  max-width: 44rem !important;
  padding: 0 1.25rem 3.5rem !important;
  font-size: 15px;
}
p, li, label, .stMarkdown, .stCaption, .stText, div[data-testid="stWidgetLabel"] p {
  font-size: 15px !important;
  font-family: Manrope, sans-serif !important;
  line-height: 24px !important;
}
h1, h2, h3 { font-family: Manrope, sans-serif !important; }

.wd-top {
  background: rgba(252,249,248,0.94);
  backdrop-filter: blur(16px);
  padding: 0.35rem 0 0.65rem 0;
  margin: 0 -0.15rem 0.75rem -0.15rem;
}
.wd-brand {
  display: flex; align-items: center; justify-content: space-between;
  min-height: 44px; gap: 0.75rem;
}
.wd-brand-left { display: flex; align-items: center; gap: 0.75rem; min-width: 0; }
.wd-logo { font-size: 18px; font-weight: 700; letter-spacing: -0.02em; color: #1c1b1b; }
.wd-vbar { width: 1px; height: 20px; background: rgba(221,191,195,0.6); flex-shrink: 0; }
.wd-title { font-size: 18px; font-weight: 600; line-height: 1.2; color: #1c1b1b; }
.wd-sub { font-family: Inter, sans-serif; font-size: 11px; font-weight: 400;
  letter-spacing: 0.06em; color: #564145; }
.wd-brand-right { display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0; }
.wd-ai {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px; border-radius: 999px; background: #f6f3f2;
  font-family: Inter, sans-serif; font-size: 11px; color: #564145;
}
.wd-avatar {
  width: 32px; height: 32px; border-radius: 999px; background: #6c0029;
  display: flex; align-items: center; justify-content: center; color: #fff;
}
.wd-nav {
  display: flex; gap: 4px; padding: 4px; background: #f0eded;
  border-radius: 8px; margin-top: 0.55rem;
}
.wd-nav a {
  flex: 1; min-height: 44px; display: flex; align-items: center; justify-content: center;
  border-radius: 6px; text-decoration: none !important;
  font-family: Inter, sans-serif; font-size: 12px; letter-spacing: 0.04em;
  color: #564145; font-weight: 500;
}
.wd-nav a.is-active {
  background: #fff; color: #6c0029; font-family: Manrope, sans-serif;
  font-size: 18px; font-weight: 600; letter-spacing: -0.005em;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.wd-proto {
  display: flex; align-items: flex-start; gap: 6px;
  margin-top: 0.5rem; padding: 6px 8px; border-radius: 6px;
  background: #f6f3f2; color: #564145;
  font-family: Inter, sans-serif; font-size: 11px; line-height: 1.35;
}
.wd-compact {
  display: flex; align-items: center; justify-content: space-between;
  min-height: 56px; gap: 0.5rem;
}
.wd-back {
  display: inline-flex; align-items: center; gap: 6px;
  color: #564145; text-decoration: none !important;
  font-size: 13px;
}
.wd-back:hover { color: #6c0029; }

.wd-kicker {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 999px; background: #eae7e7;
  color: #6c0029; font-family: Inter, sans-serif; font-size: 11px;
}
.wd-h1 {
  font-size: 22px; font-weight: 600; line-height: 30px;
  letter-spacing: -0.01em; color: #1c1b1b; margin: 0.15rem 0 0.35rem 0;
}
.wd-h1.lg { font-size: 28px; line-height: 36px; letter-spacing: -0.015em; }
.wd-lead { color: #564145; font-size: 15px; line-height: 24px; margin: 0 0 1rem 0; }

.wd-insight {
  background: #f6f3f2; border-radius: 8px; padding: 1rem;
  box-shadow: 0 1px 4px rgba(0,0,0,0.02); margin: 0.5rem 0 1.5rem 0;
}
.wd-insight-kicker {
  display: flex; align-items: center; gap: 6px; color: #6c0029;
  font-family: Inter, sans-serif; font-size: 11px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
}
.wd-card {
  background: #fff; border-radius: 8px; padding: 1rem;
  box-shadow: 0 1px 6px rgba(0,0,0,0.03); margin-bottom: 1.5rem;
}
.wd-card.xl { border-radius: 12px; padding: 1.25rem; }
.wd-section-head { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 0.35rem; }
.wd-num {
  width: 28px; height: 28px; border-radius: 999px; background: #f0eded;
  color: #6c0029; display: flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 600; flex-shrink: 0;
}
.wd-lock {
  display: inline-flex; align-items: center; gap: 4px;
  background: rgba(168,242,206,0.3); color: #003c29;
  font-family: Inter, sans-serif; font-size: 11px;
  padding: 2px 8px; border-radius: 999px;
}
.wd-health {
  background: #f0eded; border-radius: 8px; padding: 0.75rem;
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 8px; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.02);
}
.wd-health-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 18px; font-weight: 600;
}
.wd-dots { display: flex; flex-wrap: wrap; gap: 4px 12px;
  font-family: Inter, sans-serif; font-size: 12px; color: #564145; }
.wd-dot { display: inline-flex; align-items: center; gap: 6px; }
.wd-dot i { width: 8px; height: 8px; border-radius: 999px; display: inline-block; }

.wd-item { background: #fff; border-radius: 8px; padding: 1rem;
  box-shadow: 0 1px 6px rgba(0,0,0,0.03); margin-bottom: 0.35rem; }
.wd-item-top { display: flex; gap: 0.75rem; align-items: flex-start; }
.wd-thumb {
  width: 96px; height: 128px; border-radius: 8px; overflow: hidden;
  background: #f6f3f2; flex-shrink: 0; position: relative;
}
.wd-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.wd-size-tag {
  position: absolute; left: 4px; bottom: 4px;
  background: rgba(252,249,248,0.9); color: #1c1b1b;
  font-family: Inter, sans-serif; font-size: 11px; padding: 1px 4px; border-radius: 4px;
}
.wd-meta { flex: 1; min-width: 0; }
.wd-meta-row { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.wd-eyebrow {
  font-family: Inter, sans-serif; font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase; color: #564145;
}
.wd-muted { font-family: Inter, sans-serif; font-size: 11px; color: #564145; }
.wd-name { font-size: 18px; font-weight: 600; margin: 2px 0 4px; color: #1c1b1b; }
.wd-price-row { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
.wd-price { font-family: Inter, sans-serif; font-size: 14px; font-weight: 600;
  font-variant-numeric: tabular-nums; }
.wd-chip {
  font-family: Inter, sans-serif; font-size: 11px; padding: 2px 8px;
  border-radius: 999px; background: #f6f3f2; color: #564145;
}
.wd-reason {
  margin-top: 6px; display: flex; align-items: center; gap: 6px;
  background: #f6f3f2; border-radius: 6px; padding: 4px 10px;
  font-family: Inter, sans-serif; font-size: 11px; color: #1c1b1b;
}
.wd-matrix { display: grid; grid-template-columns: 1fr; gap: 0.75rem; margin-top: 0.85rem; }
@media (min-width: 720px) { .wd-matrix { grid-template-columns: 1fr 1fr; } }
.wd-panel { background: #f6f3f2; border-radius: 8px; padding: 0.75rem; display: flex;
  flex-direction: column; justify-content: space-between; gap: 8px; }
.wd-panel-top { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
.wd-panel-label {
  font-family: Inter, sans-serif; font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase; color: #564145;
}
.wd-badge {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 999px;
  font-family: Inter, sans-serif; font-size: 11px; font-weight: 600; white-space: nowrap;
}
.wd-head { font-size: 18px; font-weight: 600; line-height: 26px; margin: 6px 0; }
.wd-body { font-size: 13px; line-height: 20px; color: #1c1b1b; }
.wd-based { margin-top: 8px; padding-top: 8px;
  font-family: Inter, sans-serif; font-size: 11px; color: #564145;
  border-top: 1px solid rgba(221,191,195,0.3); }
.wd-size-cap {
  font-family: Inter, sans-serif; font-size: 11px; color: #564145;
  display: block; margin-top: 4px;
}
.wd-next { font-size: 13px; line-height: 20px; color: #1c1b1b; }
.wd-next strong { color: #6c0029; }
.wd-fit-note {
  margin-top: 0.65rem; padding: 4px 8px; border-radius: 4px;
  background: rgba(246,243,242,0.7);
  font-family: Inter, sans-serif; font-size: 11px; color: #564145;
}
.wd-footer {
  display: flex; justify-content: flex-end; gap: 1rem; padding: 0.65rem 0.15rem 1.35rem;
}
.wd-footer a {
  display: inline-flex; align-items: center; gap: 4px;
  text-decoration: none !important; font-family: Inter, sans-serif; font-size: 12px;
  color: #1c1b1b;
}
.wd-footer a.strong { color: #6c0029; font-weight: 600; }
.wd-footer a.strong:hover { text-decoration: underline !important; }

.wd-callout { background: #f6f3f2; border-radius: 8px; padding: 1rem; display: flex;
  gap: 0.75rem; align-items: flex-start; margin: 0.5rem 0 1rem; }
.wd-policy-kicker {
  font-family: Inter, sans-serif; font-size: 11px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase; color: #6c0029;
}
.wd-grid3 { display: grid; grid-template-columns: 1fr; gap: 10px; }
@media (min-width: 640px) { .wd-grid3 { grid-template-columns: 1fr 1fr; } }
.wd-tile { background: #fff; border-radius: 8px; padding: 12px; }
.wd-tile .k {
  font-family: Inter, sans-serif; font-size: 11px; letter-spacing: 0.06em;
  text-transform: uppercase; color: #564145;
}
.wd-quote {
  display: flex; gap: 8px; background: rgba(246,243,242,0.7);
  border-radius: 8px; padding: 10px; margin-top: 6px;
  font-size: 13px; font-style: italic; color: #564145;
}
.wd-measure {
  display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px;
  background: rgba(246,243,242,0.7); border-radius: 8px; padding: 12px; text-align: center;
}
.wd-measure .hi { background: rgba(229,226,225,0.6); border-radius: 6px; padding: 4px 0; }
.wd-check { display: flex; gap: 8px; align-items: flex-start; font-size: 13px; margin: 6px 0; }
.wd-add { display: flex; align-items: center; gap: 10px; font-size: 13px; margin: 8px 0; }
.wd-add .plus {
  width: 20px; height: 20px; border-radius: 999px; background: #f0eded;
  display: flex; align-items: center; justify-content: center; color: #6c0029;
}

div[data-testid="stSelectbox"] > div, div[data-testid="stNumberInput"] > div,
div[data-testid="stTextInput"] > div, div[data-testid="stTextArea"] textarea,
div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
  background: #f6f3f2 !important;
  border: 0 !important;
  border-radius: 8px !important;
  box-shadow: none !important;
}
div[data-testid="stTextArea"] textarea, div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input {
  background: #f6f3f2 !important;
  font-family: Manrope, sans-serif !important;
  color: #1c1b1b !important;
}
div[data-testid="stWidgetLabel"] p {
  font-family: Inter, sans-serif !important;
  font-size: 12px !important;
  letter-spacing: 0.04em !important;
  color: #564145 !important;
}
div.stButton > button[kind="primary"],
div.stButton > button[data-testid="stBaseButton-primary"] {
  background: #6c0029 !important; color: #fff !important;
  border: 0 !important; border-radius: 8px !important;
  font-family: Manrope, sans-serif !important; font-weight: 600 !important;
  min-height: 44px !important; box-shadow: 0 1px 4px rgba(108,0,41,0.2) !important;
}
div.stButton > button[kind="secondary"],
div.stButton > button[data-testid="stBaseButton-secondary"] {
  background: #fff !important; color: #1c1b1b !important;
  border: 0 !important; border-radius: 8px !important;
  min-height: 44px !important; box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;
}
div[data-testid="stRadio"] label { font-family: Manrope, sans-serif !important; }
.stAlert { border-radius: 8px !important; }
div[data-testid="stMarkdown"] { margin-bottom: 0 !important; }
div[data-testid="stVerticalBlock"] { gap: 0.45rem !important; }
div[data-testid="stElementContainer"]:has(.wd-footer) { margin-bottom: 0.15rem !important; }
div[data-testid="stCaption"] { color: #564145 !important; font-family: Inter, sans-serif !important; font-size: 11px !important; }
</style>
        """,
        unsafe_allow_html=True,
    )


def fit_badge(conf: str) -> str:
    conf = conf if conf in FIT_BADGE else "Low"
    icon_name, label, bg, fg = FIT_BADGE[conf]
    return (
        f'<span class="wd-badge" style="background:{bg};color:{fg}">'
        f"{icon(icon_name, 12)} {html.escape(label)}</span>"
    )


def decision_badge(status: str) -> str:
    status = status if status in DECISION_BADGE else "Needs more information"
    icon_name, label, bg, fg = DECISION_BADGE[status]
    return (
        f'<span class="wd-badge" style="background:{bg};color:{fg}">'
        f"{icon(icon_name, 12)} {html.escape(label)}</span>"
    )


def detail_badge(label: str, bg: str, fg: str) -> str:
    return (
        f'<span class="wd-badge" style="background:{bg};color:{fg};'
        f'text-transform:uppercase;letter-spacing:0.06em">'
        f"{html.escape(label)}</span>"
    )


def fit_headline(result: dict) -> str:
    if result.get("is_live") and verdict_kind(result) == "Needs more information":
        return "Insufficient information to suggest size"
    if (result.get("fit_confidence") or "") == "Low":
        return "Check fit before choosing"
    size = result.get("fit_recommendation") or "—"
    return f"Suggested size: {size}"


def decision_headline(result: dict) -> str:
    status = verdict_kind(result)
    return DECISION_HEADLINES.get(status, status)


def compose_fit_based_on(
    item: dict,
    usual: str,
    chest: float | None,
    waist: float | None,
) -> str:
    bits = ["Brand size chart"]
    if chest:
        bits.append(f"{chest:g}-inch chest measurement")
    if waist:
        bits.append(f"{waist:g}-inch waist measurement")
    bits.append(f"Usual size {usual}")
    signals = _scan_reviews(item.get("review_snippets") or [])
    if (signals["runs_small"] and signals["true_to_size"]) or (
        signals["runs_small"] and signals["runs_large"]
    ):
        bits.append("Conflicting simulated review snippets")
    elif signals["runs_small"]:
        bits.append("Simulated review snippets reporting smaller fit")
    elif signals["true_to_size"]:
        bits.append("Simulated review snippets indicating true-to-size")
    elif signals["runs_large"]:
        bits.append("Simulated review snippets reporting a larger fit")
    elif item.get("review_snippets"):
        bits.append("Simulated review snippets")
    return " • ".join(bits)


def compose_decision_based_on(result: dict) -> str:
    ev = result.get("decision_evidence_used") or result.get("evidence_used") or []
    if ev:
        pretty = []
        for row in ev[:4]:
            text = str(row)
            pretty.append(text.split(": ", 1)[-1] if ": " in text else text)
        return " • ".join(pretty)
    return compose_why_line(result)


def render_chrome(active: str) -> None:
    if active == "detail":
        md(
            f"""
<div class="wd-top">
  <div class="wd-compact">
    <div style="display:flex;align-items:center;gap:8px;min-width:0">
      <a class="wd-back" href="?view=wishlist">{icon("arrow_back", 22)}</a>
      <span class="wd-title" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
        Item Assessment Detail
      </span>
    </div>
    <div class="wd-brand-right">
      <span class="wd-ai">{icon("auto_awesome", 13)} AI-assisted</span>
      <div class="wd-avatar">{icon("person", 18)}</div>
    </div>
  </div>
</div>
            """
        )
        return

    wish_cls = "is-active" if active in ("wishlist",) else ""
    analyse_cls = "is-active" if active in ("analyse", "live_result") else ""
    md(
        f"""
<div class="wd-top">
  <div class="wd-brand">
    <div class="wd-brand-left">
      <span class="wd-logo">AJIO</span>
      <div class="wd-vbar"></div>
      <div>
        <div class="wd-title">Wishlist Decision Assistant</div>
        <div class="wd-sub">Decide what fits. Know what to do next. No coupons.</div>
      </div>
    </div>
    <div class="wd-brand-right">
      <span class="wd-ai">{icon("auto_awesome", 13)} AI-assisted</span>
      <div class="wd-avatar">{icon("person", 18)}</div>
    </div>
  </div>
  <nav class="wd-nav">
    <a class="{wish_cls}" href="?view=wishlist">Sample Wishlist</a>
    <a class="{analyse_cls}" href="?view=analyse">Analyse an Item</a>
  </nav>
  <div class="wd-proto">
    {icon("info", 15)}
    <span>{html.escape(PROTO_BANNER)}</span>
  </div>
</div>
        """
    )


def wishlist_health_counts(rows: list[dict]) -> tuple[int, int, int, int]:
    n = len(rows)
    ready = sum(1 for r in rows if verdict_kind(r) == "Ready to buy")
    wait = sum(
        1
        for r in rows
        if verdict_kind(r) in ("Worth waiting", "Reconsider this save")
    )
    check = n - ready - wait
    return n, ready, check, wait


def _chart_dim(size_chart: dict, size: str) -> tuple[str | None, float | None]:
    row = size_chart.get(str(size)) or {}
    if not isinstance(row, dict):
        return None, None
    for key in ("chest", "bust", "waist"):
        if key in row:
            try:
                return key, float(row[key])
            except (TypeError, ValueError):
                continue
    return None, None


def render_item_card(
    row: dict, usual: str, chest: float | None, waist: float | None
) -> None:
    item_id = html.escape(str(row.get("id") or "item"))
    conf = row.get("fit_confidence") or "Low"
    status = verdict_kind(row)
    img = item_image(row)
    size = html.escape(str(row.get("fit_recommendation") or ""))
    brand = html.escape(str(row.get("brand") or ""))
    cat = html.escape(str(row.get("category") or ""))
    days = row.get("saved_days_ago")
    days_l = f"Saved {days} day{'s' if days != 1 else ''} ago" if days is not None else ""
    price = row.get("price")
    price_l = f"₹{int(price):,}" if price is not None else ""
    stock = html.escape(stock_chip(row))
    reason = html.escape(str(row.get("save_reason") or "Saved for later"))
    fit_color = FIT_HEAD_COLOR.get(conf, "#1c1b1b")
    md(
        f"""
<article class="wd-item">
  <div class="wd-item-top">
    <div class="wd-thumb">
      <img src="{html.escape(img)}" alt=""/>
      <span class="wd-size-tag">{size}</span>
    </div>
    <div class="wd-meta">
      <div class="wd-meta-row">
        <span class="wd-eyebrow">{brand} • {cat}</span>
        <span class="wd-muted">{html.escape(days_l)}</span>
      </div>
      <div class="wd-name">{html.escape(display_name(row))}</div>
      <div class="wd-price-row">
        <span class="wd-price">{html.escape(price_l)}</span>
        <span class="wd-chip">{stock}</span>
      </div>
      <div class="wd-reason">
        {icon(reason_icon_name(row), 15)}
        <span><strong>Reason saved:</strong> {reason}</span>
      </div>
    </div>
  </div>
  <div class="wd-matrix">
    <div class="wd-panel">
      <div>
        <div class="wd-panel-top">
          <span class="wd-panel-label">Panel 1 — Fit Confidence</span>
          {fit_badge(conf)}
        </div>
        <span class="wd-size-cap">Suggested size based on available information</span>
        <div class="wd-head" style="color:{fit_color}">{html.escape(fit_headline(row))}</div>
        <p class="wd-body">{html.escape(row.get("fit_reason") or "")}</p>
      </div>
      <div class="wd-based"><strong style="color:#1c1b1b">Based on:</strong>
        {html.escape(compose_fit_based_on(row, usual, chest, waist))}</div>
    </div>
    <div class="wd-panel">
      <div>
        <div class="wd-panel-top">
          <span class="wd-panel-label">Panel 2 — Buy or Wait?</span>
          {decision_badge(status)}
        </div>
        <p class="wd-body">{html.escape(compose_why_line(row))}</p>
        <p class="wd-next"><strong>Next step:</strong> {html.escape(((row.get("next_step") or decision_headline(row)).rstrip(".")) + ".")}</p>
      </div>
      <div class="wd-based"><strong style="color:#1c1b1b">Based on:</strong>
        {html.escape(compose_decision_based_on(row))}</div>
    </div>
  </div>
  <div class="wd-fit-note"><strong style="color:#1c1b1b">Fit note:</strong> {html.escape(FIT_NOTE)}</div>
</article>
<div class="wd-footer">
  <a href="?view=detail&amp;item={item_id}">{icon("edit_note", 16)} Update context</a>
  <a class="strong" href="?view=detail&amp;item={item_id}">{icon("visibility", 16)} View evidence</a>
</div>
        """
    )


def render_how_it_works() -> None:
    with st.expander("How this recommendation was generated"):
        st.markdown(
            "The assistant supports decision-making using only provided "
            "information and cannot guarantee fit. It does not access live "
            "AJIO inventory, predict future prices, or treat simulated stock "
            "as live. Demo uses deterministic rules; Analyse an Item uses one "
            "Groq call when a key is configured. No discounts or coupons."
        )


def reset_state() -> None:
    st.session_state.reset_nonce = st.session_state.get("reset_nonce", 0) + 1
    st.session_state.analyse_nonce = st.session_state.get("analyse_nonce", 0) + 1
    st.session_state.pop("live_result", None)
    st.session_state.pop("live_error", None)
    st.session_state.pop("analyse_payload", None)


def _ordered_items(items: list[dict]) -> list[dict]:
    rank = {key: i for i, key in enumerate(WISHLIST_ORDER)}
    return sorted(items, key=lambda x: rank.get(str(x.get("id") or ""), 99))


def _profile_inputs(nonce: int) -> tuple[str, float | None, float | None]:
    md(
        f"""
<div class="wd-card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
    <div class="wd-section-head">
      {icon("straighten", 20)}
      <div>
        <div class="wd-name" style="margin:0">Your size profile</div>
        <p class="wd-muted" style="margin:4px 0 0">Enter this once to personalise fit guidance across your wishlist.</p>
      </div>
    </div>
    <span class="wd-lock">{icon("lock", 13)} Private to session</span>
  </div>
</div>
        """
    )
    size_col, chest_col, waist_col = st.columns(3)
    with size_col:
        usual_size = st.selectbox(
            "Usual top size",
            LETTER_SIZES,
            index=2,
            format_func=lambda s: LETTER_SIZE_LABELS.get(s, s),
            key=f"usual_size_{nonce}",
        )
    with chest_col:
        chest_raw = st.number_input(
            "Chest / Bust (inches)",
            min_value=0.0,
            max_value=60.0,
            value=40.0,
            step=0.5,
            key=f"chest_{nonce}",
        )
    with waist_col:
        waist_raw = st.number_input(
            "Waist (inches)",
            min_value=0.0,
            max_value=60.0,
            value=32.0,
            step=0.5,
            key=f"waist_{nonce}",
        )
    b1, b2, b3 = st.columns([1.6, 0.7, 1.4])
    with b1:
        if st.button("Update fit guidance", type="primary", use_container_width=True,
                     key=f"update_fit_{nonce}"):
            st.toast("Fit updated")
    with b2:
        if st.button("Reset", use_container_width=True, key=f"reset_demo_{nonce}"):
            reset_state()
            go("wishlist")
            st.rerun()
    with b3:
        st.caption("Used only for this session.")
    return usual_size, (chest_raw if chest_raw > 0 else None), (
        waist_raw if waist_raw > 0 else None
    )


def render_wishlist_page(nonce: int) -> None:
    md(
        f"""
<div>
  <h1 class="wd-h1">Your wishlist, with clearer next steps</h1>
  <p class="wd-lead">Fit signals, review evidence and your reason for saving each item are combined to help you decide.</p>
  <div class="wd-insight">
    <div class="wd-insight-kicker">{icon("psychology", 16)} From user research</div>
    <p style="margin:8px 0 0;font-size:13px;line-height:20px">
      <strong>Research insight:</strong> {html.escape(RESEARCH_INSIGHT)}
    </p>
  </div>
</div>
        """
    )
    usual, chest, waist = _profile_inputs(nonce)
    try:
        items = _ordered_items(load_sample_wishlist())
    except Exception:
        st.error(
            "Could not load the sample wishlist. Check that "
            "`mvp/sample_wishlist.json` is next to this app."
        )
        return
    if not items:
        st.info("No sample items found.")
        return

    rows = []
    for item in items:
        fit = compute_fit(item, usual, chest, waist)
        decision = compute_next_action(item, fit)
        rows.append({**item, **fit, **decision})

    n, ready, check, wait = wishlist_health_counts(rows)
    md(
        f"""
<div class="wd-health">
  <div class="wd-health-title">{icon("bookmark_manager", 18)} {n} saved items</div>
  <div class="wd-dots">
    <span class="wd-dot" style="color:#003c29"><i style="background:#003c29"></i>{ready} ready to decide</span>
    <span>•</span>
    <span class="wd-dot" style="color:#366091"><i style="background:#366091"></i>{check} need another check</span>
    <span>•</span>
    <span class="wd-dot"><i style="background:#897174"></i>{wait} worth waiting</span>
  </div>
</div>
        """
    )
    for row in rows:
        render_item_card(row, usual, chest, waist)
    render_how_it_works()


def _demo_rows_by_id(usual: str, chest: float | None, waist: float | None) -> dict[str, dict]:
    try:
        items = load_sample_wishlist()
    except Exception:
        return {}
    out = {}
    for item in items:
        fit = compute_fit(item, usual, chest, waist)
        decision = compute_next_action(item, fit)
        out[str(item.get("id") or "")] = {**item, **fit, **decision}
    return out


def render_detail_page(nonce: int) -> None:
    md(
        f'<div style="padding:0.5rem 0 0.75rem">'
        f'<a class="wd-back" href="?view=wishlist">{icon("arrow_back", 16)} Back to wishlist</a>'
        f"</div>"
    )
    item_id = st.query_params.get("item", "")
    if isinstance(item_id, list):
        item_id = item_id[0] if item_id else ""
    usual = st.session_state.get(f"usual_size_{nonce}", "M")
    chest_raw = st.session_state.get(f"chest_{nonce}", 40.0)
    waist_raw = st.session_state.get(f"waist_{nonce}", 32.0)
    chest = chest_raw if chest_raw and float(chest_raw) > 0 else None
    waist = waist_raw if waist_raw and float(waist_raw) > 0 else None
    rows = _demo_rows_by_id(usual, chest, waist)
    row = rows.get(str(item_id))
    if not row:
        st.info("That sample item is not available. Return to the wishlist.")
        return

    conf = row.get("fit_confidence") or "Low"
    status = verdict_kind(row)
    fit_bg, fit_fg = DETAIL_FIT_BADGE.get(conf, DETAIL_FIT_BADGE["Low"])
    dec_bg, dec_fg = DETAIL_DECISION_BADGE.get(status, DETAIL_DECISION_BADGE["Needs more information"])
    days = row.get("saved_days_ago")
    days_l = f"Saved {days} day{'s' if days != 1 else ''} ago" if days is not None else ""
    price = row.get("price")
    price_l = f"₹{int(price):,}" if price is not None else ""
    occasion = row.get("occasion_days_remaining")
    if isinstance(occasion, int):
        when = f"{occasion} day{'s' if occasion != 1 else ''}"
        occasion_label = str(row.get("intended_use") or row.get("save_reason") or "Dated occasion")
    else:
        when = "No date"
        occasion_label = str(row.get("save_reason") or "No specific occasion")
    questions = row.get("unresolved_questions") or []
    uncertain = questions[0] if questions else "Nothing specific noted"
    rec = str(row.get("fit_recommendation") or "")
    usual_dim, usual_val = _chart_dim(row.get("size_chart") or {}, _usual_on_chart(usual, row.get("size_chart") or {}))
    rec_dim, rec_val = _chart_dim(row.get("size_chart") or {}, rec)
    dim_label = {"chest": "chest", "bust": "bust", "waist": "waist"}.get(rec_dim or usual_dim or "", "in")
    profile_val = chest if dim_label != "waist" else waist
    if profile_val is None:
        profile_val = chest or waist
    snippets = row.get("review_snippets") or []
    quotes = (
        '<span class="wd-muted" style="letter-spacing:0.06em;text-transform:uppercase;'
        'display:block;margin-top:8px">Simulated review snippets</span>'
        + "".join(
            f'<div class="wd-quote">{icon("chat_bubble_outline", 16)}'
            f'<span>“{html.escape(str(s))}”</span></div>'
            for s in snippets[:3]
        )
    )
    evidence_rows = row.get("decision_evidence_used") or row.get("evidence_used") or []
    checks = "".join(
        f'<div class="wd-check">{icon("check_circle", 16)}'
        f"<span>{html.escape(str(e))}</span></div>"
        for e in evidence_rows[:6]
    )
    if row.get("supporting_context"):
        for extra in row["supporting_context"]:
            checks += (
                f'<div class="wd-check">{icon("check_circle", 16)}'
                f"<span>{html.escape(str(extra))}</span></div>"
            )
    measure = ""
    if profile_val or usual_val or rec_val:
        measure = f"""
        <div class="wd-measure">
          <div>
            <div class="wd-muted">Your profile</div>
            <div class="wd-price">{html.escape(f"{profile_val:g} in" if profile_val else "—")}</div>
          </div>
          <div>
            <div class="wd-muted">Size {html.escape(str(_usual_on_chart(usual, row.get("size_chart") or {})))} chart</div>
            <div class="wd-price">{html.escape(f"{usual_val:g} in" if usual_val else "—")}</div>
          </div>
          <div class="hi">
            <div class="wd-muted" style="color:#6c0029;font-weight:600">Size {html.escape(rec or "—")} chart</div>
            <div class="wd-price" style="color:#6c0029">{html.escape(f"{rec_val:g} in" if rec_val else "—")}</div>
          </div>
        </div>
        """
    md(
        f"""
<div class="wd-card xl">
  <div class="wd-item-top">
    <div class="wd-thumb">
      <img src="{html.escape(item_image(row, detail=True))}" alt=""/>
    </div>
    <div class="wd-meta" style="height:128px;display:flex;flex-direction:column;justify-content:space-between">
      <div>
        <div class="wd-eyebrow">{html.escape(str(row.get("brand") or ""))} • {html.escape(str(row.get("category") or ""))}</div>
        <div class="wd-name">{html.escape(display_name(row))}</div>
        <div class="wd-price-row">
          <span class="wd-price">{html.escape(price_l)}</span>
          <span class="wd-muted">MRP inclusive of all taxes</span>
        </div>
      </div>
      <div class="wd-price-row">
        <span class="wd-muted">{icon("calendar_today", 14)} {html.escape(days_l)}</span>
        <span class="wd-muted">{icon("inventory_2", 14)} {html.escape(stock_chip(row))}</span>
      </div>
    </div>
  </div>
</div>
<div class="wd-insight" style="margin-bottom:1.5rem">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
    {icon("bookmark_heart", 18)}
    <span class="wd-name" style="margin:0">Why you saved it</span>
  </div>
  <div class="wd-tile" style="margin-bottom:10px">
    <div class="k">Specific occasion</div>
    <div style="font-weight:500;margin-top:2px">{html.escape(occasion_label)}</div>
  </div>
  <div class="wd-grid3">
    <div class="wd-tile">
      <div class="k">Required by</div>
      <div style="font-weight:500;margin-top:2px">{html.escape(when)}</div>
    </div>
    <div class="wd-tile">
      <div class="k">Uncertainty noted</div>
      <div style="font-weight:500;margin-top:2px">{html.escape(str(uncertain))}</div>
    </div>
  </div>
</div>
<div class="wd-card xl">
  <div class="wd-panel-top" style="margin-bottom:8px">
    <span class="wd-name" style="margin:0">Panel 1 — Fit Confidence</span>
    {detail_badge(f"{conf} confidence", fit_bg, fit_fg)}
  </div>
  <div class="wd-panel" style="flex-direction:row;align-items:center;justify-content:space-between;margin:8px 0">
    <div>
      <div class="wd-panel-label">Suggested size based on available information</div>
      <div class="wd-h1" style="color:#6c0029;margin:0">{html.escape(fit_headline(row))}</div>
    </div>
    <div class="wd-avatar" style="background:rgba(108,0,41,0.08);color:#6c0029">{icon("straighten", 22)}</div>
  </div>
  <p class="wd-lead" style="margin:12px 0">{html.escape(row.get("fit_reason") or "")}</p>
  <div class="wd-panel-label" style="margin:8px 0">{icon("fact_check", 15)} Evidence used</div>
  {measure}
  {quotes}
  <p class="wd-muted" style="margin-top:12px">{icon("info", 15)} <strong>Fit note:</strong> {html.escape(FIT_NOTE)}</p>
</div>
<div class="wd-card xl">
  <div class="wd-panel-top" style="margin-bottom:8px">
    <span class="wd-name" style="margin:0">Panel 2 — Buy or Wait?</span>
    {detail_badge(status, dec_bg, dec_fg)}
  </div>
  <p class="wd-lead">{html.escape(compose_why_line(row))}</p>
  <div class="wd-panel" style="margin:8px 0 16px">
    <div class="wd-panel" style="flex-direction:row;gap:10px;align-items:center;margin-bottom:10px">
      {icon("arrow_circle_right", 20)}
      <div>
        <div class="wd-panel-label">Concrete Next Step</div>
        <div style="font-weight:600">{html.escape(row.get("next_step") or decision_headline(row))}</div>
      </div>
    </div>
    <div class="wd-panel-label">{icon("checklist", 15)} Based on</div>
    {checks}
  </div>
</div>
        """
    )
    if st.button("Change my answers", use_container_width=True, key="detail_change"):
        go("wishlist")
        st.rerun()
    with st.expander("View sizing chart details"):
        chart = row.get("size_chart") or {}
        if not chart:
            st.caption("No size chart on this sample item.")
        else:
            for size, dims in chart.items():
                st.write(f"**{size}** — {dims}")
    render_how_it_works()


def render_analyse_page(api_key: str | None) -> None:
    nonce = st.session_state.get("analyse_nonce", 0)
    md(
        f"""
<div class="wd-kicker">{icon("fact_check", 14)} Structured Evaluation</div>
<h1 class="wd-h1 lg">Analyse a wishlisted item</h1>
<p class="wd-lead">Add the information you already have. The assistant will not invent missing product details.</p>
        """
    )
    md(
        f"""
<div class="wd-card xl" style="margin-bottom:0.35rem">
  <div class="wd-section-head">
    <div class="wd-num">1</div>
    <div>
      <div class="wd-name" style="margin:0">Product Information</div>
      <p class="wd-muted" style="margin:0">Archival specs, manufacturer data, and verified customer notes</p>
    </div>
  </div>
</div>
        """
    )
    with st.form(f"analyse_form_{nonce}"):
        prod_name = st.text_input("Product Name *", placeholder="e.g. Cotton Relaxed Cuban Collar Shirt")
        c1, c2 = st.columns(2)
        with c1:
            brand = st.text_input("Brand (optional)", placeholder="e.g. Netplay, Marks & Spencer")
        with c2:
            category = st.selectbox(
                "Category *",
                ANALYSE_CATEGORIES,
                index=None,
                placeholder="Select category",
            )
        price = st.text_input("Current Price (optional)", placeholder="1899")
        size_chart = st.text_area(
            "Size Chart / Exact Specs",
            placeholder="Paste measurement table or key sizing specs e.g. M: Chest 38, L: Chest 40...",
            height=80,
        )
        reviews = st.text_area(
            "Review Snippets & User Feedback",
            placeholder="Paste relevant review comments mentioning fit, cut, fabric, or sizing...",
            height=80,
        )
        availability = st.text_input(
            "Availability Notes (optional)",
            placeholder="e.g. Only size L was listed in stock this morning",
        )
        st.caption(
            "Only enter availability notes for reference. The assistant will "
            "treat any availability as simulated and will never consider it "
            "verified live inventory."
        )

        md(
            f"""
<div class="wd-card xl" style="margin:1rem 0 0.35rem">
  <div class="wd-section-head">
    <div class="wd-num">2</div>
    <div>
      <div class="wd-name" style="margin:0">Your Decision Context</div>
      <p class="wd-muted" style="margin:0">Your baseline fit, wear rationale, and underlying hesitation</p>
    </div>
  </div>
</div>
            """
        )
        s1, s2, s3 = st.columns(3)
        with s1:
            usual = st.selectbox(
                "Usual Size *",
                LETTER_SIZES,
                index=None,
                placeholder="Size",
            )
        with s2:
            chest_in = st.number_input("Chest / Bust (in)", min_value=0.0, max_value=60.0, value=0.0, step=0.5)
        with s3:
            waist_in = st.number_input("Waist (in)", min_value=0.0, max_value=60.0, value=0.0, step=0.5)
        save_reason = st.text_area(
            "Why did you save this item?",
            placeholder="e.g. Trying to replace a faded linen shirt, loved the neutral shade...",
            height=70,
        )
        o1, o2 = st.columns(2)
        with o1:
            occasion = st.radio("Is it for a particular occasion?", ["No", "Yes"], horizontal=True)
        with o2:
            timeline = st.text_input("When do you need it? (optional)", placeholder="e.g. 10 days, next week, or no date")
        unsure = st.multiselect(
            "What are you still unsure about?",
            UNCERTAINTY_CHIPS,
            help="Select all areas you want evaluated directly",
        )
        comparing = st.radio("Are you comparing another product?", ["No", "Yes"], horizontal=True)
        extra = st.text_area(
            "Additional context (optional)",
            placeholder="Any specific laundry concerns, fabric sensitivity, or matching pieces already in wardrobe...",
            height=70,
        )
        md(
            f"""
<div class="wd-callout">
  {icon("policy", 22)}
  <div>
    <div class="wd-policy-kicker">Verification Policy</div>
    <p style="margin:4px 0 0;font-size:13px;line-height:20px">
      If essential information is missing, the assistant will ask you to verify it instead of making a confident recommendation.
      <span class="wd-muted" style="display:block;margin-top:4px"><strong style="color:#1c1b1b">Fit note:</strong> {html.escape(FIT_NOTE)}</span>
    </p>
  </div>
</div>
            """
        )
        submitted = st.form_submit_button("Analyse this item", type="primary", use_container_width=True)

    c_clear, _ = st.columns([1, 2])
    with c_clear:
        if st.button("Clear form", use_container_width=True, key=f"clear_analyse_{nonce}"):
            st.session_state.analyse_nonce = nonce + 1
            st.session_state.pop("live_result", None)
            st.session_state.pop("live_error", None)
            st.session_state.pop("analyse_payload", None)
            go("analyse")
            st.rerun()

    if not submitted:
        if st.session_state.get("live_error"):
            st.error(st.session_state.live_error)
        return
    if not str(prod_name or "").strip():
        st.warning("Add a product name so we know which saved item you mean.")
        return
    if not str(category or "").strip():
        st.warning("Select a category.")
        return
    if not str(usual or "").strip():
        st.warning("Select your usual size.")
        return
    if not api_key:
        st.info(
            "Analyse an Item needs a Groq API key. Sample Wishlist works without one — "
            "or add `GROQ_API_KEY` in the app’s Streamlit secrets."
        )
        return

    size_bits = [f"Usual {usual.strip()}"]
    if chest_in and chest_in > 0:
        size_bits.append(f"chest {chest_in:g} in")
    if waist_in and waist_in > 0:
        size_bits.append(f"waist {waist_in:g} in")
    chips = list(unsure or [])
    if "Nothing specific" in chips and len(chips) > 1:
        chips = ["Nothing specific"]
    payload = {
        "product": " ".join(p for p in (prod_name.strip(), brand.strip()) if p),
        "product_name": prod_name.strip(),
        "brand": brand.strip(),
        "category": category.strip(),
        "price": price.strip(),
        "why_saved": save_reason.strip(),
        "occasion_for": (
            save_reason.strip() or "Yes"
            if occasion == "Yes"
            else "No specific occasion"
        ),
        "occasion_timing": timeline.strip(),
        "unresolved_questions": ", ".join(chips),
        "comparison_status": "comparing" if comparing == "Yes" else "not_comparing",
        "size_info": ", ".join(size_bits),
        "size_chart": size_chart.strip(),
        "reviews": reviews.strip(),
        "availability": availability.strip(),
        "extra_context": extra.strip(),
    }
    st.session_state.analyse_payload = payload
    if _live_payload_too_thin(payload):
        result = _live_fallback_result(
            "There is not enough size or review information to make a responsible recommendation."
        )
        result["name"] = prod_name.strip()
        result["brand"] = brand.strip()
        result["category"] = category.strip()
        result["price"] = price.strip() or None
        st.session_state.live_result = result
        st.session_state.live_error = None
        go("live_result")
        st.rerun()
        return
    try:
        t0 = time.perf_counter()
        parsed = call_groq(payload, api_key)
        result = normalize_live_result(parsed)
        result["eval_seconds"] = round(time.perf_counter() - t0, 1)
        result["name"] = prod_name.strip()
        result["brand"] = brand.strip()
        result["category"] = category.strip()
        result["price"] = price.strip() or None
        st.session_state.live_result = result
        st.session_state.live_error = None
        go("live_result")
        st.rerun()
    except Exception:
        st.session_state.live_result = None
        st.session_state.live_error = (
            "Could not get a live decision just now. Check the API key "
            "and try again — or use Sample Wishlist, which works without a key."
        )
        st.error(st.session_state.live_error)


def render_live_result_page() -> None:
    if st.session_state.get("live_error"):
        st.error(st.session_state.live_error)
        if st.button("Back to form", type="primary"):
            go("analyse")
            st.rerun()
        return
    result = st.session_state.get("live_result")
    if not result:
        go("analyse")
        st.rerun()
        return

    status = verdict_kind(result)
    conf = result.get("fit_confidence") or "Low"
    insufficient = status == "Needs more information"

    if insufficient:
        adds = [
            "Add a size chart",
            "Add one or more review snippets",
            "Provide a measurement or usual size",
        ]
        extra = result.get("next_step") or ""
        add_html = "".join(
            f'<div class="wd-add"><span class="plus">{icon("add", 13)}</span>'
            f"<span>{html.escape(a)}</span></div>"
            for a in adds
        )
        md(
            f"""
<div class="wd-card xl">
  <div class="wd-panel-top">
    <div style="display:flex;align-items:center;gap:6px">
      {icon("straighten", 20)}
      <span class="wd-name" style="margin:0">Panel 1 — Fit Confidence</span>
    </div>
    {detail_badge("Low confidence", "#EEF0F3", "#596273")}
  </div>
  <div class="wd-panel" style="margin:10px 0">
    <span class="wd-size-cap">Suggested size based on available information</span>
    <div class="wd-h1" style="margin:4px 0 0">Insufficient information to suggest size</div>
  </div>
  <p class="wd-lead">{html.escape(compose_why_line(result) or extra)}</p>
  <div class="wd-fit-note"><strong style="color:#1c1b1b">Fit note:</strong> {html.escape(FIT_NOTE)}</div>
</div>
<div class="wd-card xl">
  <div class="wd-panel-top">
    <div style="display:flex;align-items:center;gap:6px">
      {icon("flag_circle", 20)}
      <span class="wd-name" style="margin:0">Panel 2 — Buy or Wait?</span>
    </div>
    {detail_badge("Needs more information", "#EEF0F3", "#596273")}
  </div>
  <p class="wd-lead">Wait before buying until essential sizing or customer feedback signals can be verified.</p>
  <div class="wd-panel" style="margin-bottom:12px">
    <div class="wd-panel-label">Concrete Next Steps</div>
    {add_html}
  </div>
</div>
            """
        )
        if st.button("Provide missing item details", type="primary", use_container_width=True):
            st.session_state.pop("live_result", None)
            go("analyse")
            st.rerun()
        st.caption("Our algorithm refuses guesswork to protect you from unnecessary returns.")
        return

    payload = st.session_state.get("analyse_payload") or {}
    name = result.get("name") or payload.get("product_name") or "Your item"
    brand = result.get("brand") or payload.get("brand") or ""
    category = result.get("category") or payload.get("category") or ""
    price = result.get("price") or payload.get("price") or ""
    subtitle_bits = [x for x in (name, brand, category, f"₹{price}" if price else "") if x]
    elapsed = result.get("eval_seconds")
    elapsed_l = f"Evaluated in {elapsed}s" if elapsed is not None else "Analysis ready"
    fit_ev = result.get("fit_evidence_used") or []
    dec_ev = result.get("decision_evidence_used") or result.get("evidence_used") or []
    fit_lis = "".join(
        f'<div class="wd-check">{icon("check_circle", 16)}<span>{html.escape(str(x))}</span></div>'
        for x in fit_ev
    ) or (
        f'<div class="wd-check">{icon("remove_circle_outline", 16)}'
        f"<span>No fit evidence listed</span></div>"
    )
    dec_lis = "".join(
        f'<div class="wd-check">{icon("radio_button_checked", 16)}<span>{html.escape(str(x))}</span></div>'
        for x in dec_ev
    )
    fit_bg, fit_fg = DETAIL_FIT_BADGE.get(conf, DETAIL_FIT_BADGE["Medium"])
    dec_bg, dec_fg = DETAIL_DECISION_BADGE.get(status, DETAIL_DECISION_BADGE["Check one thing first"])
    md(
        f"""
<div class="wd-card xl">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
    <span class="wd-badge" style="background:#a8f2ce;color:#002115">{icon("check_circle", 14)} Analysis ready</span>
    <span class="wd-muted">{html.escape(elapsed_l)}</span>
  </div>
  <div class="wd-item-top">
    <div class="wd-thumb" style="width:64px;height:80px">
      <img src="{html.escape(LIVE_PLACEHOLDER_IMAGE)}" alt=""/>
    </div>
    <div class="wd-meta">
      <div class="wd-eyebrow" style="color:#6c0029">Product Heading</div>
      <div class="wd-name">Your item analysis</div>
      <p class="wd-muted" style="margin:4px 0 0">{html.escape(" • ".join(subtitle_bits))}</p>
    </div>
  </div>
</div>
<div class="wd-card xl">
  <div class="wd-panel-top">
    <div style="display:flex;align-items:center;gap:6px">
      {icon("straighten", 20)}
      <span class="wd-name" style="margin:0">Panel 1 — Fit Confidence</span>
    </div>
    {detail_badge(f"{conf} confidence", fit_bg, fit_fg)}
  </div>
  <div class="wd-panel" style="flex-direction:row;align-items:center;justify-content:space-between;margin:10px 0">
    <div>
      <div class="wd-muted">Suggested size based on available information</div>
      <div class="wd-h1" style="color:#6c0029;margin:0">{html.escape(fit_headline(result))}</div>
    </div>
  </div>
  <p class="wd-lead">{html.escape(result.get("fit_reason") or "")}</p>
  <div class="wd-fit-note"><strong style="color:#1c1b1b">Fit note:</strong> {html.escape(FIT_NOTE)}</div>
  <div class="wd-panel-label">Based on</div>
  {fit_lis}
</div>
<div class="wd-card xl">
  <div class="wd-panel-top">
    <div style="display:flex;align-items:center;gap:6px">
      {icon("flag_circle", 20)}
      <span class="wd-name" style="margin:0">Panel 2 — Buy or Wait?</span>
    </div>
    {detail_badge(status, dec_bg, dec_fg)}
  </div>
  <p class="wd-lead">{html.escape(compose_why_line(result))}</p>
  <div class="wd-panel" style="flex-direction:row;gap:10px;align-items:flex-start;margin-bottom:12px">
    {icon("priority_high", 20)}
    <div>
      <div class="wd-panel-label">Next step</div>
      <div style="font-weight:500">{html.escape(result.get("next_step") or decision_headline(result))}</div>
    </div>
  </div>
  <div class="wd-panel-label">Based on</div>
  {dec_lis}
</div>
        """
    )
    if st.button("Analyse another item", type="primary", use_container_width=True):
        st.session_state.analyse_nonce = st.session_state.get("analyse_nonce", 0) + 1
        st.session_state.pop("live_result", None)
        st.session_state.pop("analyse_payload", None)
        go("analyse")
        st.rerun()
    if st.button("Edit my information", use_container_width=True):
        st.session_state.pop("live_result", None)
        go("analyse")
        st.rerun()
    render_how_it_works()


def main() -> None:
    st.set_page_config(
        page_title="AJIO Wishlist Decision Assistant",
        page_icon="🛍️",
        layout="centered",
    )
    inject_css()
    if "reset_nonce" not in st.session_state:
        st.session_state.reset_nonce = 0
    if "analyse_nonce" not in st.session_state:
        st.session_state.analyse_nonce = 0

    view = current_view()
    api_key = get_groq_api_key()
    nonce = st.session_state.reset_nonce

    if view == "detail":
        render_chrome("detail")
        render_detail_page(nonce)
    elif view == "live_result":
        render_chrome("live_result")
        render_live_result_page()
    elif view == "analyse":
        render_chrome("analyse")
        render_analyse_page(api_key)
    else:
        render_chrome("wishlist")
        render_wishlist_page(nonce)


if __name__ == "__main__":
    main()
