# Wishlist Decision Assistant

A standalone Streamlit MVP for **high-intent delayed evaluators** — shoppers who already saved a fashion item and are postponing the buy while they resolve fit or timing.

It answers two selected opportunity areas, without discounts or coupons:

1. **Fit / size confidence** — will it fit / is it right for me?
2. **Decision deferral** — what should I do next with this save?

Urban working professionals aged ≈30–40 were the interview sample. They are not the complete behavioural segment.

This app lives in `mvp/`. It does not log in, check out, or call live inventory.

## What it does

For each item it shows two panels:

1. **Fit Confidence** — suggested size, High / Medium / Low, a one-line reason, and what evidence was used. Fit is not guaranteed.
2. **Buy or Wait?** — a **decision status**, a one-line reason, and a next step.

**Decision statuses**

| Status | Meaning |
| --- | --- |
| Ready to buy | Active intent, a dated need in the next 30 days, and Medium/High fit |
| Check fit first | Fit confidence is Low (sample rules) |
| Check one thing first | An important fact or open sizing/quality question is still missing |
| Compare first | Still comparing another option |
| Worth waiting | No immediate need; keep the save (not “wait for a sale”) |
| Reconsider this save | Stale or weakened intent |
| Needs more information | Live mode only: not enough supplied evidence |

**Save age** (`saved_days_ago`) is shown as context — how long the sample has sat. It is **not** a reason to buy.

**Simulated stock** is labelled in the UI. It is **not** live inventory and **never** independently creates urgency or a Ready to buy status.

Two surfaces:

| Surface | Needs API key? | What happens |
| --- | --- | --- |
| **Sample Wishlist** (default) | No | Four fictional AJIO-style saves + deterministic rules. Works offline. |
| **Analyse an Item** | Yes — Groq | Paste a custom item; one Groq chat call returns the same two panels. |

## What is real, simulated, and out of scope

**Real:** the local decision rules; one Groq call when a key is set; your size profile and pasted fields for this session.

**Simulated / fictional (labelled in the UI):** sample products, size charts, review snippets, save context, availability chips, and decorative product photos. The research insight line is static copy, not a live statistic.

**Out of scope:** login, database, live AJIO catalogue or stock, checkout, payments, notifications, discounts.

## Run locally

From the **repository root**:

```bash
pip install -r mvp/requirements.txt
streamlit run mvp/streamlit_app.py
```

Sample Wishlist needs **no API key** and should never crash.

### Optional: enable Analyse an Item locally

Create `.streamlit/secrets.toml` in the repo root (this file is not committed):

```toml
GROQ_API_KEY = "your_groq_key_here"
```

Do not hardcode the key in the app.

## Deploy on Streamlit Community Cloud

1. Push this repo (or at least the `mvp/` folder) to GitHub. Do **not** commit an API key or a `secrets.toml` that contains one.
2. Go to [share.streamlit.io](https://share.streamlit.io) and create a new app.
3. Point the app at:
   - **Main file path:** `mvp/streamlit_app.py`
4. In **Secrets**, add:

   ```toml
   GROQ_API_KEY = "your_groq_key_here"
   ```

5. Deploy. Sample Wishlist works even if the secret is missing. Analyse an Item works once the key is set.

## How to test

1. Start with no key. Confirm Sample Wishlist opens and does not error. Confirm the prototype banner says products, reviews, and availability are simulated.
2. Keep usual size **M**, chest `40`, waist `32` (the defaults). You should see four **different** next actions:
   - AND dress — **Ready to buy** (upcoming occasion + fit — not save age, not stock).
   - AURELIA kurta — **Worth waiting** (no immediate need).
   - DNMX jeans — **Check fit first** (conflicting fit reviews).
   - NETPLAY shirt — **Compare first** (still comparing; limited sample stock is supporting context only).
3. Confirm stock chips say simulated / not live, and that “Saved N days ago” is not used as the buy reason.
4. Click **Reset** and confirm inputs restore.
5. Open **How this recommendation was generated** and confirm demo uses rules, live uses one Groq call, and stock is not treated as live.
6. Open **View evidence** on an item; simulated review snippets should be labelled.
7. Switch to **Analyse an Item**. Without a key, submit should show a friendly note, not a crash. With a key, paste an item and submit; the two panels should render (or a friendly error if the API fails). Thin evidence should yield **Needs more information**, not an invented blocker.
