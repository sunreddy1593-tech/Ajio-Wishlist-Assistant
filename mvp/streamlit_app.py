"""Wishlist Decision Assistant — standalone Streamlit MVP.

Demo mode is fully offline (seeded JSON + deterministic rules).
Live mode makes one Groq chat call when a key is present in st.secrets.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
from pathlib import Path

import streamlit as st

logger = logging.getLogger("wishlist_assistant")

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
FIT_REVIEW_WORD_RE = re.compile(
    r"\b(fit|fits|fitting|sizing|size|tight|loose|snug|baggy|small|large|"
    r"chest|waist|bust|shrink)\b"
)

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_MAX_TOKENS = 1500
DEBUG_MODE = False
API_UNAVAILABLE_MESSAGE = (
    "Live analysis is temporarily unavailable. Please try again."
)
PARSE_FAILED_MESSAGE = (
    "The analysis response could not be processed. Please try again."
)
SECRET_MISSING_MESSAGE = (
    "Live AI analysis is unavailable because the deployment secret is not configured."
)
RULE_FALLBACK_LABEL = (
    "Rule-based fallback — live AI analysis unavailable."
)
# The three custom-analysis failure states. Never collapse one into another.
VALIDATION_ERROR = "validation_error"
PROCESSING_ERROR = "processing_error"
SERVICE_ERROR = "service_error"
NO_SECRET = "no_secret"
RULE_FALLBACK = "rule_fallback"
CUSTOM_PAYLOAD_FIELDS = (
    "product_name",
    "brand",
    "product",
    "category",
    "price",
    "why_saved",
    "occasion_for",
    "occasion_timing",
    "unresolved_questions",
    "comparison_status",
    "usual_size",
    "chest",
    "waist",
    "size_info",
    "size_chart",
    "reviews",
    "availability",
    "extra_context",
)
CUSTOM_PAYLOAD_FIELD_LABELS = {
    "product_name": "Product name",
    "brand": "Brand",
    "product": "Product name / brand",
    "category": "Category",
    "price": "Price",
    "why_saved": "Why they saved it",
    "occasion_for": "Is it for a particular occasion?",
    "occasion_timing": "When they need it",
    "unresolved_questions": "What they are still unsure about",
    "comparison_status": "Are they comparing another item?",
    "usual_size": "Usual size",
    "chest": "Chest / bust (in)",
    "waist": "Waist (in)",
    "size_info": "Size and optional measurements",
    "size_chart": "Size chart",
    "reviews": "Review snippets",
    "availability": "Availability notes (user-reported, not live inventory)",
    "extra_context": "Additional context",
}
LIVE_RESULT_REQUIRED_KEYS = (
    "fit_recommendation",
    "fit_confidence",
    "fit_reason",
    "fit_evidence_used",
    "decision_status",
    "decision_reason",
    "next_step",
    "decision_evidence_used",
)
GROQ_RESPONSE_KEYS = (
    "fit_recommendation",
    "fit_confidence",
    "fit_reason",
    "buy_or_wait",
    "buy_wait_reason",
    "info_to_check",
)


class GroqAPIError(Exception):
    """Groq HTTP/SDK failure — not a missing-user-information problem."""


class GroqParseError(Exception):
    """Response JSON/schema could not be processed — not missing user input."""

LIVE_DECISION_STATUSES = (
    "Ready to buy",
    "Check one thing first",
    "Compare first",
    "Worth waiting",
    "Reconsider this save",
    "Needs more information",
)

# Strict JSON-schema mode requires every property to be listed in "required".
# Compact on purpose: long evidence arrays were truncating json_schema output.
ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "fit_recommendation": {"type": "string"},
        "fit_confidence": {"type": "string", "enum": ["High", "Medium", "Low"]},
        "fit_reason": {"type": "string"},
        "buy_or_wait": {"type": "string", "enum": list(LIVE_DECISION_STATUSES)},
        "buy_wait_reason": {"type": "string"},
        "info_to_check": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
    },
    "required": list(GROQ_RESPONSE_KEYS),
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a wishlist decision assistant. The shopper already saved this item.

Use ONLY supplied fields: size chart, measurements, reviews, save reason, intended use, occasion timing, comparison status, and unresolved questions. Optional stock notes, if present, are the user's own words — not live inventory.

Rules:
- Never invent a blocker that the user did not state.
- Never claim the user is price-watching unless they explicitly say they are watching price or waiting for a cheaper price.
- Never invent scarcity. Never treat stock notes as live inventory or as the sole reason to buy.
- Never recommend a discount, coupon, markdown, or waiting for a sale.
- If evidence is insufficient to recommend a size or a next action, set buy_or_wait to "Needs more information".
- Do not ask the shopper to add a size chart, reviews, or measurements when those fields are already supplied (not "(not provided)").
- Keep every field concise; respond with ONLY the JSON object, no prose.

Respond with ONLY valid JSON — no markdown, no code fences, no extra text. Exact schema:
{
  "fit_recommendation": "string",
  "fit_confidence": "High | Medium | Low",
  "fit_reason": "<=25 words",
  "buy_or_wait": "Ready to buy | Check one thing first | Compare first | Worth waiting | Reconsider this save | Needs more information",
  "buy_wait_reason": "<=25 words",
  "info_to_check": ["max 3 short items"]
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
ANALYSE_PROTOTYPE_CALLOUT = (
    "Prototype testing mode: In an integrated AJIO experience, product details, "
    "size charts and reviews would be filled automatically from the selected "
    "wishlist item. Manual entry is included here only to test the assistant "
    "with products outside the sample wishlist."
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
    """Read GROQ_API_KEY from st.secrets only. Never from the environment."""
    try:
        key = st.secrets["GROQ_API_KEY"]
    except Exception:
        return None
    if key is None:
        return None
    key = str(key).strip()
    return key or None


def groq_key_detected() -> bool:
    """True when a non-empty Groq secret is configured. Never returns the key."""
    return bool(get_groq_api_key())


def _log_adapter_error(context: str, exc: BaseException | None = None) -> None:
    """Log adapter failures for diagnosis.

    The formatted message carries only a context string and the exception type
    name. The traceback is attached via exc_info, which prints source lines but
    never local values, so the API key, the customer payload, and other secrets
    stay out of the log.
    """
    name = type(exc).__name__ if exc is not None else "Error"
    logger.error("%s (%s)", context, name, exc_info=exc)


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


def _one_size_step(from_size: str | None, to_size: str | None) -> bool:
    """True when to_size is one chart step away from from_size."""
    if not from_size or not to_size:
        return False
    a = str(from_size).strip().upper()
    b = str(to_size).strip().upper()
    if a == b:
        return False
    if a in LETTER_SIZES and b in LETTER_SIZES:
        return abs(LETTER_SIZES.index(a) - LETTER_SIZES.index(b)) == 1
    if a.isdigit() and b.isdigit():
        return abs(int(a) - int(b)) == 2
    return False


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
    directional = False
    if signals["runs_small"] and not conflicting:
        recommended = _nudge_size(recommended, 1)
        directional = True
    elif signals["runs_large"] and not conflicting:
        recommended = _nudge_size(recommended, -1)
        directional = True

    measurement_agrees = (
        match_size is not None
        and match_diff is not None
        and match_diff <= 1.0
    )
    has_clear_review = (
        (signals["true_to_size"] or signals["runs_small"] or signals["runs_large"])
        and not conflicting
    )
    reviews_agree_on_match = (
        has_clear_review
        and measurement_agrees
        and recommended == match_size
        and not directional
    )
    review_one_step_off = (
        has_clear_review
        and measurement_agrees
        and directional
        and _one_size_step(match_size, recommended)
    )
    rec_on_chart = bool(size_chart) and recommended in size_chart
    unsupported = (
        (bool(size_chart) and not rec_on_chart)
        or (directional and measurement_agrees and not _one_size_step(match_size, recommended) and recommended != match_size)
        or (not size_chart and not measurement_agrees)
    )

    if conflicting:
        confidence = "Low"
        reason = (
            f"Reviews disagree on sizing, so stay near {base} until you can try it "
            "or check a store."
        )
    elif unsupported:
        confidence = "Low"
        if not size_chart:
            reason = (
                f"Not enough to go on — using your usual {usual_size} as "
                f"{recommended}. Add a size chart or measurements."
            )
        elif not rec_on_chart:
            reason = (
                f"Reviews point toward {recommended}, but that size is not on the "
                "supplied chart, so the pick needs a check."
            )
        else:
            reason = (
                f"Suggested size {recommended} leans on an adjustment that the "
                "chart and measurements do not support. Check fit before buying."
            )
    elif reviews_agree_on_match:
        confidence = "High"
        reason = (
            f"Your {match_dim} matches {match_size} on the size chart and "
            "reviewers call it true to size."
        )
    elif review_one_step_off:
        confidence = "Medium"
        direction = "sizing up" if signals["runs_small"] else "sizing down"
        reason = (
            f"Your {match_dim} matches {match_size} on the chart, but reviews "
            f"say it runs {'small' if signals['runs_small'] else 'large'}, so "
            f"{recommended} is suggested. The signals support {direction} but "
            f"do not directly agree on {recommended}."
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


def compute_next_action(
    item: dict, fit: dict, *, gaps: list[str] | None = None
) -> dict:
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
    missing = _important_info_missing(item) if gaps is None else list(gaps)

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
    return aliases.get(token, "")


def verdict_kind(result: dict) -> str:
    if result.get("failure_kind") in (SERVICE_ERROR, PROCESSING_ERROR, NO_SECRET):
        return ""
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
    """Remove optional markdown code fences before JSON parsing."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    fenced = re.search(
        r"```(?:json)?\s*(.*?)\s*```",
        cleaned,
        flags=re.I | re.DOTALL,
    )
    if fenced:
        return fenced.group(1).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _parse_model_json(raw: str) -> dict:
    """Parse a JSON object after stripping optional fences. Never raises."""
    cleaned = _strip_code_fences(raw)
    if not cleaned:
        return {}
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _parse_groq_json(raw: str) -> dict:
    """Strip fences, then parse JSON. Raises GroqParseError on failure."""
    cleaned = _strip_code_fences(raw)
    if not cleaned:
        raise GroqParseError("empty Groq response")
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError, ValueError):
        _log_adapter_error("Groq response JSON could not be parsed")
        raise GroqParseError("Groq response JSON could not be parsed") from None
    if not isinstance(parsed, dict) or not parsed:
        raise GroqParseError("Groq response was not a JSON object")
    return parsed


