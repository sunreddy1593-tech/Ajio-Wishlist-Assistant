# Implementation plan

How the Wishlist Decision Assistant in [`mvp/`](mvp/) was built from [`problem statement.md`](problem%20statement.md) and [`architecture.md`](architecture.md).

This is the **as-built** plan for the standalone Streamlit MVP. It is not a discovery engine, not a checkout flow, and not a discounting tool. Do not treat unchecked future ideas in §8 as shipped features.

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

**MVP proof:** Sample Wishlist works with no API key; Analyse an Item is one Groq JSON call when a key exists; sample data is labelled; deployable to Streamlit Community Cloud.

---

## 1. Guardrails (implemented)

| Guardrail | Consequence in the code |
| --- | --- |
| One tool, two questions | Every item renders **Fit Confidence** and **Buy or Wait?** |
| No monetary incentives | Rules and the Groq prompt do not recommend discounts, coupons, or “wait for a sale” |
| Standalone `mvp/` | App imports nothing from a discovery pipeline |
| Demo never depends on a model | Default path uses JSON + local rules; missing `GROQ_API_KEY` does not crash |
| Live is one round-trip | Single `messages=[{system},{user}]` call; no streaming, no tools, no chain |
| Save age is not a buy reason | `saved_days_ago` is display/evidence only; not in the Ready-to-buy condition |
| Simulated stock is not urgency | `stock_status` never changes `decision_status`; low stock is supporting context only |
| Honest simulation | Sample products, reviews, availability, and photos are labelled fictional / simulated |
| After save, before buy | No login, DB, live inventory API, payments, or notification backend |

---

## 2. File plan (shipped)

```
mvp/
  streamlit_app.py         # UI + demo engines + Groq adapter
  sample_wishlist.json     # 4 fictional AJIO-style items
  requirements.txt         # streamlit, groq
  README.md                # run locally + Community Cloud
```

**Cloud main file:** `mvp/streamlit_app.py`  
**Secret:** `st.secrets["GROQ_API_KEY"]` only — never hardcoded, never committed.

Layout *inside* `streamlit_app.py`:

1. Constants (sizes, keywords, model, system prompt, status vocab)
2. Sample load + secret read
3. Demo fit engine (`compute_fit`)
4. Demo next-action engine (`compute_next_action`)
5. Live Groq call + JSON normalize
6. Views: wishlist, item detail, analyse form, live result
7. `main()` — query-param routing

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
6. Confidence: **High** if measurement agreement **and** a clear review signal; **Medium** if one of those; **Low** if conflict or neither.
7. Return `{fit_recommendation, fit_confidence, fit_reason}`.

Shirt sizes up on “runs small”; kurta/dress stay near a true-to-size read; jeans go Low on conflict; missing measurements still return a size.

### 3.3 Next-action engine (research-grounded)

Replaces Buy now / Wait. Returns `decision_status`, `decision_reason`, `next_step`, `evidence_used`, and optional `supporting_context`.

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
- Nav: **Sample Wishlist** / **Analyse an Item** (`?view=`).
- Persistent prototype banner (simulated products, reviews, availability; fit not guaranteed).
- Static **research insight** (copy, not a live count).
- Demo inputs once: usual size, chest, waist; **Reset** clears session widgets and any live result.
- Health strip: N saved · ready to decide · need another check · worth waiting (from statuses, not from stock counts).
- Per item: metadata, simulated stock chip, reason saved, two panels, fit note, links to detail.
- Item detail: save context, both panels, chart/review evidence.
- Expander: how the recommendation was generated / what is simulated.
- Analyse form: product block + decision-context block; availability caption that notes are not live inventory.
- Live result: same two panels, or Needs more information with a request for missing details.

Decorative sample photos are in the UI. They are not a live catalogue.

### 3.5 Live adapter

1. `get_groq_api_key()` from `st.secrets["GROQ_API_KEY"]` only.
2. Form always visible; no key → friendly note on submit; Sample Wishlist still works.
3. One `Groq` client call, imported **inside** the call path: model `openai/gpt-oss-120b`, `temperature=0.3`, `max_tokens=700`, no stream, no tools.
4. System prompt: already-saved item; only supplied fields; **no discounts**; no invented scarcity or price-watching; stock notes are not live inventory and not the sole reason to buy.
5. Strip code fences → parse JSON → `normalize_live_result` (unknown enums → Low / Needs more information).
6. `try/except` around the call: friendly error, never a traceback.

### 3.6 Packaging

- `mvp/requirements.txt`: `streamlit`, `groq`
- `mvp/README.md`: local run, secrets, Community Cloud
- Root `.gitignore`: `.streamlit/secrets.toml`, `.env`, venv, `__pycache__`

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
| **Needs more information** | Live: insufficient supplied evidence |

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

The older `buy_or_wait` / `info_to_check` contract is not what the prompt asks for. Normalizer still maps leftover aliases (`Buy now`, `Wait`, `Needs more info`) so a messy reply cannot break the page.

---

## 6. Implementation notes (easy to get wrong)

- **Usual size is entered once** on Sample Wishlist and applied to every item.
- **Jeans charts are numeric.** Map S/M/L → 28/30/32 (etc.) or the closest waist; don’t drop the item if `"M"` is not a chart key.
- **Keyword false positives.** “I didn’t need to size up” is true-to-size, not run-small.
- **Price is not a feature.** Show ₹ for context; never feed it into next-action as “wait until cheaper.”
- **`saved_days_ago` is a clock on the sample, not a trigger.** Do not restore “saved ≤ 30 days → buy.”
- **Simulated `low_stock` must not flip a status to Ready to buy.** Supporting context only.
- **Live `Needs more information`** is for incomplete pastes; demo uses Check fit first / Check one thing first / Compare first when the JSON already has a situation.
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
| D15 | View evidence opens item detail with simulated review snippets labelled as such |

### Analyse an Item

| # | Check |
| --- | --- |
| L1 | No key: submit shows a note; Sample Wishlist still works |
| L2 | With key: submit a pasted item → same two panels (or friendly error) |
| L3 | Missing product name, category, or usual size: validation warning, no requirement to call the API |
| L4 | Forced API failure: message, not a stack trace |
| L5 | Availability notes caption: not live inventory |
| L6 | Insufficient evidence → **Needs more information**, not an invented blocker |
| L7 | No key in git, source, or README except the secret *name* |

---

## 8. Definition of done (this MVP)

- [x] Problem, architecture, and this plan agree: two opportunity areas → two engines → two panels
- [x] Target segment documented as high-intent delayed evaluators (interview sample ≠ whole segment)
- [x] `mvp/` runs independently (`streamlit run mvp/streamlit_app.py`)
- [x] Sample Wishlist works offline with no Groq key
- [x] Analyse an Item is one Groq JSON call gated on `st.secrets["GROQ_API_KEY"]`
- [x] Decision statuses are the grounded set (not Buy now / Wait)
- [x] Save age is context, not a buy reason
- [x] Simulated stock never independently creates urgency
- [x] No discounts in UI, rules, or prompt
- [x] Sample/simulated data is labelled
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

Full steps: [`mvp/README.md`](mvp/README.md).
