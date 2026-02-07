# Project Guide — Goose AI Financial Advisor

A deep-dive into how the system works, why it's built the way it is, and where every piece lives.

## 1. What This Project Is

An **Explainable AI** demo that conducts **MiFID II investment suitability assessments** via voice or text. It determines a client's investor profile (Very Conservative → Aggressive) through a structured questionnaire, then recommends an asset allocation and products.

**Live at**: https://goosexai.tech

**Core principle**: The LLM (Llama 3.1 8B) handles *conversation only* — asking questions, confirming answers, presenting results. All financial decisions (scoring, profiles, restrictions, allocations) are made by **deterministic Python code** that is fully auditable and reproducible.

---

## 2. File Structure

```
Venture_Lab/
├── backend/
│   ├── main.py              ← The entire backend (FastAPI, scoring engine, audit)
│   └── requirements.txt     ← Pip dependencies
├── frontend/
│   ├── goose-advisor-voice.html  ← The live frontend (standalone HTML, React via CDN)
│   ├── App.js               ← React component (used by VPS Node/React app on port 3000)
│   └── App.css              ← Styles for App.js
├── deploy_backend.py        ← Deployment script (uploads main.py to VPS, restarts)
├── patch_agent.py           ← ElevenLabs agent configuration script
├── ssh_run.py               ← SSH helper (runs commands on VPS via paramiko)
├── upload_files.py           ← SFTP upload helper
├── pyproject.toml            ← UV/pip project config
├── README.md                 ← Setup instructions
└── .gitignore
```

### Two frontends — why?

The VPS runs **two frontends** that do the same thing in different ways:

1. **`goose-advisor-voice.html`** (port 8000, served by FastAPI at `/`)
   - Standalone HTML file — no build step, no Node.js
   - Loads React + ReactDOM from CDN
   - This is what `https://goosexai.tech` serves
   - Includes: text chat, voice widget, Model Card, investment catalog, audit panel

2. **`App.js` + `App.css`** (port 3000, served by React dev server)
   - Traditional React component that requires `npm install` + `npm start`
   - Simpler UI: chat + audit panel only
   - Runs on the VPS behind nginx at port 3000
   - Used during early development, still running but not the primary frontend

---

## 3. How the Backend Works

Everything lives in **`backend/main.py`** (~714 lines). Here's what each section does:

### 3.1 Configuration (lines 1–44)

```python
LLM_URL = os.getenv("LLM_URL", "https://api.groq.com/openai")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
LLM_API_KEY = os.getenv("GROQ_API_KEY", "")
```

- Reads config from `.env` file on the VPS
- Default: Groq API with Llama 3.1 8B. Can be switched to local Ollama by changing `LLM_URL`
- Rate limiting via `slowapi` (30 requests/min for chat, 10/min for profile calculation)
- CORS allows `goosexai.tech`, `localhost:3000`, `localhost:8000`, and the old Cloudflare tunnel

### 3.2 System Prompt (lines 46–126)

The `MIFID_SYSTEM_PROMPT` is the most important piece of prompt engineering. It tells the LLM:

- **Identity**: You are ONLY a MiFID II advisor. Never break character.
- **Behavioral rules**: One question at a time, short answers (1-3 sentences for voice), confirm answers before moving on
- **Test flow**: 6 blocks of questions in strict order (Blocks 1-6)
- **Tool calling**: After all blocks, call `calculate_profile` with structured JSON answers
- **Presentation**: How to present the result conversationally

**Prompt hardening** is included (lines 49-54): the LLM refuses off-topic requests, role-play attempts, and prompt injection.

### 3.3 Voice Endpoint — `/v1/chat/completions` (lines 147–256)

This is the **OpenAI-compatible endpoint** that ElevenLabs calls.

**Flow:**
1. ElevenLabs transcribes user speech → sends chat history as OpenAI-format messages
2. Our endpoint receives the request, logs it for audit
3. Sanitizes `max_tokens` (ElevenLabs sends `-1`, Groq rejects it)
4. Forwards to Groq API with our model and API key
5. Streams the response back as SSE (Server-Sent Events)
6. ElevenLabs receives the text and converts it to speech