def _build_live_user_prompt(payload: dict) -> str:
    """Include every supplied custom-form field. Ask for JSON only."""
    lines = [
        "Advise on this wishlisted fashion item using only the fields below.",
        "If a field is (not provided), do not invent it.",
        "If evidence is insufficient, set buy_or_wait to \"Needs more information\".",
        "Keep every field concise; respond with ONLY the JSON object, no prose.",
        "Return ONLY a JSON object. No markdown, no code fences, no extra text.",
        "",
    ]
    for key in CUSTOM_PAYLOAD_FIELDS:
        label = CUSTOM_PAYLOAD_FIELD_LABELS[key]
        val = payload.get(key)
        if val is None:
            text = ""
        else:
            text = str(val).strip()
        lines.append(f"{label}: {text if text else '(not provided)'}")
    return "\n".join(lines) + "\n"


def _blank_to_none(value):
    """Empty strings and zero measurements become None. Other zeros unchanged."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, bool):
        return value
    return value


def _none_if_zero_measure(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None
    if number == 0:
        return None
    return number


def _has_usual_size(payload: dict) -> bool:
    usual = payload.get("usual_size")
    if usual not in (None, ""):
        return True
    return bool(re.search(r"\busual\b", _norm(str(payload.get("size_info") or ""))))


def _has_body_measurement(payload: dict) -> bool:
    for key in ("chest", "waist"):
        val = payload.get(key)
        if val in (None, ""):
            continue
        try:
            if float(val) > 0:
                return True
        except (TypeError, ValueError):
            if str(val).strip():
                return True
    info = _norm(str(payload.get("size_info") or ""))
    return "chest" in info or "waist" in info or "bust" in info


def _has_fit_review_evidence(payload: dict) -> bool:
    reviews = payload.get("reviews")
    snippets = payload.get("review_snippets")
    parts: list[str] = []
    if reviews:
        parts.append(str(reviews))
    if isinstance(snippets, (list, tuple)):
        parts.extend(str(s) for s in snippets if s)
    elif snippets:
        parts.append(str(snippets))
    blob = _norm(" ".join(parts))
    if not blob:
        return False
    if any(_keyword_hit(blob, key) for key in RUN_SMALL_KEYS + RUN_LARGE_KEYS + TRUE_SIZE_KEYS):
        return True
    return bool(FIT_REVIEW_WORD_RE.search(blob))


def _has_size_chart(payload: dict) -> bool:
    chart = payload.get("size_chart")
    if chart in (None, "", {}, []):
        return False
    if isinstance(chart, dict):
        return bool(chart)
    return bool(str(chart).strip())


def validate_custom_payload(payload: dict) -> list[str]:
    """Normalise blanks/zero measurements to None. Return actually-missing fields.

    Does not claim a field is missing when it exists on the payload.
    """
    string_keys = (
        "product",
        "product_name",
        "brand",
        "category",
        "price",
        "why_saved",
        "occasion_for",
        "occasion_timing",
        "unresolved_questions",
        "comparison_status",
        "size_info",
        "size_chart",
        "reviews",
        "availability",
        "extra_context",
        "usual_size",
    )
    for key in string_keys:
        if key in payload:
            payload[key] = _blank_to_none(payload[key])
    for key in ("chest", "waist"):
        if key in payload:
            payload[key] = _none_if_zero_measure(payload[key])

    missing: list[str] = []
    if not (payload.get("product_name") or payload.get("product")):
        missing.append("Product name")
    if not payload.get("category"):
        missing.append("Category")
    if not _has_usual_size(payload):
        missing.append("Usual size")
    if not (
        _has_size_chart(payload)
        or _has_body_measurement(payload)
        or _has_fit_review_evidence(payload)
    ):
        missing.append(
            "Fit evidence (size chart, a body measurement, or fit-related reviews)"
        )
    return missing


def build_custom_analysis_payload(
    *,
    prod_name,
    brand,
    category,
    price,
    size_chart,
    reviews,
    availability,
    usual,
    chest_in,
    waist_in,
    save_reason,
    occasion,
    timeline,
    unsure,
    comparing,
    extra,
) -> dict:
    """Build one payload dict from the current form variables."""
    name = _blank_to_none(prod_name)
    brand_v = _blank_to_none(brand)
    usual_v = _blank_to_none(usual)
    chest = _none_if_zero_measure(chest_in)
    waist = _none_if_zero_measure(waist_in)
    save = _blank_to_none(save_reason)
    chips = [str(c).strip() for c in (unsure or []) if str(c).strip()]
    if "Nothing specific" in chips and len(chips) > 1:
        chips = ["Nothing specific"]
    size_bits = []
    if usual_v:
        size_bits.append(f"Usual {usual_v}")
    if chest:
        size_bits.append(f"chest {chest:g} in")
    if waist:
        size_bits.append(f"waist {waist:g} in")
    if occasion == "Yes":
        occasion_for = save or "Yes"
    else:
        occasion_for = "No specific occasion"
    product_bits = [p for p in (name, brand_v) if p]
    return {
        "product": " ".join(product_bits) or None,
        "product_name": name,
        "brand": brand_v,
        "category": _blank_to_none(category),
        "price": _blank_to_none(price),
        "why_saved": save,
        "occasion_for": occasion_for,
        "occasion_timing": _blank_to_none(timeline),
        "unresolved_questions": ", ".join(chips) or None,
        "comparison_status": "comparing" if comparing == "Yes" else "not_comparing",
        "size_info": ", ".join(size_bits) or None,
        "size_chart": _blank_to_none(size_chart),
        "reviews": _blank_to_none(reviews),
        "availability": _blank_to_none(availability),
        "extra_context": _blank_to_none(extra),
        "usual_size": usual_v,
        "chest": chest,
        "waist": waist,
    }


def _live_payload_too_thin(payload: dict) -> bool:
    """True when fit analysis lacks chart, measurement, or fit-related reviews."""
    missing = validate_custom_payload(dict(payload))
    return any("fit evidence" in item.lower() for item in missing)


def _field_is_present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    if isinstance(value, (int, float)):
        return value != 0
    return True


def payload_fields_present(payload: dict) -> dict[str, bool]:
    """Boolean presence of each custom-form field. Never includes raw values."""
    return {key: _field_is_present((payload or {}).get(key)) for key in CUSTOM_PAYLOAD_FIELDS}


def _record_debug(update: dict) -> None:
    """Store adapter diagnostics. Never stores the API key or raw personal inputs."""
    if not DEBUG_MODE:
        return
    safe = dict(update)
    safe.pop("api_key", None)
    safe.pop("payload", None)
    try:
        current = dict(st.session_state.get("custom_analysis_debug") or {})
        current.update(safe)
        st.session_state["custom_analysis_debug"] = current
    except Exception:
        return


def _empty_debug(payload: dict | None = None, *, key_detected: bool = False) -> dict:
    return {
        "payload_fields_present": payload_fields_present(payload or {}),
        "validation_errors": [],
        "groq_key_detected": bool(key_detected),
        "api_call_succeeded": False,
        "json_parse_succeeded": False,
    }


def _map_fit_confidence(raw) -> str:
    token = _safe_str(raw).title()
    if token in ("High", "Medium", "Low"):
        return token
    return {"high": "High", "medium": "Medium", "low": "Low"}.get(_norm(_safe_str(raw)), "")


def _uses_compact_live_schema(parsed: dict) -> bool:
    """True when the model returned the compact Groq JSON contract."""
    return "buy_or_wait" in parsed and "decision_status" not in parsed


def validate_live_schema(parsed) -> list[str]:
    """Return schema errors. Does not coerce unknown statuses into Needs more information."""
    if not isinstance(parsed, dict):
        return ["Response is not a JSON object"]
    if not parsed or parsed.get("_parse_failed"):
        return ["Response JSON object is empty or unreadable"]
    errors: list[str] = []
    if _uses_compact_live_schema(parsed):
        for key in GROQ_RESPONSE_KEYS:
            if key not in parsed:
                errors.append(f"Missing field: {key}")
        if "fit_confidence" in parsed and not _map_fit_confidence(
            parsed.get("fit_confidence")
        ):
            errors.append("Invalid fit_confidence")
        if "buy_or_wait" in parsed:
            mapped = _map_decision_status(_safe_str(parsed.get("buy_or_wait")))
            if not mapped or mapped not in VERDICT_STYLES:
                errors.append("Invalid buy_or_wait")
        if (
            "info_to_check" in parsed
            and parsed["info_to_check"] is not None
            and not isinstance(parsed["info_to_check"], (str, list, tuple))
        ):
            errors.append("Invalid info_to_check")
        for key in ("fit_reason", "buy_wait_reason"):
            if key in parsed and isinstance(parsed.get(key), dict):
                errors.append(f"Invalid {key}")
        return errors
    for key in LIVE_RESULT_REQUIRED_KEYS:
        if key not in parsed:
            errors.append(f"Missing field: {key}")
    if "fit_confidence" in parsed and not _map_fit_confidence(parsed.get("fit_confidence")):
        errors.append("Invalid fit_confidence")
    if "decision_status" in parsed:
        mapped = _map_decision_status(_safe_str(parsed.get("decision_status")))
        if not mapped or mapped not in VERDICT_STYLES:
            errors.append("Invalid decision_status")
    for key in ("fit_evidence_used", "decision_evidence_used"):
        if key in parsed and parsed[key] is not None and not isinstance(
            parsed[key], (str, list, tuple)
        ):
            errors.append(f"Invalid {key}")
    for key in ("fit_reason", "decision_reason", "next_step"):
        if key in parsed and isinstance(parsed.get(key), dict):
            errors.append(f"Invalid {key}")
    return errors


def call_groq(payload: dict, api_key: str) -> dict:
    """One Groq chat call. Raises GroqAPIError or GroqParseError. Never logs the key."""
    try:
        from groq import Groq
    except Exception as exc:
        _log_adapter_error("Groq client is unavailable", exc)
        raise GroqAPIError("Groq client is unavailable") from None

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_live_user_prompt(payload)},
            ],
            temperature=0.2,
            max_tokens=GROQ_MAX_TOKENS,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "wishlist_item_analysis",
                    "strict": True,
                    "schema": ANALYSIS_SCHEMA,
                },
            },
        )
    except GroqAPIError:
        raise
    except GroqParseError:
        raise
    except Exception as exc:
        _log_adapter_error("Groq API request failed", exc)
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        body = getattr(response, "text", None)
        detail = repr(exc)
        if status is not None or body:
            detail = f"{detail} status={status} body={body}"
        logger.error("Groq API request failed: %s", detail)
        print(f"Groq API request failed: {detail}", flush=True)
        raise GroqAPIError("Groq API request failed") from None

    try:
        raw = (response.choices[0].message.content or "").strip()
    except (AttributeError, IndexError, TypeError) as exc:
        _log_adapter_error("Groq response had no message content", exc)
        raise GroqParseError("Groq response had no message content") from None

    return _parse_groq_json(raw)


def _apply_item_identity(result: dict, payload: dict | None) -> dict:
    payload = payload or {}
    result["name"] = (
        payload.get("product_name") or payload.get("product") or result.get("name") or "Your item"
    )
    result["brand"] = payload.get("brand") or result.get("brand") or ""
    result["category"] = payload.get("category") or result.get("category") or "Custom paste"
    if payload.get("price") is not None:
        result["price"] = payload.get("price")
    result["is_live"] = True
    return result


def _live_fallback_result(message: str = "", *, parse_failed: bool = False) -> dict:
    reason = (
        message
        or "Not enough supplied evidence to recommend a size or a next action."
    )
    if parse_failed:
        next_step = "Try Analyse again. Your submitted details were received."
    else:
        next_step = (
            "Add a size chart, measurements, reviews, save reason, or what is "
            "blocking you, then try again."
        )
    return {
        "fit_recommendation": "—",
        "fit_confidence": "Low",
        "fit_reason": reason,
        "fit_evidence_used": ["Insufficient supplied evidence"],
        "decision_status": "Needs more information",
        "decision_reason": reason,
        "next_step": next_step,
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
        "parse_failed": parse_failed,
        "thin_payload": False,
        "failure_kind": PROCESSING_ERROR if parse_failed else VALIDATION_ERROR,
        "missing_fields": [],
    }


def _validation_error_result(payload: dict, missing: list[str]) -> dict:
    """State 1 — the submitted payload is genuinely missing required information."""
    reason = "Needs more information to analyse this item."
    result = _live_fallback_result(reason, parse_failed=False)
    result["failure_kind"] = VALIDATION_ERROR
    result["thin_payload"] = True
    result["parse_failed"] = False
    result["missing_fields"] = list(missing)
    result["next_step"] = "; ".join(missing) if missing else result["next_step"]
    result["decision_evidence_used"] = [f"Missing: {item}" for item in missing] or [
        "Insufficient supplied evidence"
    ]
    result["evidence_used"] = list(result["decision_evidence_used"])
    return _apply_item_identity(result, payload)


def _service_error_result(payload: dict | None = None) -> dict:
    """State 3 — authentication, network, rate limit, or Groq service failure."""
    result = _live_fallback_result(API_UNAVAILABLE_MESSAGE, parse_failed=False)
    result["decision_status"] = ""
    result["failure_kind"] = SERVICE_ERROR
    result["parse_failed"] = False
    result["thin_payload"] = False
    result["missing_fields"] = []
    result["next_step"] = "Please try again."
    result["fit_evidence_used"] = []
    result["decision_evidence_used"] = []
    result["evidence_used"] = []
    return _apply_item_identity(result, payload)


def _secret_missing_result(payload: dict | None = None) -> dict:
    result = _service_error_result(payload)
    result["failure_kind"] = NO_SECRET
    result["fit_reason"] = SECRET_MISSING_MESSAGE
    result["decision_reason"] = SECRET_MISSING_MESSAGE
    result["next_step"] = SECRET_MISSING_MESSAGE
    return result


def _processing_error_result(payload: dict | None = None) -> dict:
    """State 2 — Groq replied, but the output could not be parsed or validated."""
    result = _live_fallback_result(PARSE_FAILED_MESSAGE, parse_failed=True)
    result["decision_status"] = ""
    result["failure_kind"] = PROCESSING_ERROR
    result["parse_failed"] = True
    result["thin_payload"] = False
    result["missing_fields"] = []
    result["next_step"] = "Please try again."
    result["fit_evidence_used"] = []
    result["decision_evidence_used"] = []
    result["evidence_used"] = []
    return _apply_item_identity(result, payload)


def live_next_steps(payload: dict, result: dict) -> list[str]:
    """Shopper next steps for a Needs-more-information result.

    Only ask for fields that were not actually submitted.
    """
    kind = result.get("failure_kind")
    if kind in (SERVICE_ERROR, PROCESSING_ERROR, NO_SECRET) or result.get("parse_failed"):
        return ["Please try again"]
    fields = result.get("missing_fields")
    if fields:
        return list(fields)
    leftover = validate_custom_payload(dict(payload or {}))
    if leftover:
        return leftover
    extra = str(result.get("next_step") or "").strip()
    extra_l = extra.lower()
    asks_for_provided = (
        (_has_size_chart(payload) and "size chart" in extra_l)
        or (_has_fit_review_evidence(payload) and "review" in extra_l)
        or (
            (_has_body_measurement(payload) or _has_usual_size(payload))
            and ("measurement" in extra_l or "usual size" in extra_l)
        )
    )
    generic = "add a size chart, measurements, reviews"
    if extra and generic not in extra_l and not asks_for_provided:
        return [extra]
    return ["Edit your information or try the analysis again"]


def normalize_live_result(parsed: dict) -> dict:
    """Coerce model JSON into the live schema.

    Raises GroqParseError when JSON/schema is invalid.
    Does not convert API or schema failure into missing information.
    """
    errors = validate_live_schema(parsed)
    if errors:
        raise GroqParseError("schema validation failed")
    try:
        conf = _map_fit_confidence(parsed.get("fit_confidence"))
        status = _map_decision_status(
            _safe_str(parsed.get("decision_status") or parsed.get("buy_or_wait"))
        )
        fit_ev = _safe_str_list(parsed.get("fit_evidence_used"))
        dec_ev = _safe_str_list(
            parsed.get("decision_evidence_used") or parsed.get("evidence_used")
        )
        info = _safe_str_list(parsed.get("info_to_check"))[:3]
        if not fit_ev:
            fit_ev = ["No fit evidence listed by the model"]
        if not dec_ev:
            dec_ev = list(info) if info else ["No decision evidence listed by the model"]
        next_from_model = parsed.get("next_step")
        if next_from_model not in (None, ""):
            next_step = _safe_str(next_from_model)
        elif info:
            next_step = "; ".join(info)
        else:
            next_step = _safe_str(
                parsed.get("buy_wait_reason"),
                "Review the fit and decision panels, then decide.",
            )

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
                parsed.get("decision_reason") or parsed.get("buy_wait_reason"),
                "No decision reason returned from the supplied fields.",
            ),
            "next_step": next_step,
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
            "parse_failed": False,
            "thin_payload": False,
            "failure_kind": None,
            "missing_fields": [],
        }
    except GroqParseError:
        raise
    except Exception as exc:
        _log_adapter_error("Analysis response schema could not be processed", exc)
        raise GroqParseError("Analysis response schema could not be processed") from None


def _parse_occasion_timing(raw) -> int | None:
    blob = _norm(str(raw or ""))
    if not blob or blob in ("no date", "no specific occasion", "none", "no"):
        return None
    days = re.search(r"(\d+)\s*day", blob)
    if days:
        return int(days.group(1))
    weeks = re.search(r"(\d+)\s*week", blob)
    if weeks:
        return int(weeks.group(1)) * 7
    if "next week" in blob:
        return 7
    if "tomorrow" in blob:
        return 1
    lone = re.search(r"\b(\d+)\b", blob)
    if lone:
        n = int(lone.group(1))
        if 0 <= n <= 365:
            return n
    return None


def _parse_size_chart_text(raw) -> dict:
    """Deterministic parse of a pasted size chart into {size: {chest/waist}}."""
    if isinstance(raw, dict):
        out: dict = {}
        for key, dims in raw.items():
            if isinstance(dims, dict):
                out[str(key).upper()] = dims
        return out
    text = str(raw or "").strip()
    if not text:
        return {}
    tokens = list(re.finditer(r"\b(XXL|XL|XS|S|M|L)\b", text, flags=re.I))
    chart: dict = {}
    for i, match in enumerate(tokens):
        size = match.group(1).upper()
        end = tokens[i + 1].start() if i + 1 < len(tokens) else len(text)
        chunk = text[match.start() : end]
        dims: dict = {}
        chest = re.search(r"(?:chest|bust)\s*[:=]?\s*(\d+(?:\.\d+)?)", chunk, flags=re.I)
        waist = re.search(r"waist\s*[:=]?\s*(\d+(?:\.\d+)?)", chunk, flags=re.I)
        if chest:
            dims["chest"] = float(chest.group(1))
        if waist:
            dims["waist"] = float(waist.group(1))
        if not dims:
            number = re.search(r"(\d+(?:\.\d+)?)", chunk[match.end() - match.start() :])
            if number:
                dims["chest"] = float(number.group(1))
        if dims:
            chart[size] = dims
    return chart


def _review_snippets_from_payload(payload: dict) -> list[str]:
    raw = payload.get("reviews")
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[\n;]+", str(raw)) if part.strip()]


def _usual_size_from_payload(payload: dict) -> str:
    usual = str(payload.get("usual_size") or "").strip().upper()
    if usual in LETTER_SIZES or usual.isdigit():
        return usual
    match = re.search(
        r"usual\s+([A-Za-z0-9]+)", str(payload.get("size_info") or ""), flags=re.I
    )
    if match:
        token = match.group(1).upper()
        if token in LETTER_SIZES or token.isdigit():
            return token
    return "M"


def _item_from_custom_payload(payload: dict) -> dict:
    """Map submitted custom-form fields onto the deterministic engine item."""
    occasion_for = payload.get("occasion_for")
    has_occasion = occasion_for not in (None, "", "No specific occasion", "No")
    days = (
        _parse_occasion_timing(payload.get("occasion_timing")) if has_occasion else None
    )
    intended = ""
    if has_occasion:
        if occasion_for not in ("Yes", "yes"):
            intended = str(occasion_for)
        elif payload.get("why_saved"):
            intended = str(payload.get("why_saved"))
    chart_raw = payload.get("size_chart")
    return {
        "name": payload.get("product_name") or payload.get("product") or "Your item",
        "brand": payload.get("brand") or "",
        "category": payload.get("category") or "",
        "price": payload.get("price"),
        "size_chart": _parse_size_chart_text(chart_raw),
        "size_chart_submitted": bool(
            chart_raw if not isinstance(chart_raw, dict) else chart_raw
        ),
        "review_snippets": _review_snippets_from_payload(payload),
        "save_reason": payload.get("why_saved") or "",
        "intended_use": intended,
        "occasion_days_remaining": days,
        "occasion_timing": payload.get("occasion_timing"),
        "unresolved_questions": payload.get("unresolved_questions") or "",
        "comparison_status": payload.get("comparison_status") or "not_comparing",
        "intent_state": "active",
        "saved_days_ago": None,
        "stock_status": None,
        "usual_size": _usual_size_from_payload(payload),
        "chest": payload.get("chest"),
        "waist": payload.get("waist"),
    }


def _custom_fit_evidence(payload: dict, item: dict) -> list[str]:
    evidence: list[str] = []
    if item.get("size_chart_submitted") or item.get("size_chart"):
        evidence.append("Submitted size chart")
    usual = item.get("usual_size")
    if usual:
        evidence.append(f"Usual size {usual}")
    chest = item.get("chest")
    if chest:
        evidence.append(f"Chest measurement: {chest:g} in")
    waist = item.get("waist")
    if waist:
        evidence.append(f"Waist measurement: {waist:g} in")
    if item.get("review_snippets"):
        evidence.append("Submitted review snippets")
    return evidence or ["Submitted fit details"]


def compute_custom_analysis_fallback(payload: dict, *, cause: str | None = None) -> dict:
    """Deterministic two-panel result from the submitted payload. Not an LLM result.

    `cause` records why live analysis was skipped so the result page can say so
    above the panels. It never changes the fit or decision the rules produce.
    """
    missing = validate_custom_payload(dict(payload))
    if missing:
        return _validation_error_result(payload, missing)

    item = _item_from_custom_payload(payload)
    usual = str(item.get("usual_size") or "M")
    chest = item.get("chest")
    if chest is not None:
        try:
            chest = float(chest)
        except (TypeError, ValueError):
            chest = None
    waist = item.get("waist")
    if waist is not None:
        try:
            waist = float(waist)
        except (TypeError, ValueError):
            waist = None
    fit = compute_fit(item, usual, chest, waist)
    # Validation already passed — do not invent missing chart/reviews/size.
    decision = compute_next_action(item, fit, gaps=_blocking_check_questions(item))
    dec_ev = list(decision.get("evidence_used") or [])
    result = {
        "fit_recommendation": fit.get("fit_recommendation") or "—",
        "fit_confidence": fit.get("fit_confidence") or "Low",
        "fit_reason": fit.get("fit_reason") or "",
        "fit_evidence_used": _custom_fit_evidence(payload, item),
        "decision_status": decision.get("decision_status"),
        "decision_reason": decision.get("decision_reason") or "",
        "next_step": decision.get("next_step") or "",
        "decision_evidence_used": dec_ev,
        "evidence_used": dec_ev,
        "name": item.get("name") or "Your item",
        "brand": item.get("brand") or "",
        "category": item.get("category") or "Custom paste",
        "price": item.get("price"),
        "saved_days_ago": None,
        "stock_status": None,
        "review_snippets": item.get("review_snippets") or [],
        "is_live": False,
        "is_rule_fallback": True,
        "source_label": RULE_FALLBACK_LABEL,
        "parse_failed": False,
        "thin_payload": False,
        "failure_kind": RULE_FALLBACK,
        "fallback_cause": cause,
        "missing_fields": [],
    }
    result = _apply_item_identity(result, payload)
    result["is_live"] = False
    result["is_rule_fallback"] = True
    result["source_label"] = RULE_FALLBACK_LABEL
    result["failure_kind"] = RULE_FALLBACK
    result["fallback_cause"] = cause
    return result


def fallback_cause_message(result: dict) -> str:
    """Banner shown above rule-based panels. Empty when there is nothing to say."""
    cause = (result or {}).get("fallback_cause")
    if cause == SERVICE_ERROR:
        return API_UNAVAILABLE_MESSAGE
    if cause == NO_SECRET:
        return SECRET_MISSING_MESSAGE
    return ""


def analyse_custom_item(payload: dict, api_key: str | None) -> dict:
    """Validate the saved payload, then call Groq.

    Three distinct failure states, never collapsed into one another:
    validation_error (the payload really is incomplete), processing_error (the
    reply could not be parsed or validated), and service_error (auth, network,
    rate limit, or Groq outage). Only validation_error may tell the shopper
    that information is missing.
    """
    debug = _empty_debug(payload, key_detected=bool(api_key))
    missing = validate_custom_payload(payload)
    debug["payload_fields_present"] = payload_fields_present(payload)
    debug["validation_errors"] = list(missing)
    debug["groq_key_detected"] = bool(api_key)
    _record_debug(debug)
    if missing:
        return _validation_error_result(payload, missing)
    if not api_key:
        return compute_custom_analysis_fallback(payload, cause=NO_SECRET)
    try:
        t0 = time.perf_counter()
        parsed = call_groq(payload, api_key)
        debug["api_call_succeeded"] = True
        debug["json_parse_succeeded"] = True
        schema_errors = validate_live_schema(parsed)
        if schema_errors:
            debug["validation_errors"] = list(missing) + schema_errors
            _record_debug(debug)
            return _processing_error_result(payload)
        result = normalize_live_result(parsed)
        result["eval_seconds"] = round(time.perf_counter() - t0, 1)
        result["is_rule_fallback"] = False
        _record_debug(debug)
        return _apply_item_identity(result, payload)
    except GroqParseError as exc:
        debug["api_call_succeeded"] = True
        debug["json_parse_succeeded"] = False
        _record_debug(debug)
        _log_adapter_error("Custom analysis response could not be processed", exc)
        return _processing_error_result(payload)
    except GroqAPIError as exc:
        debug["api_call_succeeded"] = False
        debug["json_parse_succeeded"] = False
        _record_debug(debug)
        _log_adapter_error("Custom analysis API request failed", exc)
        return compute_custom_analysis_fallback(payload, cause=SERVICE_ERROR)
    except Exception as exc:
        debug["api_call_succeeded"] = False
        debug["json_parse_succeeded"] = False
        _record_debug(debug)
        _log_adapter_error("Custom analysis failed", exc)
        return compute_custom_analysis_fallback(payload, cause=SERVICE_ERROR)


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


def query_state_for(view: str, item: str | None = None) -> dict[str, str]:
    """Canonical in-app query string. Detail always includes item id."""
    chosen = str(view or "wishlist")
    if chosen not in VIEWS:
        chosen = "wishlist"
    if chosen == "detail":
        token = str(item or "").strip()
        if not token:
            return {"view": "wishlist"}
        return {"view": "detail", "item": token}
    return {"view": chosen}


def nav_to(view: str, item: str | None = None, **extra) -> None:
    """Same-tab navigation: set query params, keep session state, rerun.

    Internal pages use Streamlit buttons only. Markdown or HTML anchors would
    open a new browser tab and a new session.
    """
    if item in (None, "") and extra.get("item") not in (None, ""):
        item = extra.get("item")
    st.query_params.from_dict(query_state_for(view, item))
    st.rerun()


def nav_button(
    label: str,
    view: str,
    *,
    key: str,
    item: str | None = None,
    type: str = "secondary",
    use_container_width: bool = True,
) -> None:
    """Internal nav control. A Streamlit button, never a new-tab link."""
    if st.button(
        label,
        key=key,
        type=type,
        use_container_width=use_container_width,
    ):
        nav_to(view, item=item)


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
.wd-info-callout {
  background: #eaf1f8; border-radius: 8px; padding: 0.85rem 1rem;
  display: flex; gap: 0.75rem; align-items: flex-start;
  margin: 0.15rem 0 1rem; border-left: 3px solid #366091;
}
.wd-info-callout p {
  margin: 0; color: #315C8C; font-size: 14px; line-height: 22px;
}
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
    if result.get("failure_kind") in (SERVICE_ERROR, PROCESSING_ERROR):
        return result.get("fit_reason") or PARSE_FAILED_MESSAGE
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


_INTERNAL_EVIDENCE_FIELDS = (
    "comparison_status",
    "intent_state",
    "save_reason",
    "occasion_days_remaining",
    "fit_confidence",
    "fit_recommendation",
    "fit_reason",
    "intended_use",
    "saved_days_ago",
    "missing_or_open",
    "stock_status",
    "stock_is_simulated",
    "unresolved_questions",
    "why_saved",
)
_EVIDENCE_FIELD_ALIASES = {
    "comparison": "comparison_status",
    "intent": "intent_state",
    "occasion": "occasion_days_remaining",
    "timing": "occasion_days_remaining",
    "fit": "fit_confidence",
    "confidence": "fit_confidence",
    "size": "fit_recommendation",
    "use": "intended_use",
    "reason": "save_reason",
    "age": "saved_days_ago",
    "missing": "missing_or_open",
}
_INTERNAL_FIELD_RE = re.compile(
    r"\b("
    + "|".join(re.escape(name) for name in _INTERNAL_EVIDENCE_FIELDS)
    + r")\b",
    re.I,
)
_SNAKE_FIELD_RE = re.compile(r"\b[a-z]+_[a-z]+(?:_[a-z]+)*\s*:")


def _ctx_value(ctx: dict, *keys):
    for key in keys:
        value = ctx.get(key)
        if value not in (None, ""):
            return value
    return None


def _evidence_context(result, item_or_payload) -> dict:
    ctx: dict = {}
    for src in (item_or_payload, result):
        if not isinstance(src, dict):
            continue
        for key in (
            "comparison_status",
            "intent_state",
            "occasion_days_remaining",
            "occasion_timing",
            "save_reason",
            "why_saved",
            "intended_use",
            "saved_days_ago",
            "fit_confidence",
            "fit_recommendation",
            "fit_reason",
        ):
            value = src.get(key)
            if value not in (None, "") and ctx.get(key) in (None, ""):
                ctx[key] = value
    if ctx.get("save_reason") in (None, "") and ctx.get("why_saved") not in (None, ""):
        ctx["save_reason"] = ctx["why_saved"]
    if ctx.get("occasion_days_remaining") in (None, ""):
        days = _parse_occasion(ctx)
        if days is None:
            days = _parse_occasion_timing(ctx.get("occasion_timing"))
        if days is not None:
            ctx["occasion_days_remaining"] = days
    return ctx


def _is_shopper_safe(text: str) -> bool:
    blob = str(text or "").strip()
    if not blob:
        return False
    if _INTERNAL_FIELD_RE.search(blob):
        return False
    if _SNAKE_FIELD_RE.search(blob):
        return False
    lowered = _norm(blob)
    if re.search(r"\bcomparing\s*[•|,]\s*active\b", lowered):
        return False
    if lowered in ("comparing", "not_comparing", "active", "stale", "uncertain"):
        return False
    return True


def _comparison_phrase(value) -> str:
    if value in (None, ""):
        return ""
    if _is_comparing({"comparison_status": value}):
        return "You are comparing another shortlisted product."
    status = _norm(str(value))
    if status in ("not_comparing", "none", "no") or "not" in status:
        return "You are not comparing this with another shortlisted product."
    return ""


def _intent_phrase(value) -> str:
    token = _norm(str(value or ""))
    if token == "active":
        return "Your interest in this item is still active."
    if token == "stale":
        return (
            "This item has been saved for a long time and your current "
            "interest is uncertain."
        )
    if token == "uncertain":
        return "Your current interest in this item is uncertain."
    return ""


def _occasion_phrase(value, ctx: dict) -> str:
    days = _parse_occasion({"occasion_days_remaining": value})
    if days is None:
        days = _parse_occasion_timing(value)
    if days is None:
        days = _parse_occasion(ctx) or _parse_occasion_timing(ctx.get("occasion_timing"))
    if days is None:
        token = _norm(str(value or ""))
        if token in ("none", "(none)", "null"):
            return "There is no dated occasion for this item."
        return ""
    unit = "day" if days == 1 else "days"
    return f"You need this item in approximately {days} {unit}."


def _fit_confidence_phrase(value) -> str:
    token = _norm(str(value or ""))
    if token == "high":
        return "Available fit signals are consistent."
    if token == "medium":
        return "Available fit signals are reasonably consistent."
    if token == "low":
        return "Available fit signals are limited or inconsistent."
    return ""


def _days_saved_phrase(value) -> str:
    blob = str(value or "")
    match = re.search(r"-?\d+", blob)
    if not match:
        return ""
    days = int(match.group(0))
    unit = "day" if days == 1 else "days"
    return (
        f"This has been saved for {days} {unit}. "
        "That age is not a reason to buy."
    )


def _missing_info_phrase(value) -> str:
    blob = _norm(str(value or ""))
    if "size_chart" in blob or "size chart is missing" in blob:
        return "A size chart was not provided."
    cleaned = _INTERNAL_FIELD_RE.sub("", str(value or "")).strip(" :,-")
    return cleaned if _is_shopper_safe(cleaned) else ""


def _phrase_for_field(field: str, value, ctx: dict) -> str:
    kn = _norm(str(field or "")).replace(" ", "_")
    kn = _EVIDENCE_FIELD_ALIASES.get(kn, kn)
    if kn in ("comparison_status", "comparison"):
        raw = value if value not in (None, "") else _ctx_value(ctx, "comparison_status")
        return _comparison_phrase(raw)
    if kn == "intent_state":
        raw = value if value not in (None, "") else _ctx_value(ctx, "intent_state")
        return _intent_phrase(raw)
    if kn == "occasion_days_remaining":
        raw = value if value not in (None, "") else _ctx_value(
            ctx, "occasion_days_remaining", "occasion_timing"
        )
        return _occasion_phrase(raw, ctx)
    if kn == "fit_confidence":
        raw = value if value not in (None, "") else _ctx_value(ctx, "fit_confidence")
        return _fit_confidence_phrase(raw)
    if kn == "fit_recommendation":
        raw = value if value not in (None, "") else _ctx_value(ctx, "fit_recommendation")
        size = str(raw or "").strip()
        if not size or not _is_shopper_safe(size):
            return ""
        return f"Suggested size based on available information: {size}."
    if kn == "fit_reason":
        text = str(value or "").strip()
        return text if _is_shopper_safe(text) else ""
    if kn == "saved_days_ago":
        raw = value if value not in (None, "") else _ctx_value(ctx, "saved_days_ago")
        return _days_saved_phrase(raw)
    if kn == "save_reason":
        text = str(
            value if value not in (None, "") else _ctx_value(ctx, "save_reason", "why_saved") or ""
        ).strip()
        return text if _is_shopper_safe(text) else ""
    if kn == "intended_use":
        text = str(
            value if value not in (None, "") else _ctx_value(ctx, "intended_use") or ""
        ).strip()
        if not text or not _is_shopper_safe(text):
            return ""
        return f"You planned this for {text}."
    if kn == "missing_or_open":
        return _missing_info_phrase(value)
    return ""


def _phrase_for_value(value, ctx: dict) -> str:
    token = _norm(str(value or ""))
    if not token:
        return ""
    if token in ("comparing", "not_comparing") or token.startswith("compar"):
        return _comparison_phrase(value)
    if token in ("active", "stale", "uncertain"):
        return _intent_phrase(value)
    if token in ("high", "medium", "low"):
        return _fit_confidence_phrase(value)
    return ""


def _translate_evidence_row(row: str, ctx: dict | None = None) -> str:
    """Turn one internal evidence row into shopper-facing copy."""
    ctx = ctx or {}
    text = str(row or "").strip()
    if not text:
        return ""
    key, sep, val = text.partition(":")
    if sep:
        field = key.strip()
        value = val.strip()
        kn = _norm(field).replace(" ", "_")
        kn = _EVIDENCE_FIELD_ALIASES.get(kn, kn)
        phrase = _phrase_for_field(kn, value, ctx)
        if phrase:
            return phrase
        if "_" in field or kn in _INTERNAL_EVIDENCE_FIELDS:
            fallback = _phrase_for_value(value, ctx)
            if fallback:
                return fallback
            return value if _is_shopper_safe(value) else ""
        return text if _is_shopper_safe(text) else ""

    kn = _norm(text).replace(" ", "_")
    if kn in _EVIDENCE_FIELD_ALIASES or kn in _INTERNAL_EVIDENCE_FIELDS:
        field = _EVIDENCE_FIELD_ALIASES.get(kn, kn)
        return _phrase_for_field(field, None, ctx)
    phrase = _phrase_for_value(text, ctx)
    if phrase:
        return phrase
    if re.fullmatch(r"[A-Za-z]+(_[A-Za-z]+)+", text):
        return ""
    return text if _is_shopper_safe(text) else ""


def format_evidence_for_shopper(row: str, source: dict | None = None) -> str:
    """Turn engine evidence keys into short customer-facing copy."""
    return _translate_evidence_row(row, source or {})


def _format_evidence_list(rows, ctx: dict) -> list[str]:
    if not isinstance(rows, list):
        rows = [rows] if rows else []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        line = _translate_evidence_row(str(row), ctx)
        if not line or not _is_shopper_safe(line):
            continue
        key = _norm(line)
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _decision_evidence_rows(result) -> list:
    rows: list = []
    if isinstance(result, dict):
        raw = result.get("decision_evidence_used")
        if raw in (None, [], ""):
            raw = result.get("evidence_used")
        if isinstance(raw, list):
            rows = list(raw)
        elif raw:
            rows = [raw]
        extra = result.get("supporting_context") or []
        if isinstance(extra, list):
            rows.extend(extra)
    return rows


def format_decision_evidence(result, item_or_payload=None) -> list[str]:
    """Customer-facing decision evidence. Internal keys stay in Python only."""
    ctx = _evidence_context(result, item_or_payload)
    return _format_evidence_list(_decision_evidence_rows(result), ctx)


def compose_decision_based_on(result: dict) -> str:
    pretty = format_decision_evidence(result, result)[:4]
    if pretty:
        return " • ".join(pretty)
    return compose_why_line(result)


# ---------------------------------------------------------------------------
# Analyse-an-Item evidence — every line quotes a value the shopper supplied
# ---------------------------------------------------------------------------

_COUNT_WORDS = (
    "zero", "one", "two", "three", "four", "five", "six",
    "seven", "eight", "nine", "ten", "eleven", "twelve",
)
_BODY_PARTS = (
    "chest", "bust", "waist", "shoulder", "sleeve", "hip", "arm", "neck", "length",
)
# Each signal needs its own words to appear in the submitted reviews.
_REVIEW_SIGNALS = (
    (TRUE_SIZE_KEYS, "describes", "describe", "the fit as true to size"),
    (
        ("runs small", "run small", "sized small", "size up"),
        "reports", "report", "the fit runs small",
    ),
    (
        ("runs large", "run large", "sized large", "size down", "too baggy"),
        "reports", "report", "the fit runs large",
    ),
    (
        ("runs long", "little long", "bit long", "too long"),
        "notes", "note", "the length runs long",
    ),
    (
        ("runs short", "little short", "bit short", "too short"),
        "notes", "note", "the length runs short",
    ),
)
_NO_DATE_WORDS = ("no date", "none", "no", "no specific occasion", "not sure", "-")
_JSON_SHAPED_RE = re.compile(r"[{}\[\]]|\"\s*:")


def _count_word(count: int) -> str:
    return _COUNT_WORDS[count] if 0 <= count < len(_COUNT_WORDS) else str(count)


def _inches_phrase(value: float) -> str:
    return f"{value:g} inch" if value == 1 else f"{value:g} inches"


def _measure_value(raw) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _short_quote(text: str, limit: int = 80) -> str:
    blob = " ".join(str(text or "").split()).strip(" .;")
    return blob if len(blob) <= limit else blob[: limit - 1].rstrip() + "…"


def _review_subject(count: int) -> str:
    word = _count_word(max(1, count)).capitalize()
    return f"{word} review" if count == 1 else f"{word} reviews"


def _snug_review_line(snippets: list[str]) -> str:
    """Report a snug or tight fit, naming the body part only if a review does."""
    hits = [s for s in snippets if any(w in _norm(s) for w in ("snug", "tight"))]
    if not hits:
        return ""
    blob = _norm(hits[0])
    word = "snug" if "snug" in blob else "tight"
    qualifier = "slightly " if "slightly" in blob or "a little" in blob else ""
    part = next((p for p in _BODY_PARTS if p in blob), "")
    verb = "reports" if len(hits) == 1 else "report"
    return f"{_review_subject(len(hits))} {verb} a {qualifier}{word} {part or 'fit'}"


def _review_evidence_lines(payload: dict, limit: int = 3) -> list[str]:
    """Concise fit signals drawn from the review text the shopper pasted."""
    snippets = _review_snippets_from_payload(payload)
    if not snippets:
        return []
    lines: list[str] = []
    snug = _snug_review_line(snippets)
    if snug:
        lines.append(snug)
    for keys, singular, plural, tail in _REVIEW_SIGNALS:
        hits = [s for s in snippets if any(_keyword_hit(_norm(s), k) for k in keys)]
        if not hits:
            continue
        verb = singular if len(hits) == 1 else plural
        lines.append(f"{_review_subject(len(hits))} {verb} {tail}")
    if not lines:
        first = next((s for s in snippets if FIT_REVIEW_WORD_RE.search(_norm(s))), "")
        if first:
            lines.append(f'One review notes: "{_short_quote(first)}"')
    return lines[:limit]


def _chart_evidence_lines(payload: dict, result: dict) -> list[str]:
    """The chart row for the suggested size, or the shopper's usual size."""
    chart = _parse_size_chart_text(payload.get("size_chart"))
    if not chart:
        return []
    for raw in (result.get("fit_recommendation"), payload.get("usual_size")):
        size = str(raw or "").strip().upper()
        if not size or size not in chart:
            continue
        dim, value = _chart_dim(chart, size)
        if value is None:
            continue
        measure = "chart measurement" if dim in ("chest", "bust") else f"chart {dim}"
        return [f"Size {size} {measure}: {_inches_phrase(value)}"]
    return []


