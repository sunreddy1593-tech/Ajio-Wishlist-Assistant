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
8. **Honesty about simulation.** Sample products, reviews, charts, availability, and product photos are prototype data and are labelled as such.
9. **Submitted fields are never treated as missing.** Custom analysis validates the saved form payload. Needs more information lists only fields that validation confirmed are absent. API and JSON failures are not converted into missing-information copy.
10. **Shopper-facing copy.** Internal keys (`comparison_status`, `intent_state`, …) stay in Python. The UI shows translated sentences. Measurement evidence is native Streamlit, not raw HTML tags.
11. **Same-tab navigation.** In-app views use Streamlit buttons that set `st.query_params` and `st.rerun()`. Markdown / HTML anchors are not used for internal nav (Streamlit would open a new tab).

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
| `view=analyse` | Form to paste a custom item (one `st.form`; submit builds the payload immediately) |
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
Paste: product,     │  Form submit → session payload → validate     │
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
| **Live adapter** | Build prompt from **all** custom form fields, one Groq call, strip fences, `json.loads`, schema check. Unknown enums are parse failures, not silent Needs more information |
| **Rule fallback** | Deterministic `compute_fit` / `compute_next_action` on the submitted payload when Groq is unavailable. Label: *Rule-based fallback — live AI analysis unavailable.* `is_live=False` even after item identity is copied onto the result |
| **Evidence formatter** | `format_decision_evidence` translates internal engine keys before any shopper-facing list |
| **Panel renderer** | Fit + next-action panels on wishlist cards, detail, and live result |

Session state is ephemeral (size widgets, analyse form nonce, `custom_analysis_payload` / result). Navigation does not wipe the size profile or the saved analyse payload. Nothing is persisted to disk.

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

- The form is always shown, as **one** `st.form`. Submit (`Analyse this item`) immediately builds `custom_analysis_payload` from the widgets and validates **that** object.
- Required: product name, category, usual size, and **at least one** of size chart, a body measurement, or fit-related reviews. Empty strings and zero measurements become `None` and are not treated as present.
- Optional: brand, price, size chart, reviews, availability notes (user-reported, not live inventory), measurements, why saved, occasion, timing, open uncertainties, comparison, extra context. Every field is sent to Groq when a call is made.
- Missing key: analyse page shows *Live AI analysis is unavailable because the deployment secret is not configured.* Submit still runs the **rule-based fallback** on the payload. Sample Wishlist is unaffected.
- **One** `chat.completions.create` when a key exists: `temperature=0.3`, `max_tokens=700`, no stream, no tools. Model: `openai/gpt-oss-120b`.
- Model is instructed to return **only** JSON (no markdown). Optional ` ```json ` fences are stripped, then parsed and schema-checked.
- Three outcomes that must not be collapsed:
  - **Genuine missing information** → Needs more information, listing only fields validation confirmed are absent.
  - **Groq / HTTP / missing key** → labelled rule fallback (not Needs more information).
  - **Unreadable JSON or unknown enums** → *The analysis response could not be processed. Please try again.* (not Needs more information).
- Failures never show a traceback or the API key. Logs record exception type names only.

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

**System role:** wishlist decision assistant. Use only supplied fields. Do not invent blockers, scarcity, or price-watching. Do not treat stock notes as live inventory or as the sole reason to buy. Do not recommend discounts. Do not ask the shopper to add a size chart, reviews, or measurements when those fields are already supplied. If evidence is insufficient, use **Needs more information**.

**Response schema**

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

The UI maps this onto the same two panels as demo. Unknown `fit_confidence` or `decision_status` values fail schema validation (processing error), not a silent Needs more information fallback.

Shopper-facing evidence lists run through `format_decision_evidence` so engine keys such as `comparison_status: comparing` never appear as raw text.

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
- Automated unittest suite in `tests/test_engines.py`
- Static research-insight sentence (copy, not a live statistic)
- Prototype labelling in the banner, stock chips, review captions, and expanders

### Simulated / fictional (labelled in the UI)

- The four catalogue items, size charts, and review snippets
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
4. **Analyse an Item:** two-section form in one `st.form` (product information, decision context), verification policy, Clear form. Secret warning when the key is missing.
5. **Live result:** two panels + translated evidence lists; or Needs more information with **accurate** missing fields; or a processing error; or a labelled rule fallback (never silently shown as live AI).

---

## 13. Failure and safety

| Case | Behaviour |
| --- | --- |
| No Groq key | Sample Wishlist works. Analyse shows the secret-missing warning. Submit uses the labelled rule fallback on the payload |
| Sample JSON missing | Error in the page, no traceback |
| Groq HTTP / SDK failure | Labelled rule fallback on the submitted payload — not Needs more information |
| Empty, unreadable, or schema-invalid model JSON | Processing error: *The analysis response could not be processed. Please try again.* — not Needs more information, no traceback |
| Genuine missing fields | Needs more information listing only fields validation confirmed are absent |
| Reset / Clear form | Clears size widgets / analyse form nonce and live result; navigation otherwise preserves session payload |

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

---

## 16. What a later production system would add (not in this MVP)

- Bind to a real wishlist and size profile instead of JSON + a form
- Replace simulated `stock_status` with inventory for the recommended size (still not a sole buy reason unless product policy changes)
- Feed real size charts and review text per SKU
- Measure save → buy within 30 days, with a holdout

Keep the two-panel contract, the no-discount rule, and the rule that recency and unverified stock do not independently create urgency.