**Why we proxy instead of giving ElevenLabs the Groq key directly:**
- Our system prompt stays on our server (not sent to ElevenLabs)
- We can audit every single LLM call
- We can switch LLM providers without touching ElevenLabs config
- Rate limiting and security are in our control

### 3.4 Scoring Engine — `/calculate-profile` (lines 260–517)

This is the **explainability core**. Zero AI — pure deterministic Python.

**How scoring works:**
- Blocks 2-5 each assign points based on user answers (max 75 total)
- The total score maps to a profile: 0-15 = Very Conservative, 16-30 = Conservative, ... , 65-75 = Aggressive
- Block 1 (personal details) and certain answers trigger **restrictions** that cap the maximum profile level

**Restrictions (regulatory logic):**
| Condition | Effect |
|---|---|
| Age > 65 | Max profile: Moderate |
| Unemployed or Student | Max profile: Moderate Conservative |
| 3+ dependents | Profile reduced by 1 level |
| Financial score < 8/22 | Max profile: Conservative |
| Knowledge score < 5/16 | Max profile: Moderate Conservative |
| Time horizon < 1 year | Max profile: Moderate |

**Coherence check:** If client says "accept 0% loss" but picks "maximum returns" → inconsistency flagged.

**The `explanation` object** returned by this endpoint contains:
- Every question, answer, and score
- Which restrictions fired and why
- Raw profile vs final profile after adjustments
- The regulatory basis (MiFID II Art. 25)

This is what makes the system "explainable" — a regulator can audit exactly why any profile was assigned.

### 3.5 Text Chat — `/chat/{session_id}` (lines 545–615)

The text chat path for the React frontend:
1. Maintains per-session conversation history (last 10 messages)
2. Injects `MIFID_SYSTEM_PROMPT` as system message
3. Calls Groq API (same model as voice)
4. Logs to audit trail

### 3.6 Audit Endpoints (lines 643–672)

- **`GET /audit`** — Returns last 50 entries (LLM calls, profile calculations, webhooks)
- **`GET /audit/profiles`** — Returns all profile calculations with full explanations
- **`GET /audit/latest-profile`** — Most recent profile with complete explainability data

### 3.7 Profile Data (lines 262–287)

Hardcoded mappings for each profile level:
- **Allocations**: e.g., Moderate = 30% Bonds, 5% Cash, 45% Equities, 20% Alternatives
- **Products**: e.g., Moderate = "Global equity index funds (MSCI World)", "Balanced growth funds", etc.

---

## 4. How Voice Works (ElevenLabs Integration)

### Architecture

```
User speaks → Browser microphone
           → ElevenLabs WebSocket (STT: speech to text)
           → ElevenLabs "Custom LLM" calls goosexai.tech/v1/chat/completions
           → FastAPI proxies to Groq API
           → Response streams back
           → ElevenLabs (TTS: text to speech)
           → Audio plays in browser
```

### Key settings

The ElevenLabs agent (ID: `agent_3901kgmswk5ve9etvy9c1h4g2e40`) is configured with:
- **Custom LLM URL**: `https://goosexai.tech/v1`
- **API type**: `chat_completions` (ElevenLabs appends `/chat/completions` automatically)
- **Voice**: `eleven_turbo_v2` model
- **Turn detection**: VAD (Voice Activity Detection) with 2-second timeout
- **ASR keywords**: MiFID, ESG, SFDR, ETF, conservative, aggressive, etc.
- **Cascade timeout**: 15 seconds (max time to wait for LLM response)

### Configuring the agent

Use `patch_agent.py` to update ElevenLabs settings. Example: changing the Custom LLM URL, turn detection timeout, or ASR keywords. The script calls the ElevenLabs PATCH API.

Alternatively, configure via the ElevenLabs dashboard at https://elevenlabs.io.

---

## 5. Infrastructure

### VPS (Hostinger)

- **IP**: 168.231.87.2
- **OS**: Ubuntu 24.04
- **RAM**: 32GB
- **CPU**: CPU-only (no GPU)
- **SSH**: root@168.231.87.2

### What runs on the VPS

