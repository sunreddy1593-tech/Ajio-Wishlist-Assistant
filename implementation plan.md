# Implementation plan

How to build the Wishlist Decision Assistant from [`problem statement.md`](problem%20statement.md) and [`architecture.md`](architecture.md).

This plan is the build sequence for the **standalone Streamlit MVP** under `mvp/`. It is not a discovery engine, not a checkout flow, and not a discounting tool.

---

## 0. What success looks like

**User:** a 30–40 urban professional who already saved a fashion item gets an in-app answer to *will it fit?* and *should I buy now or wait?* — without a store trip.

**Business:** convert high-intent saves to purchases **within 30 days**, at full price (no coupons).

**MVP proof:** one page, two panels per item, two modes (Demo without a key; Live with one Groq call), labelled sample data, deployable to Streamlit Community Cloud.

---

## 1. Guardrails (do not violate while implementing)

Taken from the architecture; treat as hard constraints.

| Guardrail | Implementation consequence |
| --- | --- |
| One tool, two questions | Every item renders **Fit Confidence** and **Buy or Wait?** only |
| No monetary incentives | Rules and the Groq prompt must not recommend discounts, coupons, or “wait for a sale” |
| Standalone `mvp/` | No imports from `src/` or a discovery pipeline |
| Demo never depends on a model | Default path uses JSON + local rules; missing `GROQ_API_KEY` must not crash |
| Live is one round-trip | Single `messages=[{system},{user}]` call; no streaming, no tools, no chain |
| Honest simulation | Stock, reviews, and catalogue in demo are sample data and labelled as such |
| After save, before buy | No login, DB, live inventory API, images, payments, or notifications |

---

## 2. File plan

Create only this independently deployable slice:

```
mvp/
  streamlit_app.py         # UI + demo engines + Groq adapter
  sample_wishlist.json     # 4 AJIO-style seeded items
  requirements.txt         # streamlit, groq
  README.md                # run locally + Community Cloud
```

**Cloud main file:** `mvp/streamlit_app.py`  
**Secret:** `st.secrets["GROQ_API_KEY"]` only — never hardcoded, never committed.

Suggested module layout *inside* `streamlit_app.py` (single file is required; keep sections distinct):

1. Constants (sizes, keywords, model, system prompt)
2. Sample load + secret read
3. Demo fit engine
4. Demo buy/wait engine
5. Live Groq call + JSON normalize
6. Shared two-panel renderer
7. `main()` UI

---

## 3. Phased build

Do the phases in order. Demo must be shippable before Live is added.

### Phase A — Seed the parking lot (data)

**Why:** the product sits on items already saved. Demo needs four realistic saves so fit and timing can disagree.

**Build**

1. Author `mvp/sample_wishlist.json` with **four** AJIO-style products, e.g.:
   - Men’s slim-fit shirt
   - Women’s kurta
   - Jeans (numeric waist chart)
   - Dress
2. Each item must include: `name`, `brand`, `category`, `price`, `size_chart` (inches), `review_snippets` (2–3, fit/quality), `saved_days_ago`, `stock_status` (`in_stock` / `low_stock`).
3. Seed for **divergent outcomes**, not four “buy now”s:

| Item | Review mix | `saved_days_ago` | `stock_status` | Intended demo story |
| --- | --- | --- | --- | --- |
| Shirt | Runs small | 5 | `low_stock` | Size up; act now (stock + recency) |
| Kurta | True to size | 60 | `in_stock` | Fit OK; wait (no trigger) |
| Jeans | Runs small **and** true to size | 150 | `in_stock` | Low confidence; wait |
| Dress | True to size | 12 | `low_stock` | Fit OK; act now (stock) |

4. Include at least one **runs small** signal and one **true to size** signal across the set. Price is display-only.

**Done when:** JSON loads; charts cover letter sizes and at least one numeric waist chart; days include values on both sides of the 30-day window (and one stale >90).

---

### Phase B — Fit engine (blocker 1: confidence)

**Why:** replace the store-trip workaround with an in-app size + confidence + reason.

**Build** `compute_fit(item, usual_size, chest, waist)`:

1. Map usual size onto the chart (letter sizes; letter → waist for numeric jeans).
2. If chest/waist provided, pick the nearest chart row (chest/bust or waist; ≤1 inch = agreement).
3. Scan review snippets for run-small / run-large / true-to-size keywords. Ignore obvious negations (e.g. “didn’t need to size up”).
4. **Conflict** if run-small vs run-large, or either vs true-to-size → no size nudge, confidence **Low**.
5. Else: start from measurement match or usual size; nudge up if runs small, down if runs large.
6. Confidence:
   - **High** — measurement agreement **and** a clear, non-conflicting review signal
   - **Medium** — one of those two, not both
   - **Low** — conflict, or neither signal
