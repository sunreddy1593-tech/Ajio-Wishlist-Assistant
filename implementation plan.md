# Implementation plan

How the Wishlist Decision Assistant in [`mvp/`](mvp/) was built from [`problem statement.md`](problem%20statement.md) and [`architecture.md`](architecture.md).

This is the **as-built** plan for the standalone Streamlit MVP. It is not a discovery engine, not a checkout flow, and not a discounting tool. Do not treat items in §9 as shipped features.

---

## 0. What success looks like (this MVP)

**User:** a high-intent delayed evaluator — someone who already saved a fashion item — gets an in-app answer to *will it fit?* and *what should I do next?* without a store trip and without a coupon.

**Interview sample (not the whole segment):** urban working professionals ≈30–40. The product is aimed at the behavioural pattern, not that age band alone.

**Two selected opportunity areas**

| Area | Panel |
| --- | --- |
| Fit / size confidence | **Fit Confidence** — suggested size, High / Medium / Low, reason |
| Decision deferral | **Buy or Wait?** — decision status, reason, next step |

**Business intent (not instrumented in the app):** convert high-intent saves within 30 days at full price. Occasion timing of 0–30 days can support **Ready to buy**; **save age cannot**.

**MVP proof:** Sample Wishlist works with no API key; Analyse an Item is one Groq JSON call when a key exists, otherwise a **labelled** rule-based fallback on the submitted payload; sample data is labelled; shopper-facing copy never shows raw engine keys; in-app navigation stays in the same tab; deployable to Streamlit Community Cloud.

---

## 1. Guardrails (implemented)

| Guardrail | Consequence in the code |
| --- | --- |
| One tool, two questions | Every item renders **Fit Confidence** and **Buy or Wait?** |
| No monetary incentives | Rules and the Groq prompt do not recommend discounts, coupons, or “wait for a sale” |
| Standalone `mvp/` | App imports nothing from a discovery pipeline |
| Demo never depends on a model | Default path uses JSON + local rules; missing `GROQ_API_KEY` does not crash |
| Live is one round-trip when a key exists | Single `messages=[{system},{user}]` call; no streaming, no tools, no chain |
| No key / Groq HTTP fail is not missing info | Labelled rule fallback on the submitted payload (`RULE_FALLBACK_LABEL`) |
| Bad JSON / unknown enums are not missing info | Processing error: *The analysis response could not be processed. Please try again.* |
| Submitted fields are never “missing” | Validate the saved form payload; NMI lists only fields that failed validation |
| Shopper-facing copy | `format_decision_evidence` translates engine keys; measurement evidence is native Streamlit |
| Same-tab navigation | `nav_to` / `nav_button` set `st.query_params` and `st.rerun()` — no markdown / HTML anchors |
| Key from secrets only | `get_groq_api_key()` reads `st.secrets["GROQ_API_KEY"]`; environment variables are ignored |
| Save age is not a buy reason | `saved_days_ago` is display/evidence only; not in the Ready-to-buy condition |
| Simulated stock is not urgency | `stock_status` never changes `decision_status`; low stock is supporting context only |
| Honest simulation | Sample products, reviews, availability, and photos are labelled fictional / simulated |
| After save, before buy | No login, DB, live inventory API, payments, or notification backend |

---

## 2. File plan (shipped)

```
.
├── architecture.md
├── implementation plan.md
├── tests/test_engines.py      # unittest suite (run from repo root)
└── mvp/
      streamlit_app.py         # UI + demo engines + Groq adapter + fallback
      sample_wishlist.json     # 4 fictional AJIO-style items
      requirements.txt         # streamlit, groq
      README.md                # run locally + Community Cloud
```

**Cloud main file:** `mvp/streamlit_app.py`  
**Secret:** `st.secrets["GROQ_API_KEY"]` only — never hardcoded, never committed, never read from env vars.  
**Tests:** `python -m unittest tests.test_engines` from the repository root (`pytest` is not a project dependency).

Layout *inside* `streamlit_app.py`:

1. Constants (sizes, keywords, model, system prompt, status vocab, parse/fallback labels)
2. Sample load + `get_groq_api_key()` from secrets only
3. Demo fit engine (`compute_fit`)
4. Demo next-action engine (`compute_next_action`, optional `gaps=`)
5. Custom payload build + `validate_custom_payload`
6. Live Groq call + schema check (`GroqParseError` vs missing information)
7. Rule fallback (`compute_custom_analysis_fallback`)
8. Shopper evidence (`format_decision_evidence`) + native measurement rows
9. Same-tab nav (`nav_to`, `nav_button`)
10. Views: wishlist, item detail, analyse form, live result
11. `main()` — query-param routing

---

## 3. What was built

### 3.1 Sample data

`mvp/sample_wishlist.json` — four fictional saves, each with product fields **and** decision context:

`save_reason`, `intended_use`, `occasion_days_remaining` (int or `null`), `unresolved_questions`, `comparison_status`, `intent_state` (`active` / `uncertain` / `stale`), `saved_days_ago`, `stock_status`, `stock_is_simulated: true`.

| Item | Research-backed scenario | Intended status |
| --- | --- | --- |
| AND dress | Active save, occasion in 9 days, consistent fit | **Ready to buy** |
| AURELIA kurta | Future interest, no date, still likes it | **Worth waiting** |
| DNMX jeans | Stale save, conflicting fit reviews | **Check fit first** |
| NETPLAY shirt | Active save, still comparing; sample stock limited | **Compare first** |

Simulated stock is **not** the reason for any of those statuses. `saved_days_ago` is **not** the reason for Ready to buy.

Price remains display-only. Charts cover letter sizes and one numeric waist chart.

### 3.2 Fit engine

`compute_fit(item, usual_size, chest, waist)`:

1. Map usual size onto the chart (letter sizes; letter → waist for numeric jeans).
2. If chest/waist provided, pick the nearest chart row (chest/bust or waist; ≤1 inch = agreement).
3. Scan review snippets for run-small / run-large / true-to-size. Ignore obvious negations.
4. **Conflict** if those signals disagree → no size nudge, confidence **Low**.
5. Else: start from measurement match or usual size; nudge up if runs small, down if runs large.
6. Confidence:
   - **High** only when measurement agreement **and** consistent true-to-size reviews support the **same** size (no directional nudge).
   - **Medium** when there is one strong source (measurement **or** reviews), **or** when reviews cause a **one-size** adjustment off the measurement match (example: chest 40 = M, runs small → L is Medium, not High).
   - **Low** on conflict, missing chart/measurements, or a suggested size not on the chart.
7. Return `{fit_recommendation, fit_confidence, fit_reason}`.

Shirt sizes up on “runs small”; kurta/dress stay near a true-to-size read; jeans go Low on conflict; missing measurements still return a size.

### 3.3 Next-action engine (research-grounded)

Replaces Buy now / Wait. Returns `decision_status`, `decision_reason`, `next_step`, `evidence_used`, and optional `supporting_context`.

`compute_next_action(item, fit, *, gaps=None)` — when `gaps` is passed (custom-analysis fallback after validation already passed), do **not** invent `size_chart is missing` because the shopper supplied reviews or measurements instead of a chart.

**Statuses used in demo:** Ready to buy, Check fit first, Check one thing first, Compare first, Worth waiting, Reconsider this save.

**Rules — first match wins**

1. Fit **Low** → **Check fit first**
2. Actively comparing → **Compare first**
3. Important information missing (no size chart, or open fit/size/quality/fabric/authenticity question) → **Check one thing first**
4. Active intent + `occasion_days_remaining` in 0–30 + Medium/High fit + not comparing + no blocking gap → **Ready to buy**
5. Stale intent, or uncertain with no save reason / intended use → **Reconsider this save**
6. Else → **Worth waiting** (no immediate dated need)

**Hard constraints**

- Do **not** branch on price or markdown.
- Do **not** use `saved_days_ago` to create Ready to buy. It may be listed in evidence as a measurement of how long the sample has sat.
- Do **not** use `stock_status` to choose a status. Low stock may be appended as labelled supporting context only.