| Service | Port | Purpose |
|---|---|---|
| nginx | 80, 443 | Reverse proxy + SSL termination |
| FastAPI (uvicorn) | 8000 | Backend API |
| React dev server | 3000 | App.js frontend (legacy) |
| Ollama | 11434 | Local LLM (not used since Groq switch) |

### nginx routing (`/etc/nginx/sites-available/goose`)

```
goosexai.tech (port 443, SSL)
├── /v1/*               → localhost:8000  (FastAPI - voice LLM endpoint)
├── /chat/*             → localhost:8000  (FastAPI - text chat)
├── /audit              → localhost:8000  (FastAPI - audit)
├── /calculate-profile  → localhost:8000  (FastAPI - scoring)
├── /health             → localhost:8000  (FastAPI - health check)
└── /*                  → localhost:3000  (React frontend)
```

SSL certificate is from Let's Encrypt (certbot), auto-renews.

### DNS

Domain `goosexai.tech` (Namecheap) → A record pointing to `168.231.87.2`

### Environment variables on VPS (`/root/voice-agent/backend/.env`)

```
ELEVENLABS_API_KEY=sk_...
GROQ_API_KEY=gsk_...
LLM_URL=https://api.groq.com/openai
LLM_MODEL=llama-3.1-8b-instant
```

---

## 6. Deployment

### Deploying backend changes

1. Edit `backend/main.py` locally
2. Run `deploy_backend.py` — uploads via SFTP, restarts uvicorn, tests health endpoint
3. Or manually: `python ssh_run.py "cd /root/voice-agent && pkill uvicorn"` then restart

### Deploying frontend changes

1. Edit `frontend/goose-advisor-voice.html` locally
2. Upload via SFTP to `/root/voice-agent/frontend/public/index.html`
3. No restart needed (nginx serves static files)

### Pushing to GitHub

```bash
git add backend/main.py frontend/goose-advisor-voice.html
git commit -m "Description of change"
git push
```

---

## 7. Known Limitations

### Groq Free Tier Rate Limits

- **6,000 tokens per minute** — the MiFID II system prompt is ~1,000 tokens, so a conversation with 6+ turns can exceed this
- Symptoms: empty responses mid-conversation, voice call "dies"
- Fix: upgrade to Groq Dev tier ($0.05/million tokens) or trim conversation history

### Voice Turn Detection

- Turn timeout is 2 seconds — sometimes triggers before user finishes speaking
- Background noise can cause false triggers
- Financial terms (MiFID, SFDR) added as ASR keywords to improve recognition

### In-Memory Storage

- Audit log and session history are stored in Python memory — lost on restart
- For production: add a database (PostgreSQL, SQLite)

### Single Server

- No load balancing, no redundancy
- For production: add health monitoring, auto-restart, database persistence

---

## 8. Key Decisions and Why

| Decision | Why |
|---|---|
| **Deterministic scoring (no AI)** | Regulators require explainable, reproducible financial decisions. An LLM could give different scores for identical inputs. |
| **LLM for conversation only** | Natural voice interaction makes the assessment user-friendly, but no financial logic depends on AI output. |
| **Groq API instead of local Ollama** | CPU inference was 7-100 seconds per response — too slow for voice. Groq delivers <1 second. |
| **ElevenLabs Custom LLM** | Keeps our system prompt and audit logic on our server. ElevenLabs handles voice only. |
| **Single HTML frontend** | No build step, no Node.js needed. React via CDN keeps it simple for a demo. |
| **nginx + Let's Encrypt** | Free HTTPS required for browser microphone access (getUserMedia). |

---

## 9. API Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible chat (ElevenLabs calls this) |
| `/v1/models` | GET | Model list (ElevenLabs may query this) |
| `/chat/{session_id}` | POST | Text chat from React frontend |
| `/calculate-profile` | POST | MiFID II scoring engine (deterministic) |
| `/audit` | GET | Last 50 audit trail entries |
| `/audit/profiles` | GET | All profile calculations with explanations |
| `/audit/latest-profile` | GET | Most recent profile assessment |
| `/health` | GET | System status and architecture info |
| `/history/{session_id}` | GET | Conversation history for a session |
| `/sessions` | GET | List active sessions |
| `/webhook/elevenlabs` | POST | Post-call webhook from ElevenLabs |
| `/` | GET | Serves the frontend HTML |
