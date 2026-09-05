# Architecture

Wishlist Decision Assistant — how the product in [`problem statement.md`](problem%20statement.md) is implemented as a standalone Streamlit MVP under `mvp/`.

This document describes the **completed app**, not a future design. It does not claim features that are not in `mvp/streamlit_app.py`.

---

## 1. Behavioural target and opportunity areas

### Target segment

**High-intent delayed evaluators** — shoppers who have already saved a fashion item they genuinely consider, then postpone buying while they resolve fit, quality, timing, or comparison uncertainty.

They do not need discovery. They need enough certainty to decide, and a clear next action rather than an open-ended “later.”

Urban working professionals aged ≈30–40 were the **interview sample**. They are not the complete behavioural segment. The MVP is built for the behavioural pattern (saved, still deciding), not for that age band alone.

Budget and price can contribute to deferral in research. This MVP **cannot** offer monetary incentives, so it does not treat affordability as a problem it can solve. Price is display-only.

### Product outcome (intent, not measured in-app)

Wishlist → purchase conversion **within 30 days of saving**, at full price. The app itself does not record a purchase or a 30-day holdout. The 30-day window appears only as **occasion timing** on a save (a dated need in the next 30 days), not as “this was saved recently, so buy.”

### Two selected opportunity areas

The MVP does not address every reason a save fails to convert. It takes on two recurring, actionable barriers:

| Opportunity area | Shopper question | What the system produces |
| --- | --- | --- |
| **Fit / size confidence** | Will it fit / is it right for me? | **Panel 1 — Fit Confidence**: suggested size, High / Medium / Low, one-line reason, evidence used |
| **Decision deferral** | What should I do next with this save? | **Panel 2 — Buy or Wait?**: a **decision status**, one-line reason, concrete next step, evidence used |

A later production system could add other barriers (live inventory, price comparison, quality in full). They are out of scope here.

---

## 2. Design principles

1. **One tool, two panels.** Every assessed item is rendered as Fit Confidence and Buy or Wait? There is no deals panel, coupon, or “wait for a sale” path.
2. **No monetary incentives.** Demo rules and the live prompt must not recommend a discount, coupon, markdown, or waiting for a cheaper price.
3. **Grounded next actions.** Demo recommendations come from authored save context (intent, occasion, comparison, open questions, fit). Live recommendations may use only fields the user supplied.
4. **Save age is not a reason to buy.** `saved_days_ago` is a measurement / context signal (how long this sample has sat). It never produces **Ready to buy**.
5. **Simulated stock never independently creates urgency.** Sample `stock_status` may appear as labelled supporting context. It is never live inventory and never the sole — or independent — reason to buy.
6. **Demo never depends on a model.** Seeded JSON + deterministic rules. Missing `GROQ_API_KEY` must not crash Sample Wishlist.
7. **Live is one round-trip when a key exists.** Analyse an Item uses a single Groq chat call (`messages=[{system},{user}]`), JSON in, two panels out. No streaming, no tools, no chain. If the key is missing or Groq fails, a **labelled rule-based fallback** uses the submitted payload — it is not presented as an LLM result.
8. **Honesty about simulation.** Sample products, reviews, charts, availability, and product photos are prototype data and are labelled as such. Analyse an Item is labelled prototype testing mode; **Load an example item** is a hardcoded payload, not a live catalogue.
9. **Submitted fields are never treated as missing.** Custom analysis validates the saved form payload. Needs more information lists only fields that validation confirmed are absent. API and JSON failures are not converted into missing-information copy.
10. **Shopper-facing copy.** Internal keys (`comparison_status`, `intent_state`, …) stay in Python. The UI shows translated sentences. Measurement evidence is native Streamlit, not raw HTML tags.
11. **Same-tab navigation.** In-app views use Streamlit buttons that set `st.query_params` and `st.rerun()`. Markdown / HTML anchors are not used for internal nav (Streamlit would open a new tab).
12. **Evidence quotes supplied values.** On Analyse an Item, a “Based on” line restates what the shopper actually submitted (*Your chest measurement: 40 inches*), not the label the engine cited (*chest*). A cited signal is **dropped** when that value was never supplied, so a line can restate submitted information but never invent it.
13. **Submitted input survives a retry and an edit.** Retry re-runs the call on the stored payload without reopening the form. Edit returns to the form with every widget value written back from that payload. Neither path can silently reset a measurement to zero.

