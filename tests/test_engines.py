"""Tests for the Wishlist Decision Assistant fit and next-action engines.

Run from the repository root:

    python -m unittest tests.test_engines
"""

from __future__ import annotations

import json
import os
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
    def test_high_when_measurement_and_reviews_agree_on_the_same_size(self) -> None:
        fit = app.compute_fit(_item(), "M", 40.0, 32.0)
        self.assertEqual(fit["fit_recommendation"], "M")
        self.assertEqual(fit["fit_confidence"], "High")
        self.assertIn("true to size", fit["fit_reason"].lower())

    def test_medium_when_reviews_adjust_one_size_from_the_measurement_match(self) -> None:
        item = _item(
            size_chart={
                "M": {"chest": 40},
                "L": {"chest": 42},
            },
            review_snippets=[
                "Runs small — I had to size up. The shirt is tight in M."
            ],
        )
        fit = app.compute_fit(item, "M", 40.0, None)
        self.assertEqual(fit["fit_recommendation"], "L")
        self.assertEqual(fit["fit_confidence"], "Medium")
        reason = fit["fit_reason"].lower()
        self.assertIn("matches m", reason)
        self.assertIn("do not directly agree on l", reason)

    def test_medium_when_only_the_measurement_is_strong(self) -> None:
        item = _item(review_snippets=["Love the colour and the buttons."])
        fit = app.compute_fit(item, "M", 40.0, 32.0)
        self.assertEqual(fit["fit_recommendation"], "M")
        self.assertEqual(fit["fit_confidence"], "Medium")

    def test_medium_when_only_reviews_are_strong(self) -> None:
        fit = app.compute_fit(_item(), "M", None, None)
        self.assertEqual(fit["fit_recommendation"], "M")
        self.assertEqual(fit["fit_confidence"], "Medium")

    def test_low_when_reviews_conflict(self) -> None:
        item = _item(
            review_snippets=[
                "Runs small in the waist — I needed to size up.",
                "True to size for me.",
            ]
        )
        fit = app.compute_fit(item, "M", 40.0, 32.0)
        self.assertEqual(fit["fit_confidence"], "Low")
        self.assertTrue(fit["fit_recommendation"])

    def test_low_when_chart_and_measurements_are_insufficient(self) -> None:
        item = _item(size_chart={}, review_snippets=[])
        fit = app.compute_fit(item, "M", None, None)
        self.assertEqual(fit["fit_recommendation"], "M")
        self.assertEqual(fit["fit_confidence"], "Low")

    def test_low_when_adjusted_size_is_not_on_the_chart(self) -> None:
        item = _item(
            size_chart={"M": {"chest": 40}},
            review_snippets=["Runs small — size up."],
        )
        fit = app.compute_fit(item, "M", 40.0, None)
        self.assertEqual(fit["fit_recommendation"], "L")
        self.assertEqual(fit["fit_confidence"], "Low")

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
        self.assertEqual(fit["fit_confidence"], "Medium")

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
        with self.assertRaises(app.GroqParseError):
            app.normalize_live_result({})
        missing = app.validate_custom_payload(dict(thin))
        self.assertTrue(any("fit evidence" in item.lower() for item in missing))
        self.assertNotIn("Product name", missing)
        self.assertNotIn("Category", missing)
        self.assertNotIn("Usual size", missing)