### 3.4 UI

- `st.set_page_config` + chrome stating the two questions; **no coupons**.
- Nav: **Sample Wishlist** / **Analyse an Item** via `nav_button` → `view=wishlist` / `view=analyse` (same tab). **View evidence** / **Update context** → `view=detail&item=<id>`. Never `st.link_button` or markdown `<a href="?view=">` (Streamlit would open a new tab).
- Persistent prototype banner (simulated products, reviews, availability; fit not guaranteed).
- Static **research insight** (copy, not a live count).
- Demo inputs once: usual size, chest, waist; **Reset** clears session widgets and any live result. Navigation does **not** wipe the size profile or a saved analyse payload.
- Health strip: N saved · ready to decide · need another check · worth waiting (from statuses, not from stock counts).
- Per item: metadata, simulated stock chip (“Simulated stock: … (not live)”), reason saved, two panels, fit note, buttons to detail.
- Item detail: **Back to wishlist**, save context, both panels, native measurement evidence (Your profile / Closest chart size / Suggested size — no raw HTML tags), simulated review snippets, shopper-facing “Based on” list via `format_decision_evidence`.
- Expander: how the recommendation was generated / what is simulated.
- Analyse form: **one** `st.form` (product block + decision-context block); submit immediately builds `custom_analysis_payload`. Availability caption that notes are not live inventory. Secret-missing warning when the key is absent.
- Live result: same two panels with translated evidence; or Needs more information listing **only actually missing** fields; or a processing error; or a labelled rule fallback (never silently shown as live AI).

Decorative sample photos are in the UI. They are not a live catalogue. Layout chrome may still use `unsafe_allow_html` for styled cards; measurement evidence and evidence lists do not.

### 3.5 Live adapter

1. `get_groq_api_key()` from `st.secrets["GROQ_API_KEY"]` only. Environment variables are ignored.
2. Form always visible as one `st.form`. Submit builds the payload immediately, then `validate_custom_payload` on **that** object. Empty strings and zero measurements become `None`.
3. Required: product name, category, usual size, and **at least one** of size chart, a body measurement, or fit-related reviews. Every `CUSTOM_PAYLOAD_FIELDS` value is sent to Groq when a call is made.
4. No key: analyse page shows `SECRET_MISSING_MESSAGE`; submit still runs `compute_custom_analysis_fallback`. Sample Wishlist is unaffected.
5. One `Groq` client call, imported **inside** the call path: model `openai/gpt-oss-120b`, `temperature=0.3`, `max_tokens=700`, no stream, no tools.
6. System prompt: already-saved item; only supplied fields; **no discounts**; no invented scarcity or price-watching; stock notes are not live inventory and not the sole reason to buy; do not ask for a size chart, reviews, or measurements that were already supplied.
7. Strip code fences → parse JSON → `validate_live_schema` / `normalize_live_result`. **Unknown enums raise `GroqParseError`** — they are not coerced to Needs more information. Aliases such as `Buy now` → Ready to buy are still accepted.
8. Three outcomes that must not collapse:
   - Genuine missing fields → Needs more information (`failure_kind="missing_information"`).
   - Missing key / Groq HTTP / SDK → labelled rule fallback (`failure_kind="rule_fallback"`, `is_live=False`, `source_label=RULE_FALLBACK_LABEL`).
   - Empty / unreadable / schema-invalid JSON → `_parse_failed_result` (`PARSE_FAILED_MESSAGE`).
9. `live_next_steps` asks only for fields that were not submitted. Parse/API/no-secret → “Please try again”.
10. Failures never show a traceback or the API key. Logs record exception **type names** only (`DEBUG_MODE = False`).

### 3.6 Packaging and tests

