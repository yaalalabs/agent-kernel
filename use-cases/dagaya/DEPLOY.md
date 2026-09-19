# 🚀 Production Deployment Guide

This guide covers local webhook testing and production cloud deployment for the Dagaya AI Tutoring system.

---

## 1. Local Testing & Webhook Emulation

Test the Dagaya system locally before deploying to the cloud. You have two options depending on what you want to test.

### Option A: Local CLI Testing (Fastest, No Meta setup required)
Use `demo.py` to test the multi-agent routing, tool calling, and fallback logic directly in your terminal.

1. **Run the interactive demo:**
   ```bash
   uv run python demo.py
   ```
2. **Chat naturally** to see how the Triage agent routes your requests to the Tutor, Quiz, and Track agents.

### Option B: WhatsApp Webhook Emulation (ngrok)
Use this to test the actual WhatsApp integration exactly as it will run in production.

1. **Start the Dagaya webhook server:**
   ```bash
   uv run python server.py
   ```
   The server binds to `localhost:8000` by default.

2. **Expose the port via ngrok:**
   ```bash
   ngrok http 8000
   ```

3. **Configure your Meta WhatsApp Developer Dashboard:**
   - Copy the `https://xxxx.ngrok-free.app` URL from ngrok.
   - Go to your Meta App Dashboard → **WhatsApp** → **Configuration**.
   - Click **Edit Callback URL** and paste the ngrok URL.
   - Enter the `WHATSAPP_VERIFY_TOKEN` you defined in your `.env`.

---

## 2. Cloud Backend Deployment (Railway — Recommended)

[Railway](https://railway.app) is the recommended free-tier hosting platform for Dagaya due to its:
- Native Python support with zero config
- Simple GitHub integration for auto-deploy on push
- Free tier with sufficient monthly compute for moderate traffic

### Step-by-Step: Railway Deployment

1. **Push your code to GitHub** (your fork of this repo).

2. **Create a new project on Railway:**
   - Go to [railway.app](https://railway.app) and click **New Project**.
   - Select **Deploy from GitHub Repo** and authorize Railway to access your fork.

3. **Configure the build & start commands:**
   - **Build Command:** `chmod +x build.sh && ./build.sh`
   - **Start Command:** `uv run python server.py`

4. **Inject your environment secrets:**
   In the Railway project dashboard, go to **Variables** and add:
   - `GEMINI_API_KEY`
   - `GROQ_API_KEY`
   - `WHATSAPP_ACCESS_TOKEN`
   - `WHATSAPP_PHONE_NUMBER_ID`
   - `WHATSAPP_VERIFY_TOKEN`

5. **Deploy & update Meta webhook:**
   - Railway will issue a permanent public URL (e.g., `https://dagaya-production.up.railway.app`).
   - Update your Meta WhatsApp Webhook Callback URL to this new permanent URL.

---

## 3. Live Demo

The current beta deployment is live at:
**🌐 https://ulfheonar.com/dagaya**

---

## 4. Alternative Platforms

| Platform | Free Tier | Notes |
|---|---|---|
| Railway | ✅ Yes | Recommended — simple, fast |
| Render | ✅ Yes | Spin-down on inactivity |
| Fly.io | ✅ Yes | More config required |
| Oracle Cloud | ✅ Always Free | Most powerful, requires more setup |