7. Return `{fit_recommendation, fit_confidence, fit_reason}` with a **one-line** reason.

**Done when:** shirt sizes up on “runs small”; kurta/dress stay near usual on “true to size”; jeans go Low on conflict; missing measurements still return a size (never throw).

---

### Phase C — Buy/wait engine (blocker 2: deferral)

**Why:** surface a non-discount trigger (stock, recency) or an honest wait. Aligns with conversion **within 30 days**.

**Build** `compute_buy_or_wait(item, fit)` — first match wins:

1. Fit **Low** → **Wait** — “Wait — fit is uncertain, check reviews”
2. `low_stock` and fit High or Medium → **Buy now** — “Buy now — your size is low in stock and fit looks right”
3. `saved_days_ago <= 30` and fit **High** → **Buy now** (inside the outcome window)
4. `saved_days_ago > 90` → **Wait** (stale save)
5. Else → **Wait** (in stock, no pressure)

Do **not** branch on price or markdown.

**Done when:** the four seeds produce mixed Buy now / Wait (not a single recommendation). Stock is never treated as live inventory.

---

### Phase D — UI shell (one page, two panels)

**Why:** the intervention is the two-panel decision, not a dashboard.

**Build** in `main()`:

1. `st.set_page_config` + short header stating the two questions and **no coupons**.
2. Mode toggle: **Demo** (default) / **Try your own**.
3. Persistent banner: sample data, not live catalogue/stock.
4. Demo inputs (once, applied to all items): usual size dropdown; optional chest; optional waist.
5. **Reset** clears inputs and any live result (nonce/session pattern).
6. For each item: metadata (₹ price, days saved, “Low stock (simulated)” / “In stock (simulated)”) then two columns via a shared `render_panels()`.
7. Expander: “How this works / what’s simulated”.
8. No images, no login, no extra pages.

**Done when:** Demo is readable uncluttered; both panels labelled; sample/simulated labelling is visible without opening the expander.

---

### Phase E — Wire Demo end-to-end (no API)

**Build**

1. Load JSON from `Path(__file__).parent / "sample_wishlist.json"`.
2. On missing/invalid file: friendly error, no traceback.
3. Loop items → fit → buy/wait → `render_panels`.
4. Optional expander of the review snippets used.

**Done when:** `streamlit run mvp/streamlit_app.py` with **no key** never crashes; four items show distinct Fit + Buy/Wait stories.

---

### Phase F — Live adapter (one Groq call)

**Why:** same two questions for a pasted item the seeds don’t cover. Optional; Demo remains the product if the key is absent.

**Build**

1. `get_groq_api_key()` from `st.secrets["GROQ_API_KEY"]` only. Empty/missing → `None`.
2. If no key: keep the mode toggle visible; **do not run the form**; friendly note that Demo works without a key.
3. Form fields: product name/brand (required), size chart (optional), reviews (optional), size/measurements (required), why saved (optional), stock/price notes (optional).
4. One `Groq` client call, imported **inside** the call path:
   - model `openai/gpt-oss-120b`
   - `messages=[{system},{user}]`
   - `temperature=0.3`, `max_tokens` ~400
   - no stream, no tools
5. System prompt: urban professionals who already saved the item; resolve fit and buy-vs-wait; **no discounts**; respond with **only** JSON in the architecture schema (`Needs more info` + `info_to_check` allowed).
6. Strip code fences → `json.loads` → `normalize_live_result` (unknown enums → Low / Needs more info).
7. `try/except` around the whole call: friendly error, never a traceback.
8. Render with the **same** `render_panels()`.

**Done when:** no key → no crash on Live; with key → two panels or a friendly error; prompt never asks the model to discount.

---

### Phase G — Packaging and deploy

**Build**

1. `mvp/requirements.txt`: `streamlit`, `groq` (minimum versions fine).
2. `mvp/README.md`: local run from repo root; secrets via `.streamlit/secrets.toml` (not committed); Community Cloud main file `mvp/streamlit_app.py` + `GROQ_API_KEY` in app Secrets.
3. Root `.gitignore`: `.streamlit/secrets.toml`, `.env`, venv, `__pycache__`.

**Done when:** a third person can run Demo from the README with no key, and deploy by pointing Cloud at `mvp/streamlit_app.py`.