- `mvp/requirements.txt`: `streamlit`, `groq`
- `mvp/README.md`: local run, secrets, Community Cloud
- Root `.gitignore`: `.streamlit/secrets.toml`, `.env`, venv, `__pycache__`
- `tests/test_engines.py`: fit, decision, shopper copy, live normalizer, demo-without-key, no-discount, custom-analysis flow, Groq adapter, rule fallback, evidence formatter, measurement evidence, navigation, and the six deployment-failure cases

---

## 4. Decision statuses (as shipped)

| Status | When |
| --- | --- |
| **Ready to buy** | Active intent, dated need within 30 days, strong fit, no comparison, no blocking gap |
| **Check fit first** | Low fit confidence (demo) |
| **Check one thing first** | Missing chart or an open check-topic question |
| **Compare first** | Still comparing an alternative |
| **Worth waiting** | No immediate need; keep the save (not “wait for a sale”) |
| **Reconsider this save** | Stale or weakened intent |
| **Needs more information** | Analyse path: validation found insufficient supplied evidence (not used for Groq/parse failures) |

---

## 5. Groq JSON contract (as shipped)

```json
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
```

The older `buy_or_wait` / `info_to_check` contract is not what the prompt asks for. The normalizer still maps leftover aliases (`Buy now`, `Wait`, `Needs more info`) so a messy but **valid** reply can render. Values that are not in the allowed set after mapping fail schema validation (`GroqParseError`) and become a processing error — they are **not** silently rewritten to Needs more information.

---

## 6. Implementation notes (easy to get wrong)

- **Usual size is entered once** on Sample Wishlist and applied to every item.
- **Jeans charts are numeric.** Map S/M/L → 28/30/32 (etc.) or the closest waist; don’t drop the item if `"M"` is not a chart key.
- **Keyword false positives.** “I didn’t need to size up” is true-to-size, not run-small.
- **Fit High is not “measurement plus any review.”** A one-size nudge off the chart match is Medium.
- **Price is not a feature.** Show ₹ for context; never feed it into next-action as “wait until cheaper.”
- **`saved_days_ago` is a clock on the sample, not a trigger.** Do not restore “saved ≤ 30 days → buy.”
- **Simulated `low_stock` must not flip a status to Ready to buy.** Supporting context only; chips say “(not live)”.
- **Three custom-analysis outcomes stay distinct.** Genuine missing fields → Needs more information. Groq/key failure → labelled rule fallback. Unreadable JSON / unknown enums → processing error. Do not collapse the last two into NMI.
- **Submitted fields are present.** Do not tell the shopper to add a size chart, reviews, or measurements that validation already accepted.
- **Internal keys stay in Python.** Shopper lists go through `format_decision_evidence` (`comparison_status: comparing` → “You are comparing another shortlisted product.”).
- **Internal hops are buttons.** Markdown/HTML query-string links open a new Streamlit session in a new tab.
- **Health counts statuses**, not “how many are low in stock.”
- **Do not invent Notify-me, accounts, or live inventory** — they are not in this MVP.

---

## 7. Test plan (acceptance)

### Sample Wishlist — no API key

| # | Check |
| --- | --- |
| D1 | App starts on Sample Wishlist; no exception, no traceback |
| D2 | Prototype banner states simulated products, reviews, and availability |
| D3 | Usual **M**, chest 40, waist 32 (defaults): four items, two panels each |
| D4 | AND dress: solid fit + **Ready to buy** (dated occasion — not save age, not stock) |
| D5 | AURELIA kurta: **Worth waiting** (no immediate need) |
| D6 | DNMX jeans: **Low** fit + **Check fit first** (conflict) |
| D7 | NETPLAY shirt: size-up signal + **Compare first** (comparison — not low stock) |
| D8 | Stock chips say simulated / not live; low stock does not appear as the decision reason |
| D9 | “Saved N days ago” is visible; no copy treats recency as the reason to buy |
| D10 | Reset restores defaults and clears live result |
| D11 | Expander states rules vs LLM and what is simulated |
| D12 | Health strip: saved count + ready / check / wait |
| D13 | Each Buy or Wait panel has a text+color status badge, a reason, and a next step |
| D14 | Research insight is visible and framed as research, not a live count |
| D15 | **View evidence** is a button; it opens item detail in the **same tab** (`view=detail&item=<id>`) with simulated review snippets labelled as such |
| D16 | Item detail measurement block is native Streamlit (no raw `<div class="wd-measure">` tags) |
| D17 | Decision “Based on” lines are shopper sentences, not `comparison_status:` / `intent_state:` keys |

