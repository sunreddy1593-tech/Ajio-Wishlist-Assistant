"""Wishlist Decision Assistant — standalone Streamlit MVP.

Demo mode is fully offline (seeded JSON + deterministic rules).
Live mode makes one Groq chat call when a key is present in st.secrets.
"""

from __future__ import annotations

import html
import json
import re
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
SYSTEM_PROMPT = (
    "You are a fashion purchase advisor for urban working professionals. "
    "They already saved this item; your job is to resolve fit doubt and whether "
    "to buy now or wait. Do not offer discounts, coupons, or price-cut advice. "
    "Respond with ONLY valid JSON — no markdown, no code fences, no extra text. "
    "Use this exact schema: "
    '{"fit_recommendation": string, '
    '"fit_confidence": "High" | "Medium" | "Low", '
    '"fit_reason": string, '
    '"buy_or_wait": "Buy now" | "Wait" | "Needs more info", '
    '"buy_wait_reason": string, '
    '"info_to_check": [string]}'
)

CONF_COLORS = {"High": "#0f7b3c", "Medium": "#b45309", "Low": "#b42318"}

RESEARCH_INSIGHT = (
    "From prior research (not a live count): across shoppers like you, fit "
    "uncertainty and “waiting for the right moment” are the top reasons "
    "saved items don’t convert."
)

VERDICT_STYLES = {
    "buy": ("✅ Buy now", "#14532d", "#f0fdf4", "#86efac"),
    "wait": ("⏳ Worth waiting", "#92400e", "#fffbeb", "#fcd34d"),
    "check": ("⚠️ Check fit first", "#9a3412", "#fff7ed", "#fdba74"),
}


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


def compute_buy_or_wait(
    item: dict,
    fit: dict,
) -> dict:
    days = int(item.get("saved_days_ago") or 0)
    stock = str(item.get("stock_status") or "in_stock")
    conf = fit["fit_confidence"]

    if conf == "Low":
        return {
            "buy_or_wait": "Wait",
            "buy_wait_reason": "Wait — fit is uncertain, check reviews",
        }

    if stock == "low_stock" and conf in ("High", "Medium"):
        return {
            "buy_or_wait": "Buy now",
            "buy_wait_reason": (
                "Buy now — your size is low in stock and fit looks right"
            ),
        }

    if days <= 30 and conf == "High":
        return {
            "buy_or_wait": "Buy now",
            "buy_wait_reason": (
                "Buy now — fit looks right and you saved this recently, "
                "while it is still available."
            ),
        }

    if days > 90:
        return {
            "buy_or_wait": "Wait",
            "buy_wait_reason": (
                "Wait — this save is old; re-check if you still want it "
                "and confirm fit before buying."
            ),
        }

    return {
        "buy_or_wait": "Wait",
        "buy_wait_reason": (
            "Wait — no stock pressure right now; you can confirm fit "
            "before you buy."
        ),
    }


def verdict_kind(result: dict) -> str:
    """Map buy_or_wait + fit_confidence to a scannable badge kind."""
    action = result.get("buy_or_wait") or "Wait"
    conf = result.get("fit_confidence") or "Low"
    if action == "Needs more info" or conf == "Low":
        return "check"
    if action == "Buy now":
        return "buy"
    return "wait"


def compose_why_line(result: dict) -> str:
    """One plain-language line under the verdict, grounded in existing fields."""
    snippets = result.get("review_snippets") or []
    n_small = sum(
        1
        for s in snippets
        if _keyword_hit(_norm(s), "runs small") or _keyword_hit(_norm(s), "run small")
    )
    n_true = sum(1 for s in snippets if _keyword_hit(_norm(s), "true to size"))
    bits: list[str] = []
    if n_small:
        bits.append(f"Runs small per {n_small} review{'s' if n_small != 1 else ''}")
    elif n_true:
        bits.append("Reviews call it true to size")
    elif result.get("fit_confidence") == "Low":
        bits.append("Fit is still uncertain")

    if result.get("stock_status") == "low_stock":
        bits.append("your size is low in stock")
    days = result.get("saved_days_ago")
    if isinstance(days, int) and days >= 60:
        bits.append(f"sitting {days} days")

    if bits:
        line = "; ".join(bits)
        if not line.endswith("."):
            line += "."
        return line[0].upper() + line[1:]

    return (
        (result.get("buy_wait_reason") or "").strip()
        or (result.get("fit_reason") or "").strip()
        or "Not enough detail yet to explain this call."
    )


def wishlist_health_line(rows: list[dict]) -> str:
    n = len(rows)
    stale = sum(1 for x in rows if int(x.get("saved_days_ago") or 0) >= 60)
    low_stock = sum(1 for x in rows if x.get("stock_status") == "low_stock")
    uncertain = sum(1 for x in rows if x.get("fit_confidence") in ("Low", "Medium"))
    return (
        f"{n} item{'s' if n != 1 else ''} saved · "
        f"{stale} sitting 60+ days · "
        f"{low_stock} low in stock · "
        f"{uncertain} with fit uncertainty"
    )