def _measurement_evidence_lines(payload: dict, keys: tuple[str, ...]) -> list[str]:
    lines = []
    for key in keys:
        value = _measure_value(payload.get(key))
        if value is not None:
            lines.append(f"Your {key} measurement: {_inches_phrase(value)}")
    return lines


def _occasion_evidence_lines(payload: dict) -> list[str]:
    raw = str(payload.get("occasion_timing") or "").strip()
    if not raw or _norm(raw) in _NO_DATE_WORDS:
        return []
    days = _parse_occasion_timing(raw)
    if days is not None:
        unit = "day" if days == 1 else "days"
        return [f"The item is needed in {_count_word(days)} {unit}"]
    return [f"The item is needed {_short_quote(raw)}"] if _is_shopper_safe(raw) else []


def _price_evidence_lines(payload: dict) -> list[str]:
    raw = str(payload.get("price") or "").strip()
    if not raw:
        return []
    digits = re.sub(r"[^\d.]", "", raw)
    try:
        amount = f"₹{int(float(digits)):,}"
    except ValueError:
        return []
    return [f"The price you entered is {amount}"]


def _evidence_category(row: str) -> str:
    """Which supplied value an evidence label refers to, or '' when unclear."""
    blob = _norm(row)
    if not blob:
        return ""
    if "chart" in blob:
        return "chart"
    if "review" in blob or "feedback" in blob or "customer" in blob:
        return "reviews"
    if "usual" in blob:
        return "usual_size"
    chest = "chest" in blob or "bust" in blob
    waist = "waist" in blob
    if chest and waist:
        return "measurements"
    if chest:
        return "chest"
    if waist:
        return "waist"
    if "measurement" in blob or "measure" in blob or "body" in blob:
        return "measurements"
    if any(w in blob for w in ("occasion", "timing", "timeline", "deadline", "needed by")):
        return "occasion"
    if "price" in blob or "budget" in blob or "cost" in blob:
        return "price"
    if "availability" in blob or "stock" in blob or "inventory" in blob:
        return "availability"
    return ""