### Analyse an Item

| # | Check |
| --- | --- |
| L1 | No key: analyse page shows the secret-missing warning; submit still returns a labelled rule fallback on the payload; Sample Wishlist still works |
| L2 | With key: submit a pasted item → same two panels (or a processing error / labelled fallback — never a traceback) |
| L3 | Missing product name, category, or usual size: validation warning, no requirement to call the API |
| L4 | Complete paste (name, category, usual size, chart, reviews, measurements, occasion): Groq receives those fields; result is **not** Needs more information |
| L5 | Missing only fit evidence: Needs more information lists that gap only — not name/category/usual size |
| L6 | Forced Groq HTTP failure: labelled rule fallback, **not** Needs more information, **not** a stack trace |
| L7 | Empty / unreadable / unknown-enum JSON: processing error (*could not be processed*), **not** Needs more information |
| L8 | Availability notes caption: not live inventory |
| L9 | Next steps never ask for a chart/reviews/size that were actually submitted |
| L10 | No key in git, source, or README except the secret *name* |

### Automated suite

From the repository root: `python -m unittest tests.test_engines`

Covers fit confidence (including M + runs-small → L is Medium), next-action constraints, no-discount copy, custom-analysis flow, Groq adapter, rule fallback, evidence formatter, measurement rendering, same-tab nav helpers, and the six deployment-failure cases in `DeploymentFailureTests`.

---

## 8. Definition of done (this MVP)

- [x] Problem, architecture, and this plan agree: two opportunity areas → two engines → two panels
- [x] Target segment documented as high-intent delayed evaluators (interview sample ≠ whole segment)
- [x] `mvp/` runs independently (`streamlit run mvp/streamlit_app.py`)
- [x] Sample Wishlist works offline with no Groq key
- [x] Analyse an Item is one Groq JSON call gated on `st.secrets["GROQ_API_KEY"]`
- [x] Missing key / Groq HTTP failure uses a labelled rule fallback on the submitted payload
- [x] Parse / unknown-enum failures are processing errors, not Needs more information
- [x] Submitted custom fields are never listed as missing
- [x] Fit High requires agreeing measurement + true-to-size; one-size review adjustment is Medium
- [x] Shopper-facing evidence is translated; measurement evidence is native Streamlit
- [x] In-app navigation is same-tab buttons (`nav_to`)
- [x] Decision statuses are the grounded set (not Buy now / Wait)
- [x] Save age is context, not a buy reason
- [x] Simulated stock never independently creates urgency
- [x] No discounts in UI, rules, or prompt
- [x] Sample/simulated data is labelled
- [x] `python -m unittest tests.test_engines` covers the engines and the six deployment failures
- [x] README covers local run and Streamlit Community Cloud
- [x] No login, database, or notification backend

---

## 9. Explicitly later (not in this MVP)

Do **not** describe these as shipped:

- Real wishlist / size-profile APIs
- Live inventory for the recommended size
- Scraping or catalogue sync
- Holdout measurement of save → buy in 30 days
- Email, push, or stock-watch notifications
- Checkout

Keep the two-panel contract, the no-discount rule, and the rule that recency and unverified stock do not independently create urgency.

---

## 10. How to run and deploy

From the **repository root**:

```bash
pip install -r mvp/requirements.txt
streamlit run mvp/streamlit_app.py
```

Optional live key in `.streamlit/secrets.toml` (gitignored):

```toml
GROQ_API_KEY = "your_groq_key_here"
```

Streamlit Community Cloud: main file `mvp/streamlit_app.py`; same secret under App settings → Secrets.

Tests:

```bash
python -m unittest tests.test_engines
```

Full steps: [`mvp/README.md`](mvp/README.md).
