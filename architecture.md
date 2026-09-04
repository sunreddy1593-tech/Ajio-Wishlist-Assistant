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
7. **Live is one round-trip.** Analyse an Item uses a single Groq chat call (`messages=[{system},{user}]`), JSON in, two panels out. No streaming, no tools, no chain.
8. **Honesty about simulation.** Sample products, reviews, charts, availability, and product photos are prototype data and are labelled as such.

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
│  Analyse an Item: paste form → one Groq call│
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

**Views** (query param `view`; no login, no server-side routes):

| View | Purpose |
| --- | --- |
| `wishlist` | Four fictional sample saves; size profile; health strip; two panels each |
| `detail` | Evidence page for one sample item (chart, simulated reviews, decision evidence) |
| `analyse` | Form to paste a custom item |
| `live_result` | Two-panel result from Groq (or a grounded fallback) |

---

## 4. Repository layout

```
.
├── problem statement.md
├── architecture.md              # this file
├── implementation plan.md       # as-built plan + test checks
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
Paste: product,     │  Guard: no key → form still shown; submit    │
chart, reviews,     │        shows a note; Sample Wishlist works   │
size, occasion,     │  One Groq call  model openai/gpt-oss-120b    │
comparison, gaps    │  Parse JSON → normalize → render             │
                    │  try/except → never show a traceback         │
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
| **Live adapter** | Build prompt from the form, one Groq call, strip fences, `json.loads`, schema normalize |
| **Panel renderer** | Fit + next-action panels on wishlist cards, detail, and live result |

Session state is ephemeral (size widgets, analyse form nonce, live result). Nothing is persisted.

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

- The form is always shown. Submitting without `GROQ_API_KEY` shows a short note that Sample Wishlist still works; the app does not crash.
- Required to submit: product name, category, usual size.
- Optional: brand, price, size chart, reviews, availability notes (user-reported, not live inventory), measurements, why saved, occasion, timing, open uncertainties, comparison, extra context.
- **One** `chat.completions.create`: `temperature=0.3`, `max_tokens=700`, no stream, no tools.
- Model is instructed to return **only** JSON. Code fences are stripped before parse.
- Thin or unreadable replies become **Needs more information** — the app does not invent blockers.
- Failures (HTTP, missing key after submit, bad JSON) surface a short message — never a traceback.

---

## 7. Decision statuses

Demo and live share the same badge vocabulary. Demo can emit **Check fit first**. Live JSON is allowed the statuses in the Groq contract; unknown enums fall back to **Needs more information**. Aliases such as `Buy now` → Ready to buy and `Wait` → Worth waiting are accepted if a model still uses them.

| Status | Meaning |
| --- | --- |
| **Ready to buy** | Active intent, a dated need in the next 30 days, and Medium/High fit, with no open comparison and no blocking gap |
| **Check fit first** | Fit confidence is Low on the available chart/reviews (demo) |
| **Check one thing first** | An important product fact is still missing or an open fit/quality/fabric/authenticity question remains |
| **Compare first** | The save is still being compared with another option |
| **Worth waiting** | No immediate dated need; the item can stay saved |
| **Reconsider this save** | Intent is stale, or uncertain with no stated like/use |
| **Needs more information** | Live only: supplied evidence is insufficient to recommend a size or a next action |

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
| Conflicting reviews, or neither chart nor reviews help | **Low** |
| Clear review signal **or** measurement match, but not both | **Medium** |
| Measurement match **and** a clear, non-conflicting review signal | **High** |

The UI states that this supports a decision from provided data and **cannot guarantee actual fit**.

### 8.2 Next action — research-grounded rules

`compute_next_action(item, fit)` — **first match wins**. Reasons cite only sample or user-supplied fields.

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
- May appear in **evidence** for Worth waiting or Reconsider this save, explicitly tagged as age of the save / how long the sample has sat — **not a buy trigger**.
- **Never** a condition for Ready to buy.
- Health counts do **not** treat recency as urgency.

### 8.4 Simulated stock (`stock_status`)

- Displayed as **“Simulated stock: Limited sizes (not live)”** or **“Simulated stock: In stock (not live)”**.
- If `low_stock`, the engine may attach a **supporting_context** line: labelled simulated, not live inventory, **not a verified fact**, **never the reason to buy**.
- Simulated stock **does not** change `decision_status`. It cannot independently create urgency.

---

## 9. Live contract (Groq)

**Model:** `openai/gpt-oss-120b`

**System role:** wishlist decision assistant. Use only supplied fields. Do not invent blockers, scarcity, or price-watching. Do not treat stock notes as live inventory or as the sole reason to buy. Do not recommend discounts. If evidence is insufficient, use **Needs more information**.

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

The UI maps this onto the same two panels as demo. Unknown `fit_confidence` → Low. Unknown `decision_status` → Needs more information.

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
| `GROQ_API_KEY` | Analyse an Item only |

Absence of the key is a valid state: Sample Wishlist remains the product.

---

## 11. What is real, simulated, and out of scope

### Real (this MVP)

- Deterministic fit and next-action rules on Sample Wishlist
- One Groq JSON call when a key is present and the analyse form is submitted
- Session-only size profile and live result
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

Four views, one Streamlit page. Body text is ~15px. Statuses always include words, not color alone.

1. Chrome: title, Sample Wishlist / Analyse an Item, prototype banner.
2. **Sample Wishlist:** research insight, size profile + Reset, health strip, four item cards (two panels, fit note), expander “How this recommendation was generated,” links to item detail.
3. **Item detail:** save context, both panels, evidence, optional size-chart expander.
4. **Analyse an Item:** two-section form (product information, decision context), verification policy, Clear form.
5. **Live result:** two panels + evidence lists, or a Needs more information state asking for missing details.

---

## 13. Failure and safety

| Case | Behaviour |
| --- | --- |
| No Groq key | Sample Wishlist works; analyse submit shows a friendly note |
| Sample JSON missing | Error in the page, no traceback |
| Groq / parse failure | Friendly error; sample path untouched |
| Empty or unreadable model JSON | Needs more information fallback — no invented blocker |
| Reset / Clear form | Clears size widgets and any live result |

The Groq client is imported only inside the live call path so a missing optional dependency cannot take down Sample Wishlist.

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

---

## 16. What a later production system would add (not in this MVP)

- Bind to a real wishlist and size profile instead of JSON + a form
- Replace simulated `stock_status` with inventory for the recommended size (still not a sole buy reason unless product policy changes)
- Feed real size charts and review text per SKU
- Measure save → buy within 30 days, with a holdout

Keep the two-panel contract, the no-discount rule, and the rule that recency and unverified stock do not independently create urgency.