def _supplied_evidence_lines(category: str, payload: dict, result: dict) -> list[str]:
    """Evidence sentences for one category. Empty when the value was not supplied."""
    if category == "chest":
        return _measurement_evidence_lines(payload, ("chest",))
    if category == "waist":
        return _measurement_evidence_lines(payload, ("waist",))
    if category == "measurements":
        return _measurement_evidence_lines(payload, ("chest", "waist"))
    if category == "chart":
        return _chart_evidence_lines(payload, result)
    if category == "reviews":
        return _review_evidence_lines(payload)
    if category == "usual_size":
        size = str(payload.get("usual_size") or "").strip().upper()
        return [f"You usually wear size {size}"] if size else []
    if category == "occasion":
        return _occasion_evidence_lines(payload)
    if category == "price":
        return _price_evidence_lines(payload)
    if category == "availability":
        note = str(payload.get("availability") or "").strip()
        if not note:
            return []
        return [
            f"You noted: {_short_quote(note)}. Availability is treated as "
            "simulated, never verified live stock"
        ]
    return []


def _reports_an_absence(row: str) -> bool:
    """Rows about what is missing keep their existing wording."""
    key, sep, _ = str(row).partition(":")
    token = _norm(key if sep else row).replace(" ", "_")
    if _EVIDENCE_FIELD_ALIASES.get(token, token) == "missing_or_open":
        return True
    return bool(
        re.search(r"\b(missing|not provided|unavailable|absent|no evidence)\b", row, re.I)
    )