class ShopperCopyTests(unittest.TestCase):
    def test_full_analyse_payload_is_not_thin(self) -> None:
        payload = {
            "product": "Cotton shirt",
            "category": "Men's Shirts",
            "size_info": "Usual M, chest 40 in",
            "comparison_status": "not_comparing",
            "occasion_for": "Yes",
            "why_saved": "Need it for a client meeting",
            "occasion_timing": "7 days",
            "unresolved_questions": "",
            "size_chart": "M: chest 40 inches; L: chest 42 inches",
            "reviews": "True to size.\nRuns a little long.",
            "availability": "",
            "extra_context": "",
        }
        self.assertFalse(app._live_payload_too_thin(payload))
        fake_nmi = {
            "decision_status": "Needs more information",
            "parse_failed": False,
            "next_step": "Add a size chart, measurements, reviews, save reason, or what is blocking you, then try again.",
        }
        steps = app.live_next_steps(payload, fake_nmi)
        self.assertNotIn("Add a size chart", steps)
        self.assertNotIn("Add one or more review snippets", steps)
        self.assertNotIn("Provide a measurement or usual size", steps)
        chart_ask = app.live_next_steps(
            payload,
            {
                "decision_status": "Needs more information",
                "parse_failed": False,
                "next_step": "Add a size chart",
            },
        )
        self.assertNotIn("Add a size chart", chart_ask)

    def test_parse_failure_does_not_ask_for_fields_already_sent(self) -> None:
        payload = {
            "product_name": "Cotton shirt",
            "category": "Men's Shirts",
            "usual_size": "M",
            "size_chart": "M: chest 40",
            "reviews": "True to size",
            "size_info": "Usual M, chest 40 in",
            "chest": 40,
        }
        result = app._parse_failed_result(payload)
        self.assertEqual(result["failure_kind"], "parse")
        self.assertNotEqual(result["decision_status"], "Needs more information")
        self.assertEqual(result["decision_reason"], app.PARSE_FAILED_MESSAGE)
        steps = app.live_next_steps(payload, result)
        joined = " ".join(steps).lower()
        self.assertIn("try again", joined)
        self.assertNotIn("add a size chart", joined)
        self.assertNotIn("needs more information", joined)

    def test_internal_evidence_keys_are_shopper_facing(self) -> None:
        self.assertEqual(
            app.format_evidence_for_shopper("comparison_status: comparing"),
            "You are comparing another shortlisted product.",
        )
        self.assertEqual(
            app.format_evidence_for_shopper("intent_state: active"),
            "Your interest in this item is still active.",
        )
        line = app.compose_decision_based_on(
            {
                "evidence_used": [
                    "comparison_status: comparing",
                    "intent_state: active",
                ]
            }
        )
        self.assertNotIn("comparison_status", line)
        self.assertNotIn("intent_state", line)
        self.assertNotIn("comparing • active", line)
        self.assertIn("You are comparing another shortlisted product.", line)
        self.assertIn("Your interest in this item is still active.", line)