---

## 3. System context

The MVP sits **after save**, before buy. It does not create the wishlist, scrape AJIO, or place an order.

```
Shopper already saved an item
        │
        ▼
┌─────────────────────────────────────────────┐
│  Wishlist Decision Assistant (Streamlit)    │
│  mvp/streamlit_app.py                       │
│                                             │
│  Sample Wishlist: JSON + local rules        │
│  Analyse an Item: form → Groq or rule fallback │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
     Two panels per item
     Fit Confidence | Buy or Wait?
     (status badge, reason, next step, evidence)
                   │
                   ▼
     Shopper decides in-app
     (MVP stops here — no checkout)
```

**Views** (query param `view`; no login, no server-side routes). Internal hops use `nav_to` (buttons, same browser tab):

| Query | Purpose |
| --- | --- |
| `view=wishlist` | Four fictional sample saves; size profile; health strip; two panels each |
| `view=detail&item=<id>` | Evidence page for one sample item (chart, simulated reviews, decision evidence) |
| `view=analyse` | Form to enter a custom item (prototype callout; **Load an example item** prefills widgets; one `st.form`; submit builds the payload immediately) |
| `view=live_result` | Two-panel result from Groq, a labelled rule fallback, a parse error, or genuine Needs more information |

---

## 4. Repository layout

```
.
├── problem statement.md
├── architecture.md              # this file
├── implementation plan.md       # as-built plan + test checks
├── tests/test_engines.py        # unittest suite (run from repo root)
├── .streamlit/config.toml       # light theme (no secrets)
└── mvp/
    ├── streamlit_app.py         # UI + demo engines + Groq adapter
    ├── sample_wishlist.json     # 4 fictional AJIO-style items
    ├── requirements.txt         # streamlit, groq
    └── README.md                # run + deploy
```

Streamlit Community Cloud **main file:** `mvp/streamlit_app.py`.

Secret (Analyse an Item only): `st.secrets["GROQ_API_KEY"]` — never hardcoded, never in a committed file. `.streamlit/secrets.toml` is gitignored.

---

## 5. Runtime components

```
                    ┌─ Sample Wishlist (default) ──────────────────┐
                    │  sample_wishlist.json                        │
User size ──────────┤       │                                      │
Usual S–XXL         │       ▼                                      │
+ chest / waist     │  Fit engine (rules)                          │
                    │       │                                      │
                    │       ▼                                      │
                    │  Next-action engine (rules)                  │
                    │       │                                      │
                    │  Health counts from statuses                 │
                    └───────┼──────────────────────────────────────┘
                            │
                            ▼
                    Two-panel renderer
                    + item detail (evidence)
                            ▲
                    ┌───────┴─ Analyse an Item (optional) ─────────┐
Enter or load an    │  Load example prefills widgets (no submit)   │
example: product,   │  Form submit → session payload → validate     │
chart, reviews,     │  Missing fields only if validation says so   │
size, occasion,     │  Key present: one Groq call (gpt-oss-120b)   │
comparison, gaps    │  No key / Groq HTTP fail: labelled rule      │
                    │        fallback on the submitted payload     │
                    │  Bad JSON / unknown enums: processing error  │
                    │  try/except → never a traceback or API key   │
                    └──────────────────────────────────────────────┘
```

| Component | Responsibility |
| --- | --- |
| **UI shell** | AJIO-styled chrome, Sample Wishlist / Analyse an Item nav, prototype banner, research insight (static) |
| **Size profile** | Usual letter size + optional chest/waist; session-only; applied to all sample items |
| **Sample store** | Load four wishlist items from JSON |
| **Fit engine (demo)** | Chart + measurements + review keywords → size, confidence, reason |
| **Next-action engine (demo)** | Situation → `decision_status`, `decision_reason`, `next_step`, `evidence_used` |
| **Wishlist health** | Demo strip: saved count, ready to decide, need another check, worth waiting |
| **Item detail** | Same engines; shows save context, chart measurements, simulated reviews, evidence |
| **Live adapter** | Build prompt from **all** custom form fields, one Groq call (`max_tokens=1500`, compact json_schema), strip fences, `json.loads`, schema check. Compact `buy_or_wait` JSON is mapped onto the two-panel keys. Unknown enums are parse failures, not silent Needs more information |
| **Rule fallback** | Deterministic `compute_fit` / `compute_next_action` on the submitted payload when Groq is unavailable. Label: *Rule-based fallback — live AI analysis unavailable.* `is_live=False` even after item identity is copied onto the result |
| **Evidence formatter** | `format_decision_evidence` translates internal engine keys before any shopper-facing list (wishlist + detail) |
| **Custom evidence formatter** | `custom_evidence_lines` rewrites each cited label as a sentence quoting the supplied value — chart row for the suggested size, body measurements, review signals, usual size, occasion timing, price, availability. Drops a label when the value is absent |
| **Form-state restore** | `_custom_form_values` maps a payload onto the analyse widget keys. `_ensure_custom_form_state` seeds only blanks on a rerun; `restore_custom_form` overwrites, for Edit my information and for **Load an example item** (`load_example_analyse_form` → `example_analyse_payload`) |
| **Panel renderer** | Fit + next-action panels on wishlist cards, detail, and live result |

