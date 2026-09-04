# Wishlist Decision Assistant

A standalone Streamlit MVP that helps urban working professionals decide on fashion wishlist items — **will it fit?** and **should I buy now or wait?** — without discounts or coupons.

This app is independent. It does not import from `src/` or the discovery-engine pipeline.

## What it does

For each saved item it shows two panels:

1. **Fit Confidence** — recommended size, High / Medium / Low confidence, and a one-line reason.
2. **Buy or Wait?** — act now vs keep waiting, with a one-line rationale (stock, recency of save, remaining fit doubt).

Two modes:

| Mode | Needs API key? | What happens |
| --- | --- | --- |
| **Demo** (default) | No | Seeded AJIO-style sample items + deterministic rules. Works offline. |
| **Try your own** (Live) | Yes — Groq | Paste a custom item; one Groq chat call returns the same two panels. |

Stock status in demo mode is **simulated sample data**, labelled as such in the UI.

## Run locally

From the **repository root**:

```bash
pip install -r mvp/requirements.txt
streamlit run mvp/streamlit_app.py
```

Demo mode needs **no API key** and should never crash.

### Optional: enable Live mode locally

Create `.streamlit/secrets.toml` in the repo root (this file is not committed):

```toml
GROQ_API_KEY = "your_groq_key_here"
```

Or, on Streamlit Community Cloud, add the same key under **App settings → Secrets**. Do not hardcode the key in the app.

## Deploy on Streamlit Community Cloud

1. Push this repo (or at least the `mvp/` folder) to GitHub. Do **not** commit an API key or a `secrets.toml` that contains one.
2. Go to [share.streamlit.io](https://share.streamlit.io) and create a new app.
3. Point the app at:
   - **Main file path:** `mvp/streamlit_app.py`
4. In **Secrets**, add:

   ```toml
   GROQ_API_KEY = "your_groq_key_here"
   ```

5. Deploy. Demo mode works even if the secret is missing; Live mode appears once the key is set.

## How to test

1. Start the app with no key set. Confirm it opens on Demo and does not error.
2. Pick a usual size (try **M**, then optionally add chest `40` and waist `30`).
3. You should see four sample items with **different** Fit + Buy/Wait outcomes:
   - NETPLAY shirt — often size-up + **Buy now** (low stock, recent save).
   - AURELIA kurta — true-to-size + **Wait** (in stock, no urgency).
   - DNMX jeans — conflicting fit reviews + **Wait**.
   - AND dress — true-to-size + **Buy now** (low stock).
4. Click **Reset** and confirm inputs clear.
5. Open **How this works / what's simulated** and confirm stock is labelled as sample data.
6. Switch to **Try your own**. Without a key you should see a friendly note, not a crash. With a key, paste an item and submit; the two panels should render (or a friendly error if the API fails).
