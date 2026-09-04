# Architecture

Wishlist Decision Assistant — how the product in [`problem statement.md`](problem%20statement.md) is implemented as a standalone Streamlit MVP.

---

## 1. What the architecture is for

The wishlist today is a **passive parking lot**. It records interest and then does nothing about the two blockers that stop a saved item from becoming a purchase:

| Blocker (problem statement) | Question the shopper is stuck on | What the system must produce |
| --- | --- | --- |
| **Confidence** | Will it fit / is it right for me? | Recommended size, High / Medium / Low, one-line reason |
| **Deferral** | Should I buy now or keep waiting? | Buy now / Wait (live: also Needs more info), one-line rationale |

**Product outcome:** wishlist → purchase conversion **within 30 days of saving**, without discounts.

**Design bet:** if fit doubt is resolved and a non-discount trigger is surfaced (stock, recency, remaining uncertainty), high-intent saves convert on-platform at full price — instead of leaking to a store trip, another app, or a stock-out.

The architecture is therefore a **decision layer on top of an already-saved item**, not a discovery, search, or pricing engine.

---

## 2. Design principles

1. **One tool, two questions.** Every item is rendered as the same two panels. No third panel for deals, coupons, or “similar items.”
2. **No monetary incentives.** Neither the demo rules nor the live prompt may recommend a discount, coupon, or price cut. The trigger is confidence + timing, not a cheaper price.
3. **Standalone and deployable.** The app lives under `mvp/`, imports nothing from `src/` or a discovery pipeline, and can be pointed at Streamlit Community Cloud as a single file.
4. **Demo never depends on a model.** Seeded data + deterministic rules so the default path works with no API key and cannot crash on a missing Groq secret.
5. **Live is one round-trip.** Custom items use a single Groq chat call (`messages=[{system},{user}]`), JSON in, two panels out. No streaming, no tools, no chain.
6. **Honesty about simulation.** Demo stock, reviews, and catalogue are sample data and are labelled as such. **Notify me** is an in-session prototype (no backend). The research insight line is static, not a live computation. The MVP does not claim live inventory.

---

## 3. System context

The MVP sits **after save**, before buy. It does not create the wishlist, scrape AJIO, or place an order.

```
Shopper already saved an item
        │
        ▼
┌───────────────────────────────────────┐
│  Wishlist Decision Assistant (Streamlit) │
│  mvp/streamlit_app.py                 │
│                                       │
│  Demo: sample JSON + local rules      │
│  Live: paste form → one Groq call     │
└───────────────┬───────────────────────┘
                │
                ▼
     Two panels per item
     Fit Confidence | Buy or Wait?
     (verdict badge + one-line why)
     Notify me (simulated, in-session)
                │
                ▼
     Shopper decides in-app
     (MVP stops here — no checkout)
```

**Out of scope (deliberate):** login, database, live catalogue/inventory APIs, images, payments, **real** notification infrastructure, and the discovery-engine pipeline. A mocked “Notify me” toggle is in the UI only; it does not send anything.

Workarounds the problem statement names (store trip, brand site, other apps, cart-as-bookmark) are what this layer is trying to make unnecessary — by answering fit and timing *where the save already lives*.

---

## 4. Repository layout

```
.
├── problem statement.md      # why the product exists
├── architecture.md           # this file
└── mvp/                      # independently deployable app
    ├── streamlit_app.py      # UI + demo rules + Groq call
    ├── sample_wishlist.json  # 4 seeded AJIO-style items
    ├── requirements.txt      # streamlit, groq
    └── README.md             # run + deploy
```

Streamlit Community Cloud **main file:** `mvp/streamlit_app.py`.

Secret (live mode only): `st.secrets["GROQ_API_KEY"]` — never hardcoded, never in a committed file.

---

## 5. Runtime components

```
                    ┌─ Demo (default) ─────────────────────────────┐
                    │  sample_wishlist.json                        │
                    │       │                                      │
User size ──────────┼──────►│  Fit engine (rules)                  │
Usual S–XXL         │       │       │                              │
+ optional          │       │       ▼                              │
chest / waist       │       │  Buy/wait engine (rules)             │
                    │       │       │                              │
                    │       │  Wishlist health (counts)            │
                    └───────┼───────┼──────────────────────────────┘
                            │       │
                            ▼       ▼
                    Same two-panel renderer
                    + verdict badge + why line
                    + Notify me (session only)
                            ▲
                    ┌───────┴─ Live (optional) ────────────────────┐
Paste: name,        │  Guard: key missing → disable, friendly note │
chart, reviews,     │  One Groq call  model openai/gpt-oss-120b    │
size, why saved,    │  Parse JSON → normalize → render             │
stock notes         │  try/except → never show a traceback         │
                    └──────────────────────────────────────────────┘
```