---

### Phase H — Decision surface (UI layers on the existing engines)

**Why:** make the parking-lot problem visible at a glance, and make each item’s verdict scannable — without new backends.

**Build** (do not change Demo/Live structure or engines’ inputs):

1. **Wishlist health** (demo, above the item list): one-line strip from `saved_days_ago`, `stock_status`, and per-item `fit_confidence` — e.g. `4 items saved · 2 sitting 60+ days · 2 low in stock · 1 with fit uncertainty`. Not a chart.
2. **Verdict badge** (both modes), text + color: `✅ Buy now` / `⏳ Worth waiting` / `⚠️ Check fit first` (Needs more info **or** fit Low).
3. **One-line why** under the badge from existing fit/buy reasons (and review/stock/recency when present).
4. **Notify me** toggle per item — in-session confirmation only, labelled simulated.
5. **Research insight** — one static sentence, framed as prior research, not a live count.
6. Body text ≥14px equivalent; never color alone.

**Done when:** Demo with no key shows health + badges + why + notify; Live uses the same badge/why/notify; no inventory, accounts, images, or notification infra.

---

## 4. Implementation notes (easy to get wrong)

- **Usual size is entered once** in Demo and applied to every item — do not put a size widget inside each card.
- **Jeans charts are numeric.** Map S/M/L → 28/30/32 (etc.) or the closest waist measurement; don’t drop the item if `"M" not in size_chart`.
- **Keyword false positives.** “I didn’t need to size up” is true-to-size, not run-small. Scan with a short negation window.
- **Price is not a feature.** Show ₹ for context; never feed it into buy/wait as “wait until cheaper.”
- **30-day window is a rule input** (`saved_days_ago`), not a timer or notification job.
- **Live `Needs more info`** is for incomplete pastes; Demo should not invent that third action if rules can already decide.
- **Notify me is not a backend.** It only flips session state. Do not add email, queues, or inventory watches.
- **Health counts Medium as uncertainty** as well as Low — hesitation, not only a broken size call.

---

## 5. Test plan (acceptance)

Run after Phase E (Demo) and again after Phase F (Live).

### Demo — no API key

| # | Check |
| --- | --- |
| D1 | App starts; default mode is Demo; no exception, no traceback |
| D2 | Usual **M**, optional chest 40 / waist 30: four items, two panels each |
| D3 | Shirt: size-up signal + **Buy now** (low stock) |
| D4 | Kurta: true-to-size + **Wait** (in stock, 60 days) |
| D5 | Jeans: **Low** fit + **Wait** (conflict and/or stale) |
| D6 | Dress: solid fit + **Buy now** (low stock) |
| D7 | Stock labelled simulated; banner says sample data |
| D8 | Reset restores defaults |
| D9 | “How this works” states rules vs LLM and what is fake |
| D10 | Health strip above the list with four derived counts |
| D11 | Each Buy or Wait panel leads with a text+color verdict badge |
| D12 | A one-line why is visible under the badge |
| D13 | Notify me toggle shows the simulated confirmation; Reset clears it |
| D14 | Research insight is visible and framed as prior research |

### Live

| # | Check |
| --- | --- |
| L1 | No key: Live disabled/noted; Demo still works |
| L2 | With key: submit a pasted item → same two panels (or friendly error) |
| L3 | Missing product or size: validation warning, no API call required |
| L4 | Forced API failure: message, not a stack trace |
| L5 | No key in git, source, or README except the secret *name* |

---

## 6. Definition of done (this MVP)

- [ ] Problem, architecture, and this plan agree: two blockers → two engines → two panels
- [ ] `mvp/` runs independently (`streamlit run mvp/streamlit_app.py`)
- [ ] Demo works offline with no Groq key
- [ ] Live is one Groq JSON call gated on `st.secrets["GROQ_API_KEY"]`
- [ ] No discounts in UI, rules, or prompt
- [ ] Sample/simulated data is labelled
- [ ] README covers local run and Streamlit Community Cloud
- [ ] No login, database, images, or `src/` imports
- [ ] Demo health strip + verdict badges + why line + simulated notify (Phase H)

---

## 7. Explicitly later (not this plan)

From architecture §14 — do **not** implement in the MVP:

- Real wishlist / size-profile APIs
- Live inventory for the recommended size
- Scraping or catalogue sync
- Holdout measurement of save → buy in 30 days
- Push reminders when stock drops (**Notify me** in the MVP is simulated only)

Keep the two-panel contract and the no-discount rule if those are added later; they are product architecture, not demo shortcuts.