# ---------------------------------------------------------------------------
# Live mode (one Groq call)
# ---------------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _build_live_user_prompt(payload: dict) -> str:
    return (
        "Advise on this wishlisted fashion item. Return ONLY the JSON object.\n\n"
        f"Product: {payload['product']}\n"
        f"Size chart (may be empty): {payload['size_chart'] or '(not provided)'}\n"
        f"Reviews (may be empty):\n{payload['reviews'] or '(not provided)'}\n"
        f"Shopper size / measurements: {payload['size_info']}\n"
        f"Why they saved it: {payload['why_saved'] or '(not provided)'}\n"
        f"Stock / price notes: {payload['stock_notes'] or '(not provided)'}\n"
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
        max_tokens=400,
    )
    raw = (response.choices[0].message.content or "").strip()
    parsed = json.loads(_strip_code_fences(raw))
    if not isinstance(parsed, dict):
        raise ValueError("Model did not return a JSON object.")
    return parsed


def normalize_live_result(parsed: dict) -> dict:
    conf = str(parsed.get("fit_confidence") or "Low").strip().title()
    if conf not in ("High", "Medium", "Low"):
        conf = "Low"

    action = str(parsed.get("buy_or_wait") or "Needs more info").strip()
    action_map = {
        "buy now": "Buy now",
        "wait": "Wait",
        "needs more info": "Needs more info",
    }
    action = action_map.get(action.lower(), "Needs more info")

    extra = parsed.get("info_to_check") or []
    if isinstance(extra, str):
        extra = [extra]
    extra = [str(x).strip() for x in extra if str(x).strip()]

    return {
        "fit_recommendation": str(parsed.get("fit_recommendation") or "—").strip() or "—",
        "fit_confidence": conf,
        "fit_reason": str(parsed.get("fit_reason") or "No reason returned.").strip(),
        "buy_or_wait": action,
        "buy_wait_reason": str(
            parsed.get("buy_wait_reason") or "No rationale returned."
        ).strip(),
        "info_to_check": extra,
        "name": "Your item",
        "brand": "",
        "category": "Custom paste",
        "price": None,
        "saved_days_ago": None,
        "stock_status": None,
        "review_snippets": [],
        "is_live": True,
    }


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def inject_css() -> None:
    st.markdown(
        """
        <style>
          .block-container { max-width: 860px; padding-top: 1.6rem; font-size: 15px; }
          h1 { font-size: 1.7rem !important; letter-spacing: -0.02em; }
          p, li, label, .stMarkdown, .stCaption { font-size: 15px !important; }
          .hint { color: #64748b; font-size: 15px; margin-bottom: 0.4rem; }
          .sample-banner {
            background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;
            padding: 0.7rem 0.95rem; color: #334155; font-size: 15px;
            margin: 0.4rem 0 0.85rem 0;
          }
          .insight-line {
            color: #475569; font-size: 15px; line-height: 1.45;
            border-left: 3px solid #94a3b8; padding: 0.2rem 0 0.2rem 0.75rem;
            margin: 0 0 0.9rem 0;
          }
          .health-strip {
            background: #0f172a; color: #f8fafc; border-radius: 10px;
            padding: 0.85rem 1rem; font-size: 15px; line-height: 1.45;
            margin: 0.35rem 0 1rem 0;
          }
          .item-meta { color: #64748b; font-size: 15px; margin-top: -0.35rem; }
          .pill {
            display: inline-block; border-radius: 999px; padding: 0.2rem 0.7rem;
            font-size: 14px; font-weight: 600; letter-spacing: 0.01em;
          }
          .verdict-badge {
            display: inline-block; font-size: 15px; font-weight: 700;
            border-radius: 8px; padding: 0.4rem 0.75rem; border: 1px solid;
            letter-spacing: 0.01em;
          }
          .why-line { color: #334155; font-size: 15px; margin: 0.45rem 0 0.1rem 0; }
          .muted { color: #64748b; font-size: 15px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def pill(label: str, color: str) -> str:
    return (
        f'<span class="pill" style="background:{color}18;color:{color};'
        f'border:1px solid {color}44;">{label}</span>'
    )


def render_verdict_badge(result: dict) -> None:
    label, fg, bg, border = VERDICT_STYLES[verdict_kind(result)]
    st.markdown(
        f'<span class="verdict-badge" style="color:{fg};background:{bg};'
        f'border-color:{border};">{label}</span>',
        unsafe_allow_html=True,
    )


def render_notify_toggle(item_key: str) -> None:
    nonce = st.session_state.get("reset_nonce", 0)
    toggle_key = f"notify_{nonce}_{item_key}"
    on = st.toggle(
        "🔔 Notify me if price drops or it's back in stock (simulated)",
        key=toggle_key,
        help="Prototype only. Nothing is sent; the confirmation stays in this session.",
    )
    if on:
        st.info(
            "You'll be alerted (prototype — notifications are simulated in this MVP)."
        )


def render_panels(
    result: dict,
    *,
    show_item_header: bool = True,
    item_key: str = "item",
) -> None:
    if show_item_header:
        title_bits = [result.get("name") or "Item"]
        if result.get("brand"):
            title_bits.append(f"· {result['brand']}")
        st.subheader(" ".join(title_bits))
        meta_parts = []
        if result.get("category"):
            meta_parts.append(result["category"])
        if result.get("price") is not None:
            meta_parts.append(f"₹{int(result['price']):,}")
        if result.get("saved_days_ago") is not None:
            days = result["saved_days_ago"]
            meta_parts.append(f"Saved {days} day{'s' if days != 1 else ''} ago")
        if result.get("stock_status"):
            stock_label = (
                "Low stock (simulated)"
                if result["stock_status"] == "low_stock"
                else "In stock (simulated)"
            )
            meta_parts.append(stock_label)
        if meta_parts:
            st.markdown(
                f'<p class="item-meta">{" · ".join(meta_parts)}</p>',
                unsafe_allow_html=True,
            )

    fit_col, wait_col = st.columns(2, gap="medium")
    conf = result.get("fit_confidence") or "Low"

    with fit_col:
        with st.container(border=True):
            st.markdown("**Fit Confidence**")
            st.markdown(
                pill(conf, CONF_COLORS.get(conf, "#334155")),
                unsafe_allow_html=True,
            )
            st.markdown(
                f"Recommended size: **{result.get('fit_recommendation', '—')}**"
            )
            st.write(result.get("fit_reason") or "")

    with wait_col:
        with st.container(border=True):
            st.markdown("**Buy or Wait?**")
            render_verdict_badge(result)
            st.markdown(
                f'<p class="why-line">{html.escape(compose_why_line(result))}</p>',
                unsafe_allow_html=True,
            )
            extra = result.get("info_to_check") or []
            if extra:
                st.caption("Worth checking")
                for row in extra:
                    st.write(f"- {row}")

    render_notify_toggle(item_key)


def reset_state() -> None:
    st.session_state.reset_nonce = st.session_state.get("reset_nonce", 0) + 1
    st.session_state.pop("live_result", None)
    st.session_state.pop("live_error", None)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Wishlist Decision Assistant",
        page_icon="🛍️",
        layout="centered",
    )
    inject_css()

    if "reset_nonce" not in st.session_state:
        st.session_state.reset_nonce = 0

    api_key = get_groq_api_key()
    nonce = st.session_state.reset_nonce

    st.title("Wishlist Decision Assistant")
    st.markdown(
        '<p class="hint">You already liked it enough to save it. This tool answers '
        "the two things that still block purchase: <strong>will it fit?</strong> and "
        "<strong>should I buy now or wait?</strong> — no discounts, no coupons.</p>",
        unsafe_allow_html=True,
    )

    mode_labels = ["Demo", "Try your own"]
    mode = st.radio(
        "Mode",
        mode_labels,
        horizontal=True,
        label_visibility="collapsed",
        key=f"mode_{nonce}",
    )

    st.markdown(
        '<div class="sample-banner"><strong>Sample data.</strong> Demo items, '
        "size charts, reviews, and stock status are seeded AJIO-style examples "
        "— not live catalogue or inventory.</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="insight-line">{html.escape(RESEARCH_INSIGHT)}</p>',
        unsafe_allow_html=True,
    )

    # ----- Demo -----
    if mode == "Demo":
        top_l, top_r = st.columns([3, 1])
        with top_l:
            st.caption("Your usual size (applied to every sample item)")
        with top_r:
            if st.button("Reset", use_container_width=True, key=f"reset_demo_{nonce}"):
                reset_state()
                st.rerun()

        size_col, chest_col, waist_col = st.columns(3)
        with size_col:
            usual_size = st.selectbox(
                "Usual size",
                LETTER_SIZES,
                index=2,
                key=f"usual_size_{nonce}",
            )
        with chest_col:
            chest_raw = st.number_input(
                "Chest / bust (in), optional",
                min_value=0.0,
                max_value=60.0,
                value=0.0,
                step=0.5,
                key=f"chest_{nonce}",
            )
        with waist_col:
            waist_raw = st.number_input(
                "Waist (in), optional",
                min_value=0.0,
                max_value=60.0,
                value=0.0,
                step=0.5,
                key=f"waist_{nonce}",
            )

        chest = chest_raw if chest_raw > 0 else None
        waist = waist_raw if waist_raw > 0 else None

        try:
            items = load_sample_wishlist()
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
            fit = compute_fit(item, usual_size, chest, waist)
            wait = compute_buy_or_wait(item, fit)
            rows.append({**item, **fit, **wait})

        st.markdown(
            f'<div class="health-strip">{html.escape(wishlist_health_line(rows))}</div>',
            unsafe_allow_html=True,
        )

        for row in rows:
            render_panels(row, item_key=str(row.get("id") or row.get("name") or "item"))
            with st.expander("Reviews used for this item"):
                for snippet in row.get("review_snippets") or []:
                    st.write(f"- {snippet}")

    # ----- Live -----
    else:
        top_l, top_r = st.columns([3, 1])
        with top_l:
            st.caption("Paste one item you have saved. One Groq call, same two panels.")
        with top_r:
            if st.button("Reset", use_container_width=True, key=f"reset_live_{nonce}"):
                reset_state()
                st.rerun()

        if not api_key:
            st.info(
                "Live mode needs a Groq API key. Demo mode works without one — "
                "switch back to **Demo**, or add `GROQ_API_KEY` in the app's "
                "Streamlit secrets."
            )
            return

        with st.form(f"live_form_{nonce}"):
            product = st.text_input(
                "Product name / brand",
                placeholder="e.g. NETPLAY Men Slim Fit Cotton Shirt",
            )
            size_chart_text = st.text_area(
                "Size chart (optional)",
                placeholder="S 38\" chest · M 40\" · L 42\"",
                height=80,
            )
            reviews = st.text_area(
                "A few review lines (optional)",
                placeholder="Runs small. True to size. Fabric feels premium.",
                height=90,
            )
            size_info = st.text_input(
                "Your size / measurements",
                placeholder="Usual M, chest 40 in, waist 32 in",
            )
            why_saved = st.text_input(
                "Why you saved it (optional)",
                placeholder="Needed a white shirt for client meetings",
            )
            stock_notes = st.text_input(
                "Stock / price notes (optional)",
                placeholder="Low stock in M; still at ₹1,299",
            )
            submitted = st.form_submit_button("Get a decision", type="primary")

        if submitted:
            if not product.strip() or not size_info.strip():
                st.warning("Add at least a product name/brand and your size / measurements.")
            else:
                try:
                    parsed = call_groq(
                        {
                            "product": product.strip(),
                            "size_chart": size_chart_text.strip(),
                            "reviews": reviews.strip(),
                            "size_info": size_info.strip(),
                            "why_saved": why_saved.strip(),
                            "stock_notes": stock_notes.strip(),
                        },
                        api_key,
                    )
                    result = normalize_live_result(parsed)
                    result["name"] = product.strip()
                    st.session_state.live_result = result
                    st.session_state.live_error = None
                except Exception:
                    st.session_state.live_result = None
                    st.session_state.live_error = (
                        "Could not get a live decision just now. Check the API key "
                        "and try again — or use Demo mode, which works without a key."
                    )

        if st.session_state.get("live_error"):
            st.error(st.session_state.live_error)
        if st.session_state.get("live_result"):
            render_panels(st.session_state.live_result, item_key="live_custom")

    with st.expander("How this works / what's simulated"):
        st.markdown(
            """
**What this tool is for.** Wishlisted fashion items stall for two reasons:
fit doubt, and no reason to act now. Each item gets a **Fit Confidence** panel
and a **Buy or Wait?** panel with a verdict badge and a one-line why. There
are no discounts or coupons.

**Demo mode (no API key).** Uses four seeded AJIO-style products in
`sample_wishlist.json`. Fit is a rule over your usual size / optional
measurements, the size chart, and review keywords (*runs small*, *runs large*,
*true to size*). Buy-or-wait is a rule over that fit call, how long ago the
item was saved, and stock status. The **wishlist health** strip counts those
same fields (saves, 60+ days, low stock, fit uncertainty).

**What is simulated.** Names, prices, size charts, review snippets, days since
save, and stock (`in_stock` / `low_stock`) are **sample data**, not a live
catalogue. **Notify me** only confirms in this session — no emails, no backend.
Demo does not call an LLM.

**Insight line.** The sentence about fit uncertainty and waiting is from prior
research, not a live computation on your data.

**Live mode.** Pastes your own item into one Groq chat call
(`openai/gpt-oss-120b`) and renders the same two panels (badge + why + notify).
The key is read from `st.secrets["GROQ_API_KEY"]` only. If it is missing, live
mode stays disabled and Demo still works.

**Reset** clears your size inputs, notify toggles, and any live result.
            """
        )


if __name__ == "__main__":
    main()