| Component | Responsibility |
| --- | --- |
| **UI shell** | Header, mode toggle (Demo / Try your own), size inputs, reset, research insight, “what’s simulated” note |
| **Sample store** | Load four wishlist items from JSON (name, brand, category, price, size chart, reviews, `saved_days_ago`, `stock_status`) |
| **Fit engine (demo)** | Chart + measurements + review keywords → size, confidence, reason |
| **Buy/wait engine (demo)** | Fit confidence + days since save + simulated stock → act now or wait |
| **Wishlist health** | Demo-only strip: count of saves, 60+ day stalls, low stock, fit uncertainty (Low or Medium) |
| **Verdict + why** | Badge from buy_or_wait / Low fit; one-line why from reviews + stock + recency (or live reasons) |
| **Notify me (mock)** | Per-item toggle; in-session confirmation only |
| **Live adapter** | Build prompt, one Groq call, strip fences, `json.loads`, schema normalize |
| **Panel renderer** | Shared layout so demo and live look the same |

Session state is ephemeral (size inputs, live result, reset nonce, notify toggles). Nothing is persisted.

---

## 6. Two-mode design

Mirrors a demo-first pattern: the product is usable without credentials; the model is an optional path for a custom item.

### 6.1 Demo mode (default)

- **Input once:** usual size (dropdown) and optional chest / waist in inches.
- **For each of four seeded items:** run fit rules, then buy/wait rules.
- **Above the list:** a **wishlist health** one-line strip derived from those results (how many saved, sitting 60+ days, low in stock, fit uncertainty).
- Then render two panels per item (verdict badge + why + simulated notify).
- **No network.** If Groq is unset, demo is unaffected.

Seeded items are chosen so the two engines produce **different** outcomes (the problem is not “always buy”):

| Item | Fit signal in reviews | Saved | Stock (simulated) | Typical demo outcome |
| --- | --- | --- | --- | --- |
| NETPLAY slim shirt | Runs small | 5 days | Low stock | Size up; **Buy now** (stock + fit) |
| AURELIA kurta | True to size | 60 days | In stock | Usual size; **Wait** (no urgency) |
| DNMX skinny jeans | Conflicting (runs small vs true to size) | 150 days | In stock | **Low** fit; **⚠️ Check fit first** |
| AND A-line dress | True to size | 12 days | Low stock | High fit; **✅ Buy now** |

Badges (text + color, never color alone): **✅ Buy now** if `buy_or_wait` is Buy now; **⚠️ Check fit first** if Needs more info or fit is Low; **⏳ Worth waiting** otherwise.

`saved_days_ago` of 5 / 12 vs 60 vs 150 is intentional: the business outcome is conversion **inside 30 days**. Recent high-confidence saves can be prompted; stale or uncertain saves should not be.

### 6.2 Live mode (Try your own)

- Shown in the toggle even without a key; **the form is disabled** until `GROQ_API_KEY` is in secrets, with a note that Demo still works.
- User pastes: product name/brand, optional size chart, optional reviews, size/measurements, why they saved it, stock/price notes.
- **One** `chat.completions.create`: `temperature ≈ 0.3`, low `max_tokens`, no stream, no tools.
- Model is instructed to return **only** JSON. Code fences are stripped before parse.
- Failures (missing key, HTTP, bad JSON) surface a short message — never a traceback.

Live adds `Needs more info` and `info_to_check` because a paste is incomplete in a way the seeded JSON is not. Demo does not need that third action.

---

## 7. Decision engines (demo)

These rules are the executable version of the two blockers. They are not the live model; they prove the product shape offline.

### 7.1 Fit confidence — “is it right for me?”

**Signals**

1. Size chart vs usual size (letter sizes, or letter → waist for numeric jean charts).
2. Optional measurements: nearest chart row on chest/bust or waist (within 1 inch counts as agreement).
3. Review keywords: run-small, run-large, true-to-size. **Both** run-small and run-large in the same item → conflict.

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

This is how the architecture attacks workaround #1 (going to a store “just to check fit”): a size + a stated confidence + a reason, in-app.

### 7.2 Buy or wait — “a reason to act now”

Order of rules (first match wins):

1. Fit **Low** → **Wait** — fit is uncertain, check reviews.
2. Simulated **low stock** and fit High or Medium → **Buy now** — size is low in stock and fit looks right.
3. Saved **≤ 30 days** and fit **High** → **Buy now** — still inside the conversion window, fit looks right.
4. Saved **> 90 days** → **Wait** — stale save; re-check desire and fit.
5. Else → **Wait** — in stock, no pressure; confirm fit first.