class LiveNormalizerTests(unittest.TestCase):
    def test_08_unknown_enums_are_schema_failures(self) -> None:
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
        with self.assertRaises(app.GroqParseError):
            app.normalize_live_result(parsed)
        errors = app.validate_live_schema(parsed)
        self.assertTrue(errors)
        self.assertNotIn("Needs more information", " ".join(errors))

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

        with self.assertRaises(app.GroqParseError):
            app.normalize_live_result(None)  # type: ignore[arg-type]
        with self.assertRaises(app.GroqParseError):
            app.normalize_live_result("nope")  # type: ignore[arg-type]
        with self.assertRaises(app.GroqParseError):
            app.normalize_live_result({"_parse_failed": True})


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

        with self.assertRaises(app.GroqParseError):
            app.normalize_live_result(
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


def _full_custom_payload(**overrides) -> dict:
    payload = {
        "product": "Cotton shirt",
        "product_name": "Cotton shirt",
        "brand": "Netplay",
        "category": "Men's Shirts",
        "price": "1899",
        "why_saved": "Need it for a client meeting",
        "occasion_for": "Yes",
        "occasion_timing": "7 days",
        "unresolved_questions": None,
        "comparison_status": "not_comparing",
        "size_info": "Usual M, chest 40 in",
        "size_chart": "M: chest 40 inches; L: chest 42 inches",
        "reviews": "True to size.\nRuns a little long.",
        "availability": None,
        "extra_context": None,
        "usual_size": "M",
        "chest": 40.0,
        "waist": None,
    }
    payload.update(overrides)
    return payload


_VALID_GROQ = {
    "fit_recommendation": "M",
    "fit_confidence": "High",
    "fit_reason": "Chart and measurement agree on M.",
    "fit_evidence_used": ["size chart", "chest 40 in"],
    "decision_status": "Ready to buy",
    "decision_reason": "Upcoming occasion and fit is clear.",
    "next_step": "Buy the suggested size.",
    "decision_evidence_used": ["occasion", "fit"],
}


class CustomAnalysisFlowTests(unittest.TestCase):
    def test_validate_requires_name_category_usual_and_fit_evidence(self) -> None:
        missing = app.validate_custom_payload({})
        self.assertIn("Product name", missing)
        self.assertIn("Category", missing)
        self.assertIn("Usual size", missing)
        self.assertTrue(any("fit evidence" in item.lower() for item in missing))

    def test_validate_normalises_blanks_and_zero_measurements(self) -> None:
        payload = {
            "product_name": "  Shirt  ",
            "category": "Men's Shirts",
            "usual_size": "M",
            "size_chart": "   ",
            "reviews": "",
            "chest": 0,
            "waist": 0.0,
            "price": "  ",
        }
        missing = app.validate_custom_payload(payload)
        self.assertEqual(payload["product_name"], "Shirt")
        self.assertIsNone(payload["size_chart"])
        self.assertIsNone(payload["reviews"])
        self.assertIsNone(payload["chest"])
        self.assertIsNone(payload["waist"])
        self.assertIsNone(payload["price"])
        self.assertTrue(any("fit evidence" in item.lower() for item in missing))
        self.assertNotIn("Product name", missing)
        self.assertNotIn("Category", missing)
        self.assertNotIn("Usual size", missing)

    def test_validate_does_not_claim_present_fields_missing(self) -> None:
        payload = _full_custom_payload()
        missing = app.validate_custom_payload(payload)
        self.assertEqual(missing, [])
        self.assertFalse(any("size chart" in item.lower() for item in missing))
        chart_only = _full_custom_payload(reviews=None, chest=None, size_info="Usual M")
        self.assertEqual(app.validate_custom_payload(chart_only), [])
        measure_only = _full_custom_payload(size_chart=None, reviews=None)
        self.assertEqual(app.validate_custom_payload(measure_only), [])
        review_only = _full_custom_payload(size_chart=None, chest=None, size_info="Usual M")
        self.assertEqual(app.validate_custom_payload(review_only), [])

    def test_colour_only_reviews_are_not_fit_evidence(self) -> None:
        payload = _full_custom_payload(
            size_chart=None,
            chest=None,
            waist=None,
            size_info="Usual M",
            reviews="Love the colour and the buttons.",
        )
        missing = app.validate_custom_payload(payload)
        self.assertTrue(any("fit evidence" in item.lower() for item in missing))

    def test_genuine_missing_information_lists_only_absent_fields(self) -> None:
        payload = {
            "product_name": "Cotton shirt",
            "category": "Men's Shirts",
            "usual_size": "M",
            "size_chart": None,
            "reviews": "Nice colour",
            "chest": None,
            "waist": None,
        }
        result = app.analyse_custom_item(payload, "gsk-test")
        self.assertEqual(result["failure_kind"], "missing_information")
        self.assertEqual(result["decision_status"], "Needs more information")
        self.assertEqual(result["missing_fields"], app.validate_custom_payload(dict(payload)))
        joined = " ".join(result["missing_fields"]).lower()
        self.assertIn("fit evidence", joined)
        self.assertNotIn("product name", joined)
        self.assertNotIn("category", joined)
        self.assertNotIn("usual size", joined)

    def test_api_failure_is_not_missing_information(self) -> None:
        with patch.object(app, "call_groq", side_effect=app.GroqAPIError("down")):
            result = app.analyse_custom_item(_full_custom_payload(), "gsk-test")
        self.assertEqual(result["failure_kind"], "rule_fallback")
        self.assertTrue(result.get("is_rule_fallback"))
        self.assertEqual(result["source_label"], app.RULE_FALLBACK_LABEL)
        self.assertNotEqual(result["decision_status"], "Needs more information")
        self.assertNotEqual(result["decision_reason"], app.API_UNAVAILABLE_MESSAGE)
        self.assertFalse(result.get("is_live"))

    def test_parse_failure_is_not_missing_information(self) -> None:
        with patch.object(app, "call_groq", side_effect=app.GroqParseError("bad json")):
            result = app.analyse_custom_item(_full_custom_payload(), "gsk-test")
        self.assertEqual(result["failure_kind"], "parse")
        self.assertNotEqual(result["decision_status"], "Needs more information")
        self.assertEqual(result["decision_reason"], app.PARSE_FAILED_MESSAGE)
        self.assertNotIn("size chart", result["decision_reason"].lower())

    def test_unexpected_exception_is_not_converted_to_missing_information(self) -> None:
        with patch.object(app, "call_groq", side_effect=RuntimeError("boom")):
            result = app.analyse_custom_item(_full_custom_payload(), "gsk-test")
        self.assertEqual(result["failure_kind"], "rule_fallback")
        self.assertTrue(result.get("is_rule_fallback"))
        self.assertNotEqual(result["decision_status"], "Needs more information")
        self.assertEqual(result["source_label"], app.RULE_FALLBACK_LABEL)

    def test_saved_payload_is_passed_exactly_to_groq(self) -> None:
        captured: dict = {}

        def fake_call(payload: dict, api_key: str) -> dict:
            captured["payload"] = payload
            captured["api_key"] = api_key
            return dict(_VALID_GROQ)

        payload = _full_custom_payload()
        with patch.object(app, "call_groq", side_effect=fake_call):
            result = app.analyse_custom_item(payload, "gsk-test")
        self.assertIs(captured["payload"], payload)
        self.assertEqual(captured["api_key"], "gsk-test")
        self.assertEqual(result["decision_status"], "Ready to buy")
        self.assertIsNone(result.get("failure_kind"))

    def test_build_payload_from_form_variables(self) -> None:
        payload = app.build_custom_analysis_payload(
            prod_name="  Cuban shirt  ",
            brand="Netplay",
            category="Men's Shirts",
            price="1899",
            size_chart="M: chest 40",
            reviews="True to size",
            availability="",
            usual="M",
            chest_in=40.0,
            waist_in=0.0,
            save_reason="Client meeting",
            occasion="Yes",
            timeline="7 days",
            unsure=["Fit or size"],
            comparing="No",
            extra="  ",
        )
        self.assertEqual(payload["product_name"], "Cuban shirt")
        self.assertEqual(payload["chest"], 40.0)
        self.assertIsNone(payload["waist"])
        self.assertIsNone(payload["availability"])
        self.assertIsNone(payload["extra_context"])
        self.assertEqual(app.validate_custom_payload(payload), [])

    def test_missing_secret_is_not_missing_information(self) -> None:
        result = app.analyse_custom_item(_full_custom_payload(), None)
        self.assertEqual(result["failure_kind"], "rule_fallback")
        self.assertTrue(result.get("is_rule_fallback"))
        self.assertEqual(result["source_label"], app.RULE_FALLBACK_LABEL)
        self.assertNotEqual(result["decision_status"], "Needs more information")
        self.assertFalse(result.get("is_live"))
        self.assertNotIn("Add a size chart", " ".join(result.get("missing_fields") or []))


class GroqAdapterTests(unittest.TestCase):
    def test_key_is_read_only_from_st_secrets(self) -> None:
        self.assertFalse(app.DEBUG_MODE)
        with patch.dict(os.environ, {"GROQ_API_KEY": "env-should-be-ignored"}, clear=False):
            missing = MagicMock()
            missing.__getitem__.side_effect = KeyError("GROQ_API_KEY")
            with patch.object(app.st, "secrets", missing):
                self.assertIsNone(app.get_groq_api_key())
                self.assertFalse(app.groq_key_detected())
        with patch.object(app.st, "secrets", {"GROQ_API_KEY": "secret-from-st"}):
            self.assertEqual(app.get_groq_api_key(), "secret-from-st")
            self.assertTrue(app.groq_key_detected())

    def test_prompt_includes_every_custom_form_field_and_asks_for_json_only(self) -> None:
        payload = _full_custom_payload()
        prompt = app._build_live_user_prompt(payload)
        self.assertIn("Return ONLY a JSON object", prompt)
        self.assertIn("No markdown, no code fences", prompt)
        for key in app.CUSTOM_PAYLOAD_FIELDS:
            self.assertIn(app.CUSTOM_PAYLOAD_FIELD_LABELS[key] + ":", prompt)
        self.assertIn("only valid json", app.SYSTEM_PROMPT.lower())

    def test_code_fences_are_stripped_before_json_parse(self) -> None:
        body = json.dumps(_VALID_GROQ)
        fenced = "```json\n" + body + "\n```"
        self.assertEqual(app._strip_code_fences(fenced), body)
        parsed = app._parse_groq_json("Here you go:\n```\n" + body + "\n```\n")
        self.assertEqual(parsed["decision_status"], "Ready to buy")
        with self.assertRaises(app.GroqParseError):
            app._parse_groq_json("not json at all")

    def test_schema_validation_rejects_incomplete_objects(self) -> None:
        errors = app.validate_live_schema({"fit_confidence": "High"})
        self.assertTrue(any("Missing field" in item for item in errors))
        self.assertEqual(app.validate_live_schema(dict(_VALID_GROQ)), [])

    def test_debug_snapshot_is_booleans_and_error_codes_only(self) -> None:
        payload = _full_custom_payload()
        present = app.payload_fields_present(payload)
        self.assertTrue(all(isinstance(v, bool) for v in present.values()))
        self.assertTrue(present["size_chart"])
        self.assertTrue(present["chest"])
        blob = str(present)
        self.assertNotIn("Cotton shirt", blob)
        self.assertNotIn("True to size", blob)
        debug = app._empty_debug(payload, key_detected=True)
        self.assertNotIn("api_key", debug)
        self.assertNotIn("gsk", str(debug).lower())
        joined = " ".join(str(v) for v in debug.values())
        self.assertNotIn("1899", joined)

    def test_adapter_logs_never_include_the_api_key(self) -> None:
        records: list[str] = []

        def capture(fmt, *args, **kwargs):
            records.append(fmt % args if args else str(fmt))

        with patch.object(app.logger, "error", side_effect=capture):
            app._log_adapter_error("Groq API request failed", RuntimeError("gsk-leaked"))
        self.assertTrue(records)
        self.assertNotIn("gsk-leaked", " ".join(records))
        self.assertNotIn("gsk", " ".join(records).lower())


class RuleFallbackTests(unittest.TestCase):
    def test_fallback_uses_submitted_fit_and_decision_fields(self) -> None:
        payload = _full_custom_payload()
        result = app.compute_custom_analysis_fallback(payload)
        self.assertEqual(result["source_label"], app.RULE_FALLBACK_LABEL)
        self.assertTrue(result["is_rule_fallback"])
        self.assertFalse(result["is_live"])
        self.assertEqual(result["failure_kind"], "rule_fallback")
        self.assertEqual(result["missing_fields"], [])
        self.assertIn("Submitted size chart", result["fit_evidence_used"])
        self.assertTrue(any("Usual size" in row for row in result["fit_evidence_used"]))
        self.assertTrue(any("Chest" in row for row in result["fit_evidence_used"]))
        self.assertIn("Submitted review snippets", result["fit_evidence_used"])
        blob = " ".join(
            [
                result["fit_reason"],
                result["decision_reason"],
                result["next_step"],
                " ".join(result["fit_evidence_used"]),
                " ".join(result["decision_evidence_used"]),
            ]
        ).lower()
        self.assertNotIn("add a size chart", blob)
        self.assertNotIn("size_chart is missing", blob)
        self.assertIn(result["decision_status"], app.VERDICT_STYLES)
        for key in (
            "fit_recommendation",
            "fit_confidence",
            "fit_reason",
            "fit_evidence_used",
            "decision_status",
            "decision_reason",
            "next_step",
            "decision_evidence_used",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["fit_recommendation"], "M")
        self.assertEqual(result["fit_confidence"], "High")
        self.assertEqual(result["decision_status"], "Ready to buy")

    def test_fallback_reads_comparison_and_does_not_invent_missing_chart(self) -> None:
        payload = _full_custom_payload(comparison_status="comparing")
        result = app.compute_custom_analysis_fallback(payload)
        self.assertEqual(result["decision_status"], "Compare first")
        self.assertEqual(result["missing_fields"], [])
        self.assertNotIn("Add a size chart", result["next_step"])

    def test_fallback_without_occasion_is_not_ready_to_buy(self) -> None:
        payload = _full_custom_payload(
            occasion_for="No specific occasion",
            occasion_timing=None,
        )
        result = app.compute_custom_analysis_fallback(payload)
        self.assertNotEqual(result["decision_status"], "Ready to buy")
        self.assertEqual(result["source_label"], app.RULE_FALLBACK_LABEL)

    def test_size_chart_parser_reads_letter_rows(self) -> None:
        chart = app._parse_size_chart_text("M: chest 40 inches; L: chest 42 inches")
        self.assertEqual(chart["M"]["chest"], 40.0)
        self.assertEqual(chart["L"]["chest"], 42.0)

    def test_groq_success_is_not_labelled_as_rule_fallback(self) -> None:
        with patch.object(app, "call_groq", return_value=dict(_VALID_GROQ)):
            result = app.analyse_custom_item(_full_custom_payload(), "gsk-test")
        self.assertFalse(result.get("is_rule_fallback"))
        self.assertNotEqual(result.get("source_label"), app.RULE_FALLBACK_LABEL)
        self.assertTrue(result.get("is_live"))


class FormatDecisionEvidenceTests(unittest.TestCase):
    def test_maps_internal_fields_to_shopper_sentences(self) -> None:
        result = {
            "evidence_used": [
                "comparison_status: comparing",
                "intent_state: active",
                "occasion_days_remaining: 9",
                "fit_confidence: High",
                "save_reason: Need a midi for a wedding.",
            ]
        }
        item = {
            "comparison_status": "comparing",
            "intent_state": "active",
            "occasion_days_remaining": 9,
            "fit_confidence": "High",
            "save_reason": "Need a midi for a wedding.",
        }
        lines = app.format_decision_evidence(result, item)
        self.assertEqual(
            lines[0],
            "You are comparing another shortlisted product.",
        )
        self.assertIn("Your interest in this item is still active.", lines)
        self.assertIn("You need this item in approximately 9 days.", lines)
        self.assertIn("Available fit signals are consistent.", lines)
        self.assertIn("Need a midi for a wedding.", lines)
        blob = " ".join(lines)
        for marker in (
            "comparison_status:",
            "intent_state:",
            "save_reason:",
            "occasion_days_remaining",
            "fit_confidence:",
            "comparing • active",
        ):
            self.assertNotIn(marker, blob)

    def test_stale_intent_sentence(self) -> None:
        lines = app.format_decision_evidence(
            {"evidence_used": ["intent_state: stale"]},
            {"intent_state": "stale"},
        )
        self.assertEqual(
            lines,
            [
                "This item has been saved for a long time and your current "
                "interest is uncertain."
            ],
        )

    def test_reads_payload_when_evidence_is_only_the_field_name(self) -> None:
        lines = app.format_decision_evidence(
            {"decision_evidence_used": ["comparison_status", "occasion", "fit"]},
            {
                "comparison_status": "comparing",
                "occasion_days_remaining": 9,
                "fit_confidence": "High",
            },
        )
        self.assertIn("You are comparing another shortlisted product.", lines)
        self.assertIn("You need this item in approximately 9 days.", lines)
        self.assertIn("Available fit signals are consistent.", lines)

    def test_engine_keeps_internal_keys_but_ui_copy_does_not(self) -> None:
        item = _item(
            comparison_status="comparing",
            intent_state="active",
            occasion_days_remaining=9,
        )
        fit = app.compute_fit(item, "M", 40.0, 32.0)
        decision = app.compute_next_action(item, fit)
        internal = " ".join(str(x) for x in (decision.get("evidence_used") or []))
        self.assertIn("comparison_status:", internal)
        self.assertIn("intent_state:", internal)
        lines = app.format_decision_evidence({**item, **fit, **decision}, item)
        blob = " ".join(lines)
        self.assertNotIn("comparison_status", blob)
        self.assertNotIn("intent_state", blob)
        self.assertNotIn("save_reason:", blob)
        self.assertNotIn("comparing • active", blob)


class MeasurementEvidenceTests(unittest.TestCase):
    def test_detail_rows_match_profile_closest_and_suggested(self) -> None:
        item = {"size_chart": LETTER_CHART, "fit_recommendation": "L"}
        rows = app.measurement_evidence_rows(item, "M", 40.0, 32.0)
        self.assertEqual(
            rows,
            [
                ("Your profile", "40 in"),
                ("Closest chart size", "M — 40 in"),
                ("Suggested size", "L — 42 in"),
            ],
        )
        blob = " ".join(f"{label}: {value}" for label, value in rows)
        for marker in ("<div", "</div>", "class=", "style="):
            self.assertNotIn(marker, blob)

    def test_chest_is_preferred_when_chart_has_both_dims(self) -> None:
        item = {
            "size_chart": {
                "S": {"chest": 34, "waist": 28},
                "M": {"chest": 36, "waist": 30},
                "L": {"chest": 38, "waist": 32},
                "XL": {"chest": 40, "waist": 34},
            },
            "fit_recommendation": "L",
        }
        rows = dict(app.measurement_evidence_rows(item, "M", 40.0, 32.0))
        self.assertEqual(rows["Your profile"], "40 in")
        self.assertEqual(rows["Closest chart size"], "XL — 40 in")
        self.assertEqual(rows["Suggested size"], "L — 38 in")

    def test_source_does_not_build_measure_html(self) -> None:
        source = Path(app.__file__).read_text(encoding="utf-8")
        self.assertNotIn('<div class="wd-measure">', source)
        self.assertNotIn("wd-measure", source)


class NavigationTests(unittest.TestCase):
    def test_source_does_not_open_internal_pages_in_a_new_tab(self) -> None:
        source = Path(app.__file__).read_text(encoding="utf-8")
        self.assertNotIn('target="_blank"', source)
        self.assertNotIn("target='_blank'", source)
        self.assertNotIn("st.link_button(", source)
        self.assertNotIn("st.page_link(", source)
        self.assertNotIn('href="?view=', source)
        self.assertNotIn("href='?view=", source)

    def test_required_query_states(self) -> None:
        self.assertEqual(app.query_state_for("wishlist"), {"view": "wishlist"})
        self.assertEqual(app.query_state_for("analyse"), {"view": "analyse"})
        self.assertEqual(
            app.query_state_for("detail", "and-aline-dress"),
            {"view": "detail", "item": "and-aline-dress"},
        )

    def test_nav_to_updates_query_reruns_and_keeps_session(self) -> None:
        session = {
            "custom_analysis_payload": {"product_name": "Shirt"},
            "reset_nonce": 0,
            "analyse_nonce": 2,
        }
        qp = MagicMock()
        with patch.object(app.st, "query_params", qp):
            with patch.object(app.st, "rerun") as rerun:
                with patch.object(app.st, "session_state", session):
                    app.nav_to("analyse")
        qp.from_dict.assert_called_once_with({"view": "analyse"})
        rerun.assert_called_once()
        self.assertEqual(session["custom_analysis_payload"]["product_name"], "Shirt")
        self.assertEqual(session["reset_nonce"], 0)
        self.assertEqual(session["analyse_nonce"], 2)

    def test_detail_query_includes_item_wishlist_does_not(self) -> None:
        qp = MagicMock()
        with patch.object(app.st, "query_params", qp):
            with patch.object(app.st, "rerun"):
                app.nav_to("detail", item="dnmx-skinny-jeans")
        qp.from_dict.assert_called_with(
            {"view": "detail", "item": "dnmx-skinny-jeans"}
        )
        qp.reset_mock()
        with patch.object(app.st, "query_params", qp):
            with patch.object(app.st, "rerun"):
                app.nav_to("wishlist")
        qp.from_dict.assert_called_with({"view": "wishlist"})


def _complete_deployment_payload() -> dict:
    return app.build_custom_analysis_payload(
        prod_name="Test Linen Work Shirt",
        brand="",
        category="Men's Shirts",
        price="",
        size_chart="M chest 40; L chest 42",
        reviews="True to size; Chest feels slightly snug",
        availability="",
        usual="M",
        chest_in=40.0,
        waist_in=0.0,
        save_reason="Client presentation next week",
        occasion="Yes",
        timeline="7 days",
        unsure=[],
        comparing="No",
        extra="",
    )


def _shopper_facing_text(result: dict, payload: dict | None = None) -> str:
    payload = payload or {}
    chunks = [
        result.get("fit_reason"),
        result.get("decision_reason"),
        result.get("next_step"),
        result.get("source_label"),
        result.get("decision_status"),
        " ".join(str(x) for x in (result.get("missing_fields") or [])),
        " ".join(str(x) for x in (result.get("fit_evidence_used") or [])),
        " ".join(str(x) for x in (result.get("decision_evidence_used") or [])),
        " ".join(app.live_next_steps(payload, result)),
        " ".join(app.format_decision_evidence(result, payload)),
    ]
    return " ".join(str(item) for item in chunks if item)


class DeploymentFailureTests(unittest.TestCase):
    def test_1_complete_custom_input_is_not_treated_as_missing(self) -> None:
        payload = _complete_deployment_payload()
        self.assertEqual(app.validate_custom_payload(dict(payload)), [])
        captured: dict = {}

        def fake_call(received: dict, api_key: str) -> dict:
            captured["payload"] = received
            captured["api_key"] = api_key
            return dict(_VALID_GROQ)

        with patch.object(app, "call_groq", side_effect=fake_call):
            result = app.analyse_custom_item(payload, "gsk-test")

        self.assertIs(captured["payload"], payload)
        self.assertEqual(captured["payload"]["product_name"], "Test Linen Work Shirt")
        self.assertEqual(captured["payload"]["category"], "Men's Shirts")
        self.assertIn("M chest 40", captured["payload"]["size_chart"])
        self.assertIn("True to size", captured["payload"]["reviews"])
        self.assertIn("Chest feels slightly snug", captured["payload"]["reviews"])
        self.assertEqual(captured["payload"]["usual_size"], "M")
        self.assertEqual(captured["payload"]["chest"], 40.0)
        self.assertEqual(captured["payload"]["why_saved"], "Client presentation next week")
        self.assertEqual(captured["payload"]["occasion_timing"], "7 days")
        self.assertNotEqual(result["decision_status"], "Needs more information")
        self.assertIsNone(result.get("failure_kind"))
        blob = _shopper_facing_text(result, payload).lower()
        self.assertNotIn("add a size chart", blob)
        self.assertNotIn("add review snippets", blob)
        self.assertNotIn("provide a measurement or usual size", blob)

    def test_2_actual_missing_information_lists_only_absent_fields(self) -> None:
        payload = app.build_custom_analysis_payload(
            prod_name="Test Linen Work Shirt",
            brand="",
            category="Men's Shirts",
            price="",
            size_chart="",
            reviews="",
            availability="",
            usual="M",
            chest_in=0.0,
            waist_in=0.0,
            save_reason="Client presentation next week",
            occasion="Yes",
            timeline="7 days",
            unsure=[],
            comparing="No",
            extra="",
        )
        missing = app.validate_custom_payload(dict(payload))
        result = app.analyse_custom_item(payload, "gsk-test")
        self.assertEqual(result["decision_status"], "Needs more information")
        self.assertEqual(result["failure_kind"], "missing_information")
        self.assertEqual(result["missing_fields"], missing)
        joined = " ".join(missing).lower()
        self.assertTrue(any("fit evidence" in item.lower() for item in missing))
        self.assertNotIn("product name", joined)
        self.assertNotIn("category", joined)
        self.assertNotIn("usual size", joined)
        self.assertFalse(any("size chart is missing" in item.lower() for item in missing))

    def test_3_groq_failure_is_an_analysis_service_error_not_missing_info(self) -> None:
        payload = _complete_deployment_payload()
        with patch.object(app, "call_groq", side_effect=app.GroqAPIError("down")):
            result = app.analyse_custom_item(payload, "gsk-test")
        self.assertNotEqual(result["decision_status"], "Needs more information")
        self.assertNotEqual(result.get("failure_kind"), "missing_information")
        label = str(result.get("source_label") or "")
        self.assertEqual(label, app.RULE_FALLBACK_LABEL)
        self.assertIn("unavailable", label.lower())
        self.assertTrue(result.get("is_rule_fallback"))
        self.assertEqual(result.get("name"), "Test Linen Work Shirt")
        self.assertEqual(result.get("category"), "Men's Shirts")
        blob = _shopper_facing_text(result, payload).lower()
        self.assertNotIn("needs more information", blob)
        self.assertNotIn("add a size chart", blob)
        self.assertNotIn("add review snippets", blob)
        self.assertNotIn("provide a measurement or usual size", blob)

    def test_4_invalid_model_json_is_a_processing_error(self) -> None:
        payload = _complete_deployment_payload()
        with patch.object(app, "call_groq", side_effect=app.GroqParseError("bad json")):
            result = app.analyse_custom_item(payload, "gsk-test")
        self.assertEqual(result["failure_kind"], "parse")
        self.assertEqual(result["decision_reason"], app.PARSE_FAILED_MESSAGE)
        self.assertEqual(result["fit_reason"], app.PARSE_FAILED_MESSAGE)
        self.assertNotEqual(result["decision_status"], "Needs more information")
        blob = _shopper_facing_text(result, payload)
        self.assertNotIn("Traceback", blob)
        self.assertNotIn("GroqParseError", blob)
        self.assertNotIn("add a size chart", blob.lower())
        dumped = json.dumps(result, default=str)
        self.assertNotIn("Traceback", dumped)
        self.assertNotIn("missing_information", str(result.get("failure_kind")))

    def test_5_evidence_formatting_hides_internal_keys_and_html(self) -> None:
        result = {
            "evidence_used": [
                "comparison_status: comparing",
                "intent_state: active",
                "occasion_days_remaining: 9",
                "fit_confidence: High",
                "save_reason: Client presentation next week",
            ]
        }
        item = {
            "comparison_status": "comparing",
            "intent_state": "active",
            "occasion_days_remaining": 9,
            "fit_confidence": "High",
            "save_reason": "Client presentation next week",
            "size_chart": {"M": {"chest": 40}, "L": {"chest": 42}},
            "fit_recommendation": "L",
        }
        lines = app.format_decision_evidence(result, item)
        blob = " ".join(lines)
        for marker in (
            "comparison_status",
            "intent_state",
            "save_reason:",
            "occasion_days_remaining",
            "fit_confidence:",
            "comparing • active",
        ):
            self.assertNotIn(marker, blob)
        for marker in ("<div", "</div>", "<span", "class=", "style="):
            self.assertNotIn(marker, blob)
        measure_blob = " ".join(
            f"{label}: {value}"
            for label, value in app.measurement_evidence_rows(item, "M", 40.0, None)
        )
        for marker in ("<div", "</div>", "class=", "style="):
            self.assertNotIn(marker, measure_blob)

    def test_6_measurement_match_with_size_up_reviews_is_medium(self) -> None:
        item = _item(
            size_chart={"M": {"chest": 40}, "L": {"chest": 42}},
            review_snippets=["Runs small — I had to size up."],
        )
        fit = app.compute_fit(item, "M", 40.0, None)
        self.assertEqual(fit["fit_recommendation"], "L")
        self.assertEqual(fit["fit_confidence"], "Medium")
        self.assertNotEqual(fit["fit_confidence"], "High")


if __name__ == "__main__":
    unittest.main()