Session state is ephemeral (size widgets, analyse form nonce, `custom_analysis_payload` / result). Navigation does not wipe the size profile or the saved analyse payload. Nothing is persisted to disk.

Every analyse-form widget carries an explicit key suffixed with the analyse nonce (`ca_chest_{nonce}`, `ca_reviews_{nonce}`, …). The nonce is what **Clear form** and **Analyse another item** increment to blank the form, so a flat key would defeat clearing. Restoration reads the nonce from session state. **Edit my information** writes in the button handler **before** the rerun that rebuilds the form. **Load an example item** sits *outside* the form and *above* it, so `restore_custom_form` runs in the same run before the inputs are created. Streamlit reads session state when a widget is created, so a write after `st.form` would not reach it.

---

## 6. Two-mode design

### 6.1 Sample Wishlist (default, no API)

- **Input once:** usual size (dropdown) and chest / waist in inches (defaults 40 / 32; `0` means unused).
- For each of four seeded items: `compute_fit` then `compute_next_action`.
- **Health strip** above the list, derived from decision statuses (not from simulated stock counts).
- **No network.** If Groq is unset, this path is unaffected.

Seeded items are four **research-backed scenarios**, all labelled fictional / simulated:

| Item | Scenario | Typical demo status (usual M, chest 40, waist 32) |
| --- | --- | --- |
| AND A-line dress | Active save, dated occasion, consistent fit | **Ready to buy** |
| AURELIA kurta | Future interest, no date, still likes it | **Worth waiting** |
| DNMX skinny jeans | Stale save, conflicting fit reviews | **Check fit first** |
| NETPLAY slim shirt | Active save, still comparing an alternative; sample stock labelled limited | **Compare first** (stock is supporting context only) |

`saved_days_ago` of 5 / 12 / 60 / 150 is **how long the sample has sat**. It is shown on the card. It is not a buy trigger.

### 6.2 Analyse an Item (Live)