Stock here is **not** a live feed. It is a labelled simulation so the deferral panel can show a non-discount trigger. Price is displayed as context; it is not an input to the rule (no “wait for a sale”).

This is how the architecture attacks workaround #2–4 (price-checking other apps, forgetting/re-saving, parking in cart): a prompt tied to stock and recency, or an honest wait when confidence is missing.

---

## 8. Live contract (Groq)

**Model:** `openai/gpt-oss-120b`

**System role:** fashion purchase advisor for urban working professionals who already saved the item. Resolve fit and buy-vs-wait. Do not offer discounts.

**Response schema**

```json
{
  "fit_recommendation": "string",
  "fit_confidence": "High | Medium | Low",
  "fit_reason": "string",
  "buy_or_wait": "Buy now | Wait | Needs more info",
  "buy_wait_reason": "string",
  "info_to_check": ["string"]
}
```

The UI then maps this onto the same two panels as demo, including the verdict badge and why line. Unknown enums fall back to Low / Needs more info so a messy model reply cannot break the page.

---

## 9. Data

### Wishlist item (demo)

| Field | Role in the architecture |
| --- | --- |
| `name`, `brand`, `category`, `price` | Identity; price is display-only (no discount logic) |
| `size_chart` | Fit engine — chest/bust, waist, length in inches |
| `review_snippets` | Fit engine — run-small / run-large / true-to-size |
| `saved_days_ago` | Buy/wait — recency vs the 30-day outcome window |
| `stock_status` | Buy/wait — `in_stock` / `low_stock`, **simulated** |

No user accounts. Shopper size lives only in the session.

### Secrets

| Key | Used when |
| --- | --- |
| `GROQ_API_KEY` | Live mode only |

Absence of the key is a valid state: Demo remains the product.

---

## 10. UI architecture

Single page, no routes. Minimum ~15px body text. Labels always include words, not color alone.

1. Short header (the two questions, no coupons).
2. Mode toggle.
3. Persistent **sample-data** banner.
4. **Research insight** — one static sentence (prior research, not a live count).
5. Size inputs + **Reset** (demo) or paste form + **Reset** (live).
6. **Demo only — wishlist health** strip above the list (saved · 60+ days · low stock · fit uncertainty).
7. Per item: metadata (including “Low stock (simulated)”) then **Fit Confidence** | **Buy or Wait?** (verdict badge + one-line why) and a mocked **Notify me** toggle.
8. Expander: how it works / what is simulated.

Demo and live share `render_panels()` so the product is one decision surface, not two apps.

---

## 11. Failure and safety

| Case | Behaviour |
| --- | --- |
| No Groq key | Demo works; live form not usable; friendly note |
| Sample JSON missing | Error in the page, no traceback |
| Groq / parse failure | Friendly error; previous demo path untouched |
| Reset | Clears size widgets, notify toggles, and any live result |

The Groq client is imported only inside the live call path so a missing optional dependency cannot take down Demo.

---

## 12. Deployment

```
GitHub repo
    └── mvp/streamlit_app.py   ← Cloud “main file”
    └── mvp/requirements.txt
    └── mvp/sample_wishlist.json

Streamlit Community Cloud
    └── Secrets: GROQ_API_KEY   (optional; enables live)
```

Local: `streamlit run mvp/streamlit_app.py` from the repo root. Demo requires nothing else.

---

## 13. How this maps back to the problem statement

| Problem-statement claim | Architectural response |
| --- | --- |
| Wishlist captures interest but not confidence | Fit engine (rules or LLM) → size + High/Medium/Low + reason |
| No reason to act now; trigger arrives too late | Buy/wait engine uses ≤30-day recency and low-stock as triggers |
| Shoppers leave for stores to resolve fit | In-app size recommendation from chart + reviews; no store required in the MVP path |
| Sales lost to stock-outs | Low-stock + adequate fit → Buy now (simulated in demo) |
| Conversion via discounts would hurt margin | Explicit non-goal: no coupons, no “wait for sale” in rules or prompt |
| Target: 30–40, low urgency, buy when prompted | Prompt is informational (fit + stock/recency), not a markdown |
| Saves stall, get forgotten, or sell out | Demo **wishlist health** strip (60+ days, low stock, fit uncertainty) |

---

## 14. What a later production system would add (not in this MVP)

The MVP is a decision **shape**, not a platform integration.

- Bind to a real wishlist and size-profile instead of JSON + a form.
- Replace simulated `stock_status` with inventory for the recommended size.
- Turn **Notify me** into real alerts (email/push) when stock or price changes — the toggle today is in-session only.
- Feed real size charts and review text per SKU (still no scrape inside this app today).
- Measure the actual outcome: save → buy within 30 days, with a holdout.
- Still keep the two-panel contract and the no-discount rule — those are product architecture, not demo shortcuts.