def custom_evidence_lines(rows, result: dict, payload: dict) -> list[str]:
    """Rewrite evidence labels as concise lines quoting the supplied values.

    A cited label is dropped when the shopper never supplied that value, so a
    line can restate the submitted information but never invent it.
    """
    ctx = _evidence_context(result, payload)
    supplied = dict(payload or {})
    out: list[str] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else ([rows] if rows else []):
        text = str(row or "").strip()
        if not text:
            continue
        lines: list[str] = []
        if not _reports_an_absence(text):
            category = _evidence_category(text)
            if category:
                lines = _supplied_evidence_lines(category, supplied, result or {})
                if not lines:
                    continue
        if not lines:
            if _JSON_SHAPED_RE.search(text):
                continue
            translated = _translate_evidence_row(text, ctx)
            lines = [translated] if translated else []
        for line in lines:
            if not _is_shopper_safe(line):
                continue
            key = _norm(line)
            if key in seen:
                continue
            seen.add(key)
            out.append(line)
    return out


def custom_fit_evidence(result: dict, payload: dict) -> list[str]:
    rows = (result or {}).get("fit_evidence_used") or []
    return custom_evidence_lines(rows, result, payload)


def custom_decision_evidence(result: dict, payload: dict) -> list[str]:
    return custom_evidence_lines(_decision_evidence_rows(result), result, payload)