- The analyse page is a **prototype testing surface**, not a live AJIO product picker. A callout immediately below the heading (`ANALYSE_PROTOTYPE_CALLOUT`) states that in an integrated experience, product details, size charts, and reviews would auto-fill from the selected wishlist item, and that manual entry exists only to test products outside the sample wishlist.
- The product block is titled **Product evidence — auto-filled in the integrated experience**. Field labels state requirement clearly: Product Name, Category, and Usual Size are **required**; Size Chart, Review Snippets, Chest/Bust, and Waist are **optional, improves confidence**; Current Price and Availability Notes are **optional**.
- **Load an example item** is a secondary button *outside* the form. It prefills widgets from a hardcoded `example_analyse_payload()` (a realistic dress with a size chart, two review snippets, size profile, save reason, and occasion timing). It does **not** submit, scrape, fetch a URL, or call an API.
- The form is always shown, as **one** `st.form`. Submit (`Analyse this item`, still the primary action) immediately builds `custom_analysis_payload` from the widgets and validates **that** object.
- Required: product name, category, usual size, and **at least one** of size chart, a body measurement, or fit-related reviews. Empty strings and zero measurements become `None` and are not treated as present.
- Optional: brand, price, size chart, reviews, availability notes (user-reported, not live inventory), measurements, why saved, occasion, timing, open uncertainties, comparison, extra context. Every field is sent to Groq when a call is made.
- Missing key: analyse page shows *Live AI analysis is unavailable because the deployment secret is not configured.* Submit still runs the **rule-based fallback** on the payload. Sample Wishlist is unaffected.
- **One** `chat.completions.create` when a key exists: `temperature=0.2`, `max_tokens=1500` (`GROQ_MAX_TOKENS`), no stream, no tools. Model: `openai/gpt-oss-120b`. A 700-token cap truncated json_schema output (`json_validate_failed`).
- The call requests **strict structured output** (`response_format` `json_schema`, name `wishlist_item_analysis`, compact `ANALYSIS_SCHEMA`: `fit_recommendation`, `fit_confidence`, short `fit_reason` / `buy_wait_reason`, `buy_or_wait`, `info_to_check` max 3). The prompt says keep every field concise and return only JSON. The normalizer maps that onto the two-panel UI fields; leftover full replies with `decision_status` are still accepted.
- The prompt still asks for JSON only. Optional ` ```json ` fences are stripped, then parsed and schema-checked, so an endpoint that ignores `response_format` is still handled.
- Three failure states that must not be collapsed into one another (`failure_kind`):
  - **`validation_error`** — the submitted payload is genuinely incomplete → Needs more information, listing only fields validation confirmed are absent.
  - **`processing_error`** — Groq replied but the output could not be parsed or schema-validated → *The analysis response could not be processed. Please try again.* No fit or decision verdict is issued.
  - **`service_error`** — authentication, network, rate limit, or Groq outage → the labelled rule fallback still renders both panels from the submitted payload, with *Live analysis is temporarily unavailable. Please try again.* shown as a banner above them.
- Only `validation_error` may tell the shopper that information is missing. Neither `processing_error` nor `service_error` is converted into a Low fit-confidence verdict.
- A missing key is treated as configuration, not an outage: rule fallback with the secret-missing banner (`fallback_cause = no_secret`).
- **Recovery from a failure state is two buttons, and neither rebuilds the form.** `retry_saved_analysis()` (primary, *Retry analysis*) calls the adapter again with the stored `custom_analysis_payload` and stays on the result page; with no stored payload it records a `validation_error` result rather than navigating away. `edit_saved_analysis()` (secondary, *Edit my information*) restores the widgets from that payload, clears the stale result, and routes to `view=analyse`.
- Failures never show a traceback or the API key in the UI. Logs carry a context string, the exception type name, and `exc_info` for diagnosis. `call_groq` also logs `repr(exc)` plus HTTP `status` / `body` when the SDK exposes them, so a Cloud truncation error is visible without putting the key or payload in the log.

---

## 7. Decision statuses

Demo and live share the same badge vocabulary. Demo can emit **Check fit first**. Live JSON is allowed the statuses in the Groq contract. **Unknown enums are schema failures** (`GroqParseError`), not a silent Needs more information. Aliases such as `Buy now` → Ready to buy and `Wait` → Worth waiting are accepted if a model still uses them.

| Status | Meaning |
| --- | --- |
| **Ready to buy** | Active intent, a dated need in the next 30 days, and Medium/High fit, with no open comparison and no blocking gap |
| **Check fit first** | Fit confidence is Low on the available chart/reviews (demo) |
| **Check one thing first** | An important product fact is still missing or an open fit/quality/fabric/authenticity question remains |
| **Compare first** | The save is still being compared with another option |
| **Worth waiting** | No immediate dated need; the item can stay saved |
| **Reconsider this save** | Intent is stale, or uncertain with no stated like/use |
| **Needs more information** | Analyse path only: validation found insufficient supplied evidence. Not used for missing-key, Groq, or parse failures |

There is no **Buy now** / **Wait** status in the current engines.

---

## 8. Decision engines (demo)

These rules are the executable version of the two opportunity areas. They are not the live model.

### 8.1 Fit confidence — “is it right for me?”

**Signals**

1. Size chart vs usual size (letter sizes, or letter → waist for numeric jean charts).
2. Optional measurements: nearest chart row on chest/bust or waist (within 1 inch counts as agreement).
3. Review keywords: run-small, run-large, true-to-size. Obvious negations (e.g. “didn’t need to size up”) are ignored. **Conflict** if run-small vs run-large, or either vs true-to-size.

**Size recommendation**

- Start from measurement match if present, else usual size on the chart.
- If reviews consistently run small → size up one step.
- If reviews consistently run large → size down one step.
- If reviews conflict → do not nudge; stay near the base size.

**Confidence**

| Condition | Level |
| --- | --- |
| Measurement/chart match **and** consistent true-to-size reviews support the **same** size; no conflict | **High** |
| Only one strong source (measurement **or** reviews), **or** reviews cause a **one-size** adjustment away from the direct measurement match | **Medium** |
| Reviews conflict with each other; size chart and measurements are insufficient; or the suggested size is not on the chart (unsupported assumption) | **Low** |

Example: chest 40 in matches M (40 in); reviews say the item runs small so L (42 in) is suggested → **Medium**, not High. The signals support sizing up; they do not independently agree on L.

The UI states that this supports a decision from provided data and **cannot guarantee actual fit**.

### 8.2 Next action — research-grounded rules

`compute_next_action(item, fit, *, gaps=None)` — **first match wins**. Reasons cite only sample or user-supplied fields. When `gaps` is passed (custom-analysis fallback after validation already passed), the engine does **not** claim `size_chart is missing` solely because the shopper used reviews or measurements instead of a chart.

| Situation | Status |
| --- | --- |
| Fit confidence is **Low** | **Check fit first** |
| `comparison_status` is an active comparison | **Compare first** |
| Important information missing (no size chart, or an open fit/size/quality/fabric/authenticity question) | **Check one thing first** |
| `intent_state` is **active**, `occasion_days_remaining` is 0–30, fit is Medium or High, not comparing, no blocking gap | **Ready to buy** |
| `intent_state` is **stale**, or **uncertain** with no `save_reason` / `intended_use` | **Reconsider this save** |
| Otherwise (including no dated occasion in the next 30 days) | **Worth waiting** |

**Ready to buy is never produced from `saved_days_ago` or `stock_status`.** Those fields are not in the Ready-to-buy condition.

Comparison is evaluated **before** missing-info so an active comparison is the action even if a size question is also open (as on the sample shirt).

### 8.3 Save age (`saved_days_ago`)

- Shown on the card (“Saved N days ago”).
- May appear in **engine evidence** for Worth waiting or Reconsider this save, tagged as age of the save — **not a buy trigger**. Shopper-facing lists translate that line (no `saved_days_ago:` prefix).
- **Never** a condition for Ready to buy.
- Health counts do **not** treat recency as urgency.

### 8.4 Simulated stock (`stock_status`)

- Displayed as **“Simulated stock: Limited sizes (not live)”** or **“Simulated stock: In stock (not live)”**.
- If `low_stock`, the engine may attach a **supporting_context** line: labelled simulated, not live inventory, **not a verified fact**, **never the reason to buy**.
- Simulated stock **does not** change `decision_status`. It cannot independently create urgency.

---

## 9. Live contract (Groq)

**Model:** `openai/gpt-oss-120b`  
**Completion budget:** `max_tokens=1500` (`GROQ_MAX_TOKENS`). Keep the schema compact; evidence arrays on the Groq contract truncated the document.

**System role:** wishlist decision assistant. Use only supplied fields. Do not invent blockers, scarcity, or price-watching. Do not treat stock notes as live inventory or as the sole reason to buy. Do not recommend discounts. Do not ask the shopper to add a size chart, reviews, or measurements when those fields are already supplied. If evidence is insufficient, use **Needs more information**. Keep every field concise; respond with only the JSON object.

**Response schema** (what Groq is asked to emit)

```json
{
  "fit_recommendation": "string",
  "fit_confidence": "High | Medium | Low",
  "fit_reason": "<=25 words",
  "buy_or_wait": "Ready to buy | Check one thing first | Compare first | Worth waiting | Reconsider this save | Needs more information",
  "buy_wait_reason": "<=25 words",
  "info_to_check": ["max 3 short items"]
}
```

The normalizer maps `buy_or_wait` → `decision_status`, `buy_wait_reason` → `decision_reason`, and `info_to_check` → `next_step` so the UI still renders the two panels. If `info_to_check` is empty, `next_step` falls back to `buy_wait_reason` rather than asking for already-submitted fields. Leftover full replies (`decision_status`, evidence arrays) are still accepted. Unknown `fit_confidence` or `buy_or_wait` / `decision_status` values fail schema validation (processing error), not a silent Needs more information fallback.

Shopper-facing evidence lists run through `format_decision_evidence` (wishlist, detail) or `custom_evidence_lines` (Analyse an Item) so engine keys such as `comparison_status: comparing` never appear as raw text, and JSON-shaped rows are discarded rather than printed.

On the live result the model's own labels are the *selection* of which evidence to show, not the copy itself:

| Cited label | Rendered line (when the value was supplied) |
| --- | --- |
| `size chart` | Size M chart measurement: 40 inches |
| `chest 40 in` | Your chest measurement: 40 inches |
| `reviews` | One review describes the fit as true to size · One review reports a slightly snug chest |
| `usual size` | You usually wear size M |
| `occasion` | The item is needed in seven days |
| `availability` | You noted: … Availability is treated as simulated, never verified live stock |

Review lines count the matching snippets (*Two reviews describe…*) and name a body part only when a review names one. Rows about what is **absent** keep their existing wording (*A size chart was not provided.*).

---

## 10. Data

### Wishlist item (demo)

| Field | Role |
| --- | --- |
| `id`, `name`, `brand`, `category`, `price` | Identity; price is display-only |
| `size_chart` | Fit engine — chest/bust, waist, length in inches |
| `review_snippets` | Fit engine — run-small / run-large / true-to-size |
| `save_reason`, `intended_use` | Whether the shopper still likes / has a use for the item |
| `occasion_days_remaining` | Dated need (integer) or `null` (no date) |
| `unresolved_questions` | Open questions; fit/quality/fabric/authenticity topics can block Ready to buy |
| `comparison_status` | `comparing` vs `not_comparing` |
| `intent_state` | `active` / `uncertain` / `stale` |
| `saved_days_ago` | Display + context evidence — **not** a buy trigger |
| `stock_status`, `stock_is_simulated` | Labelled sample availability — **not** a buy trigger |

No user accounts. Shopper size lives only in the session.

### Secrets

| Key | Used when |
| --- | --- |
| `GROQ_API_KEY` | Analyse an Item only — read from `st.secrets`, never from environment variables |

Absence of the key is a valid state: Sample Wishlist remains the product; Analyse still runs the labelled rule fallback.

---

## 11. What is real, simulated, and out of scope

### Real (this MVP)

- Deterministic fit and next-action rules on Sample Wishlist
- One Groq JSON call when a key is present and the analyse form is submitted
- Labelled rule-based fallback on the submitted payload when the key is missing or Groq fails
- Session-only size profile, analyse payload, and live result
- Retry-in-place and restore-the-form recovery from every custom-analysis failure state
- Evidence lines that restate the shopper's own chart, measurements, reviews, and timing
- Automated unittest suite in `tests/test_engines.py`, including a regression class for the strict schema, the three failure states, and retry / edit state retention
- Static research-insight sentence (copy, not a live statistic)
- Prototype labelling in the banner, stock chips, review captions, expanders, and the Analyse an Item testing-mode callout
- Hardcoded **Load an example item** payload for prototype testing (not a catalogue, URL, or AJIO integration)

### Simulated / fictional (labelled in the UI)

- The four catalogue items, size charts, and review snippets
- The hardcoded **Load an example item** dress (chart, two reviews, measurements, save reason, occasion timing)
- Save context (reason, occasion, intent, comparison, open questions)
- `stock_status` / availability chips
- Product photographs (hosted decorative images, not a live catalogue feed)
- “AJIO” chrome — prototype branding, not a live AJIO integration

### Out of scope (not implemented)

- Login, accounts, database, persistence
- Live catalogue, inventory, or price APIs
- Checkout, payments, carts
- Email/push notifications or stock watches
- Scraping or a discovery-engine pipeline
- Measuring save → buy within 30 days
- Discounts, coupons, or sale-wait recommendations

The app stops when the shopper has a suggested size and a next action. It does not complete a purchase.

---

## 12. UI architecture

Four views, one Streamlit page. Body text is ~15px. Statuses always include words, not color alone. Internal navigation is **buttons**, not `<a href>` / `st.link_button`.

1. Chrome: title, **Sample Wishlist** / **Analyse an Item** (`nav_button` → `view=wishlist` or `view=analyse`), prototype banner.
2. **Sample Wishlist:** research insight, size profile + Reset, health strip, four item cards (two panels, fit note), expander “How this recommendation was generated,” **Update context** / **View evidence** → `view=detail&item=<id>`.
3. **Item detail:** **Back to wishlist** (same tab), save context, both panels, native measurement evidence (profile / closest chart size / suggested size), simulated review snippets, shopper-facing “Based on” list, optional size-chart expander.
4. **Analyse an Item:** prototype testing callout; **Load an example item** (secondary, outside the form); two-section form in one `st.form` (**Product evidence — auto-filled in the integrated experience**, then decision context) with required / optional field labels; verification policy; **Analyse this item** (primary submit); Clear form. Secret warning when the key is missing.
5. **Live result:** two panels + evidence lines that quote the submitted values; or Needs more information with **accurate** missing fields; or a processing error; or a labelled rule fallback (never silently shown as live AI). Processing and service failures offer **Retry analysis** (primary) — one more call on the stored payload, staying on the page — and **Edit my information** (secondary), which restores every widget value and returns to the form. Every widget and button on both screens has an explicit key.

---

## 13. Failure and safety

| Case | `failure_kind` | Behaviour |
| --- | --- | --- |
| Genuine missing fields | `validation_error` | Needs more information listing only fields validation confirmed are absent |
| Empty, unreadable, or schema-invalid model JSON | `processing_error` | *The analysis response could not be processed. Please try again.* — no verdict, not Needs more information, no traceback |
| Groq auth / network / rate limit / outage / HTTP 400 `json_validate_failed` | `rule_fallback` with `fallback_cause = service_error` | Rule-based panels from the submitted payload, under a *Live analysis is temporarily unavailable* banner. `call_groq` logs the original status and body |
| No Groq key | `rule_fallback` with `fallback_cause = no_secret` | Sample Wishlist works. Analyse shows the secret-missing warning. Submit returns rule-based panels under the same warning |
| Sample JSON missing | — | Error in the page, no traceback |
| **Retry analysis** | unchanged until the call returns | Re-runs the adapter on the stored payload, in place. Form widgets are never re-read, so a retry cannot drop submitted values |
| **Retry with no stored payload** | `validation_error` | Records the missing-information state instead of navigating; nothing is silently re-sent |
| **Edit my information** | cleared | Widgets rewritten from the stored payload, stale result dropped, back to `view=analyse` with chest / waist / usual size / chart / reviews / save reason / timing intact |
| Reset / Clear form | — | Clears size widgets / analyse form nonce and live result; navigation otherwise preserves session payload |
| **Load an example item** | unchanged | Prefills analyse widgets from `example_analyse_payload()` via `restore_custom_form`. Does not set `custom_analysis_payload` or call Groq until the shopper submits |

The Groq client is imported only inside the live call path so a missing optional dependency cannot take down Sample Wishlist.

Automated checks: `python -m unittest tests.test_engines` from the repository root.

---

## 14. Deployment

```
GitHub repo
    └── mvp/streamlit_app.py   ← Cloud “main file”
    └── mvp/requirements.txt
    └── mvp/sample_wishlist.json

