"""Tests for the Wishlist Decision Assistant fit and next-action engines.

Run from the repository root:

    python -m unittest tests.test_engines
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
MVP = ROOT / "mvp"
if str(MVP) not in sys.path:
    sys.path.insert(0, str(MVP))

import streamlit_app as app  # noqa: E402

LETTER_CHART = {
    "S": {"chest": 38, "waist": 30, "length": 27},
    "M": {"chest": 40, "waist": 32, "length": 28},
    "L": {"chest": 42, "waist": 34, "length": 29},
}

STRONG_FIT = {
    "fit_recommendation": "M",
    "fit_confidence": "High",
    "fit_reason": "Chart and reviews agree on M.",
}

# Phrases that *recommend* a monetary incentive. Explicit prohibitions are stripped first.
_ALLOWED_DISCOUNT_TALK = (
    "never recommend a discount, coupon, markdown, or waiting for a sale",
    "do not wait for a sale or coupon",
    "no discounts or coupons",
    "without discounts or coupons",
    "no markdown, no code fences",
)
_DISCOUNT_TERMS = (
    "discount",
    "coupon",
    "wait for a sale",
    "% off",
    "price markdown",
)


def _item(**overrides) -> dict:
    base = {
        "name": "Test shirt",
        "brand": "TEST",
        "category": "Men's Shirts",
        "price": 1299,
        "size_chart": dict(LETTER_CHART),
        "review_snippets": ["True to size. I wear M and M was a perfect fit."],
        "save_reason": "Need a white shirt for work.",
        "intended_use": "Office",
        "occasion_days_remaining": None,
        "unresolved_questions": [],
        "comparison_status": "not_comparing",
        "intent_state": "active",
        "saved_days_ago": 5,
        "stock_status": "in_stock",
        "stock_is_simulated": True,
    }
    base.update(overrides)
    return base


def _decision_blobs(result: dict) -> str:
    parts = [
        result.get("decision_status"),
        result.get("decision_reason"),
        result.get("next_step"),
        result.get("fit_reason"),
        result.get("fit_recommendation"),
        " ".join(str(x) for x in (result.get("evidence_used") or [])),
        " ".join(str(x) for x in (result.get("supporting_context") or [])),
    ]
    return " ".join(str(p) for p in parts if p)


def _discount_recommendation_hits(text: str) -> list[str]:
    blob = app._norm(text)
    for allowed in _ALLOWED_DISCOUNT_TALK:
        blob = blob.replace(allowed, " ")
    return [term for term in _DISCOUNT_TERMS if term in blob]


class FitEngineTests(unittest.TestCase):
    def test_conflicting_reviews_yield_low_confidence(self) -> None:
        item = _item(
            review_snippets=[
                "Runs small in the waist — I needed to size up.",
                "True to size for me.",
            ]
        )
        fit = app.compute_fit(item, "M", 40.0, 32.0)
        self.assertEqual(fit["fit_confidence"], "Low")
        self.assertTrue(fit["fit_recommendation"])

    def test_true_to_size_plus_measurement_is_high(self) -> None:
        fit = app.compute_fit(_item(), "M", 40.0, 32.0)
        self.assertEqual(fit["fit_confidence"], "High")
        self.assertEqual(fit["fit_recommendation"], "M")

    def test_runs_small_nudges_size_up(self) -> None:
        item = _item(
            review_snippets=["Looks sharp but runs small — I had to size up from M to L."]
        )
        fit = app.compute_fit(item, "M", 40.0, 32.0)
        self.assertEqual(fit["fit_recommendation"], "L")
        self.assertIn(fit["fit_confidence"], ("High", "Medium"))

    def test_missing_measurements_still_return_a_size(self) -> None:
        fit = app.compute_fit(_item(), "M", None, None)
        self.assertTrue(str(fit["fit_recommendation"]).strip())
        self.assertIn(fit["fit_confidence"], ("High", "Medium", "Low"))


class DecisionEngineTests(unittest.TestCase):
    def test_01_low_fit_confidence_checks_before_buying(self) -> None:
        """Low fit confidence → check first (demo: Check fit first), never Ready to buy.

        Check one thing first is reserved for missing product facts (see test 07).
        """
        item = _item(
            review_snippets=[
                "Runs small — size up.",
                "True to size for me.",
            ],
            intent_state="active",
            occasion_days_remaining=9,
            stock_status="low_stock",
        )
        fit = app.compute_fit(item, "M", 40.0, 32.0)
        self.assertEqual(fit["fit_confidence"], "Low")
        decision = app.compute_next_action(item, fit)
        self.assertEqual(decision["decision_status"], "Check fit first")
        self.assertNotEqual(decision["decision_status"], "Ready to buy")
        self.assertIn("check", decision["decision_status"].lower())

    def test_02_upcoming_occasion_active_intent_strong_fit_ready_to_buy(self) -> None:
        item = _item(
            intent_state="active",
            occasion_days_remaining=9,
            comparison_status="not_comparing",
            unresolved_questions=[],
        )
        fit = app.compute_fit(item, "M", 40.0, 32.0)
        self.assertIn(fit["fit_confidence"], ("High", "Medium"))
        decision = app.compute_next_action(item, fit)
        self.assertEqual(decision["decision_status"], "Ready to buy")
        self.assertIn("upcoming need", decision["decision_reason"].lower())
        self.assertNotIn("saved_days_ago", decision["decision_reason"])

    def test_03_recent_save_without_occasion_is_not_ready_to_buy(self) -> None:
        item = _item(
            intent_state="active",
            occasion_days_remaining=None,
            saved_days_ago=3,
            stock_status="in_stock",
        )
        fit = app.compute_fit(item, "M", 40.0, 32.0)
        self.assertIn(fit["fit_confidence"], ("High", "Medium"))
        decision = app.compute_next_action(item, fit)
        self.assertNotEqual(decision["decision_status"], "Ready to buy")
        self.assertEqual(decision["decision_status"], "Worth waiting")

    def test_04_simulated_low_stock_alone_is_not_ready_to_buy(self) -> None:
        item = _item(
            intent_state="active",
            occasion_days_remaining=None,
            saved_days_ago=2,
            stock_status="low_stock",
            stock_is_simulated=True,
        )
        fit = app.compute_fit(item, "M", 40.0, 32.0)
        decision = app.compute_next_action(item, fit)
        self.assertNotEqual(decision["decision_status"], "Ready to buy")
        self.assertEqual(decision["decision_status"], "Worth waiting")
        self.assertTrue(decision.get("supporting_context"))
        reason = decision["decision_reason"].lower()
        self.assertNotIn("low in stock", reason)
        self.assertNotIn("buy now", reason)

    def test_05_active_comparison_is_compare_first(self) -> None:
        item = _item(
            comparison_status="comparing",
            intent_state="active",
            occasion_days_remaining=7,
            stock_status="low_stock",
        )
        fit = app.compute_fit(item, "M", 40.0, 32.0)
        self.assertIn(fit["fit_confidence"], ("High", "Medium"))
        decision = app.compute_next_action(item, fit)
        self.assertEqual(decision["decision_status"], "Compare first")
        self.assertNotEqual(decision["decision_status"], "Ready to buy")

    def test_06_stale_item_with_weakened_intent_is_reconsider(self) -> None:
        stale = _item(
            intent_state="stale",
            occasion_days_remaining=None,
            saved_days_ago=150,
            save_reason="Liked the wash months ago.",
        )
        fit = app.compute_fit(stale, "M", 40.0, 32.0)
        self.assertIn(fit["fit_confidence"], ("High", "Medium"))
        decision = app.compute_next_action(stale, fit)
        self.assertEqual(decision["decision_status"], "Reconsider this save")

        weakened = _item(
            intent_state="uncertain",
            save_reason="",
            intended_use="",
            occasion_days_remaining=None,
        )
        decision2 = app.compute_next_action(weakened, STRONG_FIT)
        self.assertEqual(decision2["decision_status"], "Reconsider this save")

    def test_07_missing_information_safe_fallback(self) -> None:
        no_chart = _item(size_chart={}, unresolved_questions=[])
        decision = app.compute_next_action(no_chart, STRONG_FIT)
        self.assertEqual(decision["decision_status"], "Check one thing first")
        self.assertNotEqual(decision["decision_status"], "Ready to buy")

        open_fit_q = _item(
            unresolved_questions=["Will this run small in the waist for me?"],
            size_chart=dict(LETTER_CHART),
        )
        decision_q = app.compute_next_action(open_fit_q, STRONG_FIT)
        self.assertEqual(decision_q["decision_status"], "Check one thing first")

        thin = {
            "product": "Shirt",
            "category": "Men's Shirts",
            "size_info": "Usual M",
            "comparison_status": "not_comparing",
            "occasion_for": "No specific occasion",
            "why_saved": "",
            "occasion_timing": "",
            "unresolved_questions": "",
            "size_chart": "",
            "reviews": "",
            "availability": "Only L left",
            "extra_context": "",
        }
        self.assertTrue(app._live_payload_too_thin(thin))
        fallback = app._live_fallback_result()
        self.assertEqual(fallback["decision_status"], "Needs more information")
        self.assertEqual(fallback["fit_confidence"], "Low")
        empty = app.normalize_live_result({})
        self.assertEqual(empty["decision_status"], "Needs more information")
        self.assertEqual(empty["fit_recommendation"], "—")


class LiveNormalizerTests(unittest.TestCase):
    def test_08_unknown_enums_normalised_safely(self) -> None:
        parsed = {
            "fit_recommendation": ["L", "maybe"],
            "fit_confidence": "Pretty sure",
            "fit_reason": {"note": "invented"},
            "fit_evidence_used": "chart",
            "decision_status": "YOLO buy it",
            "decision_reason": None,
            "next_step": 12,
            "decision_evidence_used": {"a": 1},
        }
        result = app.normalize_live_result(parsed)
        self.assertEqual(result["fit_confidence"], "Low")
        self.assertEqual(result["decision_status"], "Needs more information")
        self.assertIsInstance(result["fit_recommendation"], str)
        self.assertIsInstance(result["fit_reason"], str)
        self.assertIsInstance(result["decision_reason"], str)
        self.assertIsInstance(result["next_step"], str)
        self.assertIsInstance(result["fit_evidence_used"], list)
        self.assertIsInstance(result["decision_evidence_used"], list)
        self.assertIn(result["decision_status"], app.VERDICT_STYLES)
        self.assertIn(result["fit_confidence"], ("High", "Medium", "Low"))

        aliased = app.normalize_live_result(
            {
                "fit_confidence": "high",
                "decision_status": "Buy now",
                "fit_recommendation": "M",
                "fit_reason": "ok",
                "decision_reason": "ok",
                "next_step": "ok",
                "fit_evidence_used": ["reviews"],
                "decision_evidence_used": ["occasion"],
            }
        )
        self.assertEqual(aliased["fit_confidence"], "High")
        self.assertEqual(aliased["decision_status"], "Ready to buy")

        self.assertEqual(app.normalize_live_result(None)["decision_status"], "Needs more information")  # type: ignore[arg-type]
        self.assertEqual(app.normalize_live_result("nope")["decision_status"], "Needs more information")  # type: ignore[arg-type]


class DemoWithoutKeyTests(unittest.TestCase):
    def test_09_no_groq_api_key_demo_continues_working(self) -> None:
        missing = MagicMock()
        missing.__getitem__.side_effect = KeyError("GROQ_API_KEY")
        with patch.object(app.st, "secrets", missing):
            self.assertIsNone(app.get_groq_api_key())

        empty = {"GROQ_API_KEY": "   "}
        with patch.object(app.st, "secrets", empty):
            self.assertIsNone(app.get_groq_api_key())

        items = app.load_sample_wishlist()
        self.assertEqual(len(items), 4)
        expected = {
            "and-aline-dress": "Ready to buy",
            "aurelia-printed-kurta": "Worth waiting",
            "dnmx-skinny-jeans": "Check fit first",
            "netplay-slim-shirt": "Compare first",
        }
        rows = []
        for item in items:
            fit = app.compute_fit(item, "M", 40.0, 32.0)
            decision = app.compute_next_action(item, fit)
            self.assertIn(fit["fit_confidence"], ("High", "Medium", "Low"))
            self.assertIn(decision["decision_status"], app.VERDICT_STYLES)
            self.assertEqual(
                decision["decision_status"],
                expected[str(item["id"])],
                msg=item["id"],
            )
            rows.append({**item, **fit, **decision})
        self.assertEqual(len(rows), 4)


class NoDiscountTests(unittest.TestCase):
    def test_10_application_never_recommends_a_discount_or_coupon(self) -> None:
        prompt = app.SYSTEM_PROMPT.lower()
        self.assertIn("never recommend a discount", prompt)
        self.assertIn("coupon", prompt)
        self.assertEqual(_discount_recommendation_hits(app.SYSTEM_PROMPT), [])
        self.assertEqual(_discount_recommendation_hits(app.PROTO_BANNER), [])

        user_prompt = app._build_live_user_prompt(
            {
                "product": "Shirt",
                "price": "999",
                "availability": "low stock",
            }
        )
        self.assertEqual(_discount_recommendation_hits(user_prompt), [])

        items = app.load_sample_wishlist()
        blobs = [app.SYSTEM_PROMPT, app.PROTO_BANNER, app.FIT_NOTE]
        for item in items:
            fit = app.compute_fit(item, "M", 40.0, 32.0)
            decision = app.compute_next_action(item, fit)
            blobs.append(_decision_blobs({**fit, **decision}))

        extra_cases = [
            (_item(occasion_days_remaining=9), None),
            (_item(occasion_days_remaining=None, saved_days_ago=3), None),
            (_item(stock_status="low_stock", occasion_days_remaining=None), None),
            (_item(comparison_status="comparing"), None),
            (_item(intent_state="stale"), None),
            (_item(size_chart={}), STRONG_FIT),
            (_item(review_snippets=["Runs small.", "True to size."]), None),
        ]
        for item, preset_fit in extra_cases:
            fit = preset_fit or app.compute_fit(item, "M", 40.0, 32.0)
            decision = app.compute_next_action(item, fit)
            blobs.append(_decision_blobs({**fit, **decision}))

        blobs.append(_decision_blobs(app._live_fallback_result()))

        for blob in blobs:
            hits = _discount_recommendation_hits(blob)
            self.assertEqual(hits, [], msg=f"discount/coupon recommendation in: {blob[:240]}")

        coupon_status = app.normalize_live_result(
            {
                "fit_confidence": "High",
                "decision_status": "Wait for a coupon",
                "fit_recommendation": "M",
                "fit_reason": "Chart match.",
                "decision_reason": "ok",
                "next_step": "ok",
                "fit_evidence_used": ["chart"],
                "decision_evidence_used": ["intent"],
            }
        )
        self.assertEqual(coupon_status["decision_status"], "Needs more information")
        self.assertNotEqual(coupon_status["decision_status"], "Ready to buy")


if __name__ == "__main__":
    unittest.main()