def render_chrome(active: str) -> None:
    if active == "detail":
        top, _ = st.columns([1.2, 2.2])
        with top:
            nav_button(
                "Back to wishlist",
                "wishlist",
                key="chrome_detail_back",
            )
        md(
            f"""
<div class="wd-top">
  <div class="wd-compact">
    <span class="wd-title">Item Assessment Detail</span>
    <div class="wd-brand-right">
      <span class="wd-ai">{icon("auto_awesome", 13)} AI-assisted</span>
      <div class="wd-avatar">{icon("person", 18)}</div>
    </div>
  </div>
</div>
            """
        )
        return

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
  <div class="wd-proto">
    {icon("info", 15)}
    <span>{html.escape(PROTO_BANNER)}</span>
  </div>
</div>
        """
    )
    wish_type = "primary" if active in ("wishlist",) else "secondary"
    analyse_type = "primary" if active in ("analyse", "live_result") else "secondary"
    c_wish, c_analyse = st.columns(2)
    with c_wish:
        nav_button(
            "Sample Wishlist",
            "wishlist",
            type=wish_type,
            key="nav_wishlist",
        )
    with c_analyse:
        nav_button(
            "Analyse an Item",
            "analyse",
            type=analyse_type,
            key="nav_analyse",
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


def _inches_label(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:g} in"


def _size_with_inches(size: str | None, inches: float | None) -> str:
    token = str(size or "").strip()
    if not token:
        return "—"
    if inches is None:
        return token
    return f"{token} — {_inches_label(inches)}"


def measurement_evidence_rows(
    item: dict,
    usual: str,
    chest: float | None,
    waist: float | None,
) -> list[tuple[str, str]]:
    """Plain-text measurement comparison for the detail page. No HTML."""
    chart = item.get("size_chart") or {}
    rec = str(item.get("fit_recommendation") or "").strip()
    has_chest = any(
        isinstance(dims, dict) and any(key in dims for key in ("chest", "bust"))
        for dims in chart.values()
    )
    has_waist = any(
        isinstance(dims, dict) and "waist" in dims for dims in chart.values()
    )
    if has_chest and chest is not None:
        closest_size, _diff, _dim = _closest_chart_size(chart, chest, None)
        profile_val = chest
    elif has_waist and waist is not None:
        closest_size, _diff, _dim = _closest_chart_size(chart, None, waist)
        profile_val = waist
    else:
        closest_size, _diff, closest_dim = _closest_chart_size(chart, chest, waist)
        if closest_dim == "waist":
            profile_val = waist if waist is not None else chest
        else:
            profile_val = chest if chest is not None else waist
    if not closest_size:
        mapped = _usual_on_chart(usual, chart) if usual else ""
        closest_size = mapped or None
    closest_val = _chart_dim(chart, closest_size)[1] if closest_size else None
    rec_val = _chart_dim(chart, rec)[1] if rec else None
    return [
        ("Your profile", _inches_label(profile_val)),
        ("Closest chart size", _size_with_inches(closest_size, closest_val)),
        ("Suggested size", _size_with_inches(rec, rec_val)),
    ]


def render_measurement_evidence(rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    with st.container():
        cols = st.columns(3)
        for col, (label, value) in zip(cols, rows):
            with col:
                st.caption(label)
                st.markdown(value)


def render_plain_bullets(items: list, *, empty: str | None = None) -> None:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        if empty:
            st.caption(empty)
        return
    st.markdown("\n".join(f"- {item}" for item in cleaned))


def render_item_card(
    row: dict, usual: str, chest: float | None, waist: float | None
) -> None:
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
        """
    )
    raw_id = str(row.get("id") or "item")
    f1, f2 = st.columns(2)
    with f1:
        nav_button(
            "Update context",
            "detail",
            item=raw_id,
            key=f"upd_{raw_id}",
        )
    with f2:
        nav_button(
            "View evidence",
            "detail",
            item=raw_id,
            type="primary",
            key=f"ev_{raw_id}",
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
    _clear_custom_analysis(clear_form=True)


def _clear_custom_analysis(*, clear_form: bool) -> None:
    st.session_state.pop("custom_analysis_result", None)
    st.session_state.pop("live_result", None)
    st.session_state.pop("live_error", None)
    if clear_form:
        st.session_state.pop("custom_analysis_debug", None)
        st.session_state.pop("custom_analysis_payload", None)
        st.session_state.pop("analyse_payload", None)
        st.session_state.analyse_nonce = st.session_state.get("analyse_nonce", 0) + 1


def _saved_custom_payload() -> dict:
    payload = st.session_state.get("custom_analysis_payload")
    if isinstance(payload, dict):
        return payload
    legacy = st.session_state.get("analyse_payload")
    return legacy if isinstance(legacy, dict) else {}


def retry_saved_analysis() -> None:
    """Re-run analysis on the stored payload without leaving the result page.

    The analyse form is never reopened or rebuilt, so a retry cannot lose
    values the shopper already submitted.
    """
    payload = _saved_custom_payload()
    if not payload:
        st.session_state["custom_analysis_result"] = _validation_error_result(
            {}, validate_custom_payload({})
        )
        st.session_state.pop("live_result", None)
        st.rerun()
        return
    try:
        result = analyse_custom_item(payload, get_groq_api_key())
    except Exception as exc:
        _log_adapter_error("Retry analysis failed", exc)
        result = compute_custom_analysis_fallback(payload, cause=SERVICE_ERROR)
    st.session_state["custom_analysis_result"] = result
    st.session_state.pop("live_result", None)
    st.rerun()


def edit_saved_analysis() -> None:
    """Return to the analyse form with every submitted value restored.

    Routing reads the `view` query parameter, so nav_to sets that and reruns.
    Writing a `view` key into session state would leave the URL on the result
    page and rerun straight back into it.
    """
    payload = _saved_custom_payload()
    restore_custom_form(payload)
    st.session_state.pop("custom_analysis_result", None)
    st.session_state.pop("live_result", None)
    nav_to("analyse")


def _saved_custom_result() -> dict | None:
    result = st.session_state.get("custom_analysis_result")
    if isinstance(result, dict):
        return result
    legacy = st.session_state.get("live_result")
    return legacy if isinstance(legacy, dict) else None


def _custom_form_values(payload: dict, nonce: int) -> dict:
    """Analyse-form widget values that match a saved payload."""
    unsure_raw = payload.get("unresolved_questions")
    if isinstance(unsure_raw, str) and unsure_raw:
        chips = [c.strip() for c in unsure_raw.split(",") if c.strip() in UNCERTAINTY_CHIPS]
    elif isinstance(unsure_raw, list):
        chips = [c for c in unsure_raw if c in UNCERTAINTY_CHIPS]
    else:
        chips = []
    occasion_for = payload.get("occasion_for")
    values = {
        f"ca_prod_name_{nonce}": payload.get("product_name") or "",
        f"ca_brand_{nonce}": payload.get("brand") or "",
        f"ca_price_{nonce}": payload.get("price") or "",
        f"ca_size_chart_{nonce}": payload.get("size_chart") or "",
        f"ca_reviews_{nonce}": payload.get("reviews") or "",
        f"ca_availability_{nonce}": payload.get("availability") or "",
        f"ca_chest_{nonce}": float(payload["chest"]) if payload.get("chest") else 0.0,
        f"ca_waist_{nonce}": float(payload["waist"]) if payload.get("waist") else 0.0,
        f"ca_save_reason_{nonce}": payload.get("why_saved") or "",
        f"ca_occasion_{nonce}": (
            "Yes" if occasion_for not in (None, "No specific occasion") else "No"
        ),
        f"ca_timeline_{nonce}": payload.get("occasion_timing") or "",
        f"ca_unsure_{nonce}": chips,
        f"ca_comparing_{nonce}": (
            "Yes" if payload.get("comparison_status") == "comparing" else "No"
        ),
        f"ca_extra_{nonce}": payload.get("extra_context") or "",
    }
    if payload.get("category") in ANALYSE_CATEGORIES:
        values[f"ca_category_{nonce}"] = payload["category"]
    if payload.get("usual_size") in LETTER_SIZES:
        values[f"ca_usual_{nonce}"] = payload["usual_size"]
    return values


def _ensure_custom_form_state(nonce: int) -> None:
    """Seed untouched form widgets from the saved payload after reruns."""
    for key, value in _custom_form_values(_saved_custom_payload(), nonce).items():
        if key not in st.session_state:
            st.session_state[key] = value


def restore_custom_form(payload: dict) -> None:
    """Write a submitted payload back over the analyse form widgets.

    Every widget key carries the current analyse nonce, so the nonce is read
    from session state rather than hard-coded. Unlike seeding, this overwrites
    values Streamlit dropped while the shopper was on the result page, so
    measurements never come back as zero.
    """
    nonce = st.session_state.get("analyse_nonce", 0)
    for key, value in _custom_form_values(dict(payload or {}), nonce).items():
        st.session_state[key] = value


def example_analyse_payload() -> dict:
    """Realistic prototype payload for the analyse form. Not a live catalogue item."""
    return {
        "product_name": "Women Solid A-Line Midi Dress",
        "brand": "AND",
        "category": "Dresses & Jumpsuits",
        "price": "2499",
        "size_chart": (
            "S: chest 34, waist 28, length 46\n"
            "M: chest 36, waist 30, length 47\n"
            "L: chest 38, waist 32, length 48\n"
            "XL: chest 40, waist 34, length 49"
        ),
        "reviews": (
            "True to size. Zipper sits well; I didn't need to size up.\n"
            "Lining is good quality. Waist nips in exactly where it should in M."
        ),
        "availability": None,
        "usual_size": "M",
        "chest": 36.0,
        "waist": 30.0,
        "why_saved": (
            "Need a midi for a cousin's wedding next week; already pictured "
            "wearing this."
        ),
        "occasion_for": "Yes",
        "occasion_timing": "9 days",
        "unresolved_questions": None,
        "comparison_status": "not_comparing",
        "extra_context": None,
    }


def load_example_analyse_form() -> None:
    """Prefill analyse widgets from the example payload. Does not submit."""
    restore_custom_form(example_analyse_payload())


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
            nav_to("wishlist")
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
    snippets = row.get("review_snippets") or []
    measure_rows = measurement_evidence_rows(row, str(usual), chest, waist)
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
</div>
        """
    )
    st.caption("Evidence used")
    render_measurement_evidence(measure_rows)
    if snippets:
        st.caption("Simulated review snippets")
        for snippet in snippets[:3]:
            st.markdown(f"“{snippet}”")
    st.caption(f"Fit note: {FIT_NOTE}")
    md(
        f"""
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
  </div>
</div>
        """
    )
    st.caption("Based on")
    render_plain_bullets(format_decision_evidence(row, row)[:6])
    nav_button(
        "Change my answers",
        "wishlist",
        key="detail_change",
    )
    with st.expander("View sizing chart details"):
        chart = row.get("size_chart") or {}
        if not chart:
            st.caption("No size chart on this sample item.")
        else:
            for size, dims in chart.items():
                if isinstance(dims, dict):
                    parts = ", ".join(f"{key} {val}" for key, val in dims.items())
                else:
                    parts = str(dims)
                st.markdown(f"**{size}** — {parts}")
    render_how_it_works()


def render_adapter_debug() -> None:
    """Development-only diagnostics. Hidden when DEBUG_MODE is False."""
    if not DEBUG_MODE:
        return
    dbg = {}
    try:
        dbg = dict(st.session_state.get("custom_analysis_debug") or {})
    except Exception:
        dbg = {}
    present = dbg.get("payload_fields_present")
    if not isinstance(present, dict):
        present = payload_fields_present(_saved_custom_payload())
    errors = dbg.get("validation_errors")
    if not isinstance(errors, list):
        errors = []
    key_detected = dbg.get("groq_key_detected")
    if key_detected is None:
        key_detected = groq_key_detected()
    with st.expander("Developer diagnostics", expanded=True):
        st.caption("Booleans and error codes only. No personal inputs. No API key.")
        st.write("Payload fields present")
        st.json({key: bool(present.get(key)) for key in CUSTOM_PAYLOAD_FIELDS})
        st.write("Validation errors:", [str(item) for item in errors])
        st.write("Groq key detected:", bool(key_detected))
        st.write("API call succeeded:", bool(dbg.get("api_call_succeeded")))
        st.write("JSON parsing succeeded:", bool(dbg.get("json_parse_succeeded")))


def render_analyse_page(api_key: str | None) -> None:
    nonce = st.session_state.get("analyse_nonce", 0)
    _ensure_custom_form_state(nonce)
    if not api_key:
        st.warning(SECRET_MISSING_MESSAGE)
    render_adapter_debug()
    md(
        f"""
<div class="wd-kicker">{icon("fact_check", 14)} Structured Evaluation</div>
<h1 class="wd-h1 lg">Analyse a wishlisted item</h1>
        """
    )
    md(
        f"""
<div class="wd-info-callout">
  {icon("info", 18)}
  <p>{html.escape(ANALYSE_PROTOTYPE_CALLOUT)}</p>
</div>
        """
    )
    md(
        "<p class=\"wd-lead\">Add the information you already have. "
        "The assistant will not invent missing product details.</p>"
    )
    load_col, _ = st.columns([1, 2])
    with load_col:
        if st.button(
            "Load an example item",
            type="secondary",
            use_container_width=True,
            key=f"load_example_{nonce}",
        ):
            load_example_analyse_form()
    md(
        f"""
<div class="wd-card xl" style="margin-bottom:0.35rem">
  <div class="wd-section-head">
    <div class="wd-num">1</div>
    <div>
      <div class="wd-name" style="margin:0">Product evidence — auto-filled in the integrated experience</div>
      <p class="wd-muted" style="margin:0">Enter or load details here to test the assistant</p>
    </div>
  </div>
</div>
        """
    )
    with st.form(f"analyse_form_{nonce}", clear_on_submit=False):
        prod_name = st.text_input(
            "Product Name — required",
            placeholder="e.g. Cotton Relaxed Cuban Collar Shirt",
            key=f"ca_prod_name_{nonce}",
        )
        c1, c2 = st.columns(2)
        with c1:
            brand = st.text_input(
                "Brand (optional)",
                placeholder="e.g. Netplay, Marks & Spencer",
                key=f"ca_brand_{nonce}",
            )
        with c2:
            category = st.selectbox(
                "Category — required",
                ANALYSE_CATEGORIES,
                index=None,
                placeholder="Select category",
                key=f"ca_category_{nonce}",
            )
        price = st.text_input(
            "Current Price — optional",
            placeholder="1899",
            key=f"ca_price_{nonce}",
        )
        size_chart = st.text_area(
            "Size Chart — optional, improves confidence",
            placeholder="Paste measurement table or key sizing specs e.g. M: Chest 38, L: Chest 40...",
            height=80,
            key=f"ca_size_chart_{nonce}",
        )
        reviews = st.text_area(
            "Review Snippets — optional, improves confidence",
            placeholder="Paste relevant review comments mentioning fit, cut, fabric, or sizing...",
            height=80,
            key=f"ca_reviews_{nonce}",
        )
        availability = st.text_input(
            "Availability Notes — optional",
            placeholder="e.g. Only size L was listed in stock this morning",
            key=f"ca_availability_{nonce}",
        )
        st.caption(
            "Only enter availability notes for reference. The assistant will "
            "treat any availability as simulated and will never consider it "
            "verified live inventory."
        )

        st.caption("2 — Your decision context: baseline fit, why you saved it, and what is still uncertain.")
        s1, s2, s3 = st.columns(3)
        with s1:
            usual = st.selectbox(
                "Usual Size — required",
                LETTER_SIZES,
                index=None,
                placeholder="Size",
                key=f"ca_usual_{nonce}",
            )
        with s2:
            chest_in = st.number_input(
                "Chest/Bust — optional, improves confidence",
                min_value=0.0,
                max_value=60.0,
                step=0.5,
                help="Inches",
                key=f"ca_chest_{nonce}",
            )
        with s3:
            waist_in = st.number_input(
                "Waist — optional, improves confidence",
                min_value=0.0,
                max_value=60.0,
                step=0.5,
                help="Inches",
                key=f"ca_waist_{nonce}",
            )
        save_reason = st.text_area(
            "Why did you save this item?",
            placeholder="e.g. Trying to replace a faded linen shirt, loved the neutral shade...",
            height=70,
            key=f"ca_save_reason_{nonce}",
        )
        o1, o2 = st.columns(2)
        with o1:
            occasion = st.radio(
                "Is it for a particular occasion?",
                ["No", "Yes"],
                horizontal=True,
                key=f"ca_occasion_{nonce}",
            )
        with o2:
            timeline = st.text_input(
                "When do you need it? (optional)",
                placeholder="e.g. 10 days, next week, or no date",
                key=f"ca_timeline_{nonce}",
            )
        unsure = st.multiselect(
            "What are you still unsure about?",
            UNCERTAINTY_CHIPS,
            help="Select all areas you want evaluated directly",
            key=f"ca_unsure_{nonce}",
        )
        comparing = st.radio(
            "Are you comparing another product?",
            ["No", "Yes"],
            horizontal=True,
            key=f"ca_comparing_{nonce}",
        )
        extra = st.text_area(
            "Additional context (optional)",
            placeholder="Any specific laundry concerns, fabric sensitivity, or matching pieces already in wardrobe...",
            height=70,
            key=f"ca_extra_{nonce}",
        )
        st.info(
            "If essential information is missing, the assistant will ask you to "
            "verify it instead of making a confident recommendation. "
            + FIT_NOTE
        )
        submitted = st.form_submit_button(
            "Analyse this item",
            type="primary",
            use_container_width=True,
            key=f"ca_submit_{nonce}",
        )

    c_clear, _ = st.columns([1, 2])
    with c_clear:
        if st.button("Clear form", use_container_width=True, key=f"clear_analyse_{nonce}"):
            _clear_custom_analysis(clear_form=True)
            nav_to("analyse")

    if not submitted:
        return

    payload = build_custom_analysis_payload(
        prod_name=prod_name,
        brand=brand,
        category=category,
        price=price,
        size_chart=size_chart,
        reviews=reviews,
        availability=availability,
        usual=usual,
        chest_in=chest_in,
        waist_in=waist_in,
        save_reason=save_reason,
        occasion=occasion,
        timeline=timeline,
        unsure=unsure,
        comparing=comparing,
        extra=extra,
    )
    st.session_state["custom_analysis_payload"] = payload
    missing = validate_custom_payload(st.session_state["custom_analysis_payload"])
    _record_debug(
        {
            **_empty_debug(
                st.session_state["custom_analysis_payload"],
                key_detected=bool(api_key),
            ),
            "validation_errors": list(missing),
        }
    )
    if missing:
        result = _validation_error_result(
            st.session_state["custom_analysis_payload"], missing
        )
        st.session_state["custom_analysis_result"] = result
        nav_to("live_result")
        return
    try:
        result = analyse_custom_item(
            st.session_state["custom_analysis_payload"], api_key
        )
    except Exception as exc:
        _log_adapter_error("Custom analysis failed", exc)
        result = compute_custom_analysis_fallback(
            st.session_state["custom_analysis_payload"], cause=SERVICE_ERROR
        )
    st.session_state["custom_analysis_result"] = result
    nav_to("live_result")


def _render_live_notice_panels(
    *,
    headline: str,
    lead: str,
    panel2_badge: str,
    panel2_lead: str,
    steps: list[str],
) -> None:
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
    <div class="wd-h1" style="margin:4px 0 0">{html.escape(headline)}</div>
  </div>
  <p class="wd-lead">{html.escape(lead)}</p>
  <div class="wd-fit-note"><strong style="color:#1c1b1b">Fit note:</strong> {html.escape(FIT_NOTE)}</div>
</div>
<div class="wd-card xl">
  <div class="wd-panel-top">
    <div style="display:flex;align-items:center;gap:6px">
      {icon("flag_circle", 20)}
      <span class="wd-name" style="margin:0">Panel 2 — Buy or Wait?</span>
    </div>
    {detail_badge(panel2_badge, "#EEF0F3", "#596273")}
  </div>
  <p class="wd-lead">{html.escape(panel2_lead)}</p>
</div>
        """
    )
    st.caption("Concrete Next Steps")
    render_plain_bullets(steps)