Streamlit Community Cloud
    └── Secrets: GROQ_API_KEY   (optional; enables Analyse an Item)
```

Local: `streamlit run mvp/streamlit_app.py` from the repo root. Sample Wishlist requires nothing else. See [`mvp/README.md`](mvp/README.md).

---

## 15. How this maps back to the problem statement

| Problem-statement claim | Architectural response |
| --- | --- |
| High-intent delayed evaluators | Product sits after save; no discovery |
| Two selected barriers: fit confidence and deferral | Two panels; two engines |
| Wishlist is a passive parking lot | Health strip + explicit next action per save |
| Shoppers leave to check fit | In-app size + confidence from chart + reviews |
| Deferral stays vague | Statuses: ready / check / compare / wait / reconsider |
| Recency must not fake urgency | `saved_days_ago` is context, not Ready to buy |
| Simulated stock must not fake scarcity | Stock is labelled supporting context only |
| No discounts | Rules and prompt forbid coupons and sale-waits |
| Honest custom analysis | Submitted chart/reviews/size are used; API errors are not missing-information |
| Re-entering details is friction | Retry re-uses the stored payload; Edit restores the form instead of clearing it |
| Vague evidence does not build confidence | “Based on” lines quote the shopper's own measurements, chart row, reviews, and timing |

---

## 16. What a later production system would add (not in this MVP)

- Bind to a real wishlist and size profile instead of JSON + a form
- Replace simulated `stock_status` with inventory for the recommended size (still not a sole buy reason unless product policy changes)
- Feed real size charts and review text per SKU
- Measure save → buy within 30 days, with a holdout

Keep the two-panel contract, the no-discount rule, and the rule that recency and unverified stock do not independently create urgency.