def render_live_result_page() -> None:
    render_adapter_debug()
    result = _saved_custom_result()
    if not result:
        nav_to("analyse")
        return
    payload = _saved_custom_payload()
    kind = result.get("failure_kind")

    if kind in (SERVICE_ERROR, NO_SECRET):
        message = (
            SECRET_MISSING_MESSAGE if kind == NO_SECRET else API_UNAVAILABLE_MESSAGE
        )
        _render_live_notice_panels(
            headline=message,
            lead=message,
            panel2_badge="Try again",
            panel2_lead=message,
            steps=["Please try again"],
        )
        if kind == SERVICE_ERROR and st.button(
            "Retry analysis", type="primary", use_container_width=True, key="retry_service"
        ):
            retry_saved_analysis()
        if st.button(
            "Edit my information",
            type="secondary" if kind == SERVICE_ERROR else "primary",
            use_container_width=True,
            key="edit_service",
        ):
            edit_saved_analysis()
        return

    if kind == PROCESSING_ERROR:
        _render_live_notice_panels(
            headline=PARSE_FAILED_MESSAGE,
            lead=PARSE_FAILED_MESSAGE,
            panel2_badge="Try again",
            panel2_lead=PARSE_FAILED_MESSAGE,
            steps=["Please try again"],
        )
        if st.button(
            "Retry analysis", type="primary", use_container_width=True, key="retry_processing"
        ):
            retry_saved_analysis()
        if st.button(
            "Edit my information",
            use_container_width=True,
            key="edit_processing",
        ):
            edit_saved_analysis()
        return

    status = verdict_kind(result)
    conf = result.get("fit_confidence") or "Low"
    insufficient = (
        not result.get("is_rule_fallback")
        and (status == "Needs more information" or kind == VALIDATION_ERROR)
    )

    if insufficient:
        adds = live_next_steps(payload, result)
        _render_live_notice_panels(
            headline="Insufficient information to suggest size",
            lead=compose_why_line(result) or (result.get("next_step") or ""),
            panel2_badge="Needs more information",
            panel2_lead=(
                "Wait before buying until essential sizing or customer feedback "
                "signals can be verified."
            ),
            steps=adds,
        )
        cta = (
            "Provide missing item details"
            if any(
                "product name" in s.lower()
                or "category" in s.lower()
                or "usual size" in s.lower()
                or "fit evidence" in s.lower()
                or s.startswith("Add ")
                or s.startswith("Provide ")
                for s in adds
            )
            else "Edit my information"
        )
        if st.button(
            cta, type="primary", use_container_width=True, key="edit_insufficient"
        ):
            edit_saved_analysis()
        st.caption("The assistant will not invent product details you did not provide.")
        return

    cause_message = fallback_cause_message(result)
    if cause_message:
        st.warning(cause_message)

    name = result.get("name") or payload.get("product_name") or "Your item"
    brand = result.get("brand") or payload.get("brand") or ""
    category = result.get("category") or payload.get("category") or ""
    price = result.get("price") or payload.get("price") or ""
    subtitle_bits = [x for x in (name, brand, category, f"₹{price}" if price else "") if x]
    elapsed = result.get("eval_seconds")
    if result.get("is_rule_fallback"):
        elapsed_l = RULE_FALLBACK_LABEL
        ready_label = RULE_FALLBACK_LABEL
        ready_bg, ready_fg = "#EEF0F3", "#596273"
    else:
        elapsed_l = f"Evaluated in {elapsed}s" if elapsed is not None else "Analysis ready"
        ready_label = "Analysis ready"
        ready_bg, ready_fg = "#a8f2ce", "#002115"
    fit_ev = result.get("fit_evidence_used") or []
    fit_bg, fit_fg = DETAIL_FIT_BADGE.get(conf, DETAIL_FIT_BADGE["Medium"])
    dec_bg, dec_fg = DETAIL_DECISION_BADGE.get(
        status, DETAIL_DECISION_BADGE["Check one thing first"]
    )
    md(
        f"""
<div class="wd-card xl">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
    <span class="wd-badge" style="background:{ready_bg};color:{ready_fg}">{icon("check_circle", 14)} {html.escape(ready_label)}</span>
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
</div>
        """
    )
    st.caption("Based on")
    render_plain_bullets(
        custom_fit_evidence(result, payload),
        empty="No fit evidence listed",
    )
    md(
        f"""
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
</div>
        """
    )
    st.caption("Based on")
    render_plain_bullets(custom_decision_evidence(result, payload))
    show_retry = result.get("fallback_cause") == SERVICE_ERROR
    if show_retry and st.button(
        "Retry analysis", type="primary", use_container_width=True, key="retry_fallback"
    ):
        retry_saved_analysis()
    if st.button("Edit my information", use_container_width=True, key="edit_result"):
        edit_saved_analysis()
    if st.button(
        "Analyse another item",
        type="secondary" if show_retry else "primary",
        use_container_width=True,
        key="analyse_another",
    ):
        _clear_custom_analysis(clear_form=True)
        nav_to("analyse")
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
