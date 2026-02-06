# Goose AI Financial Advisor

Explainable AI-powered MiFID II investment suitability assessment. Uses an on-premises LLM (Llama 3.1 8B) for conversation and a deterministic scoring engine for all financial decisions.

## Architecture

```
frontend/
  goose-advisor-voice.html   Single-file app (React via CDN, no build step)

backend/
  main.py                    FastAPI server: LLM proxy, scoring engine, audit log
  requirements.txt           Pip fallback dependencies
```

- **LLM**: Ollama running Llama 3.1 8B locally - handles conversation only
- **Scoring Engine**: Deterministic Python code - calculates investor profiles, allocations, restrictions
- **Voice** (optional): ElevenLabs Conversational AI for speech-to-text and text-to-speech

## Quick Start (UV)

### Prerequisites

1. **UV** - Python package manager:
   ```bash
   # macOS / Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Windows
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. **Ollama** - Local LLM runtime:
   - Download from [ollama.com](https://ollama.com/download)
   - Pull the model:
     ```bash
     ollama pull llama3.1:8b
     ```

### Run

```bash
git clone https://github.com/inigomartos/Goose_for_claude.git
cd Goose_for_claude
uv run uvicorn backend.main:app --port 8000
```

Open **http://localhost:8000** in your browser.

### Alternative (pip)

```bash
git clone https://github.com/inigomartos/Goose_for_claude.git
cd Goose_for_claude
pip install -r backend/requirements.txt
uvicorn backend.main:app --port 8000
```

## Voice Mode (Optional)

Voice mode requires an ElevenLabs API key and an HTTPS connection (browsers require HTTPS for microphone access).

1. Create a `.env` file in the project root:
   ```
   ELEVENLABS_API_KEY=your_key_here
   ```

2. For local development, voice will only work on `localhost` (which browsers treat as a secure context). If accessing from another device on your network, you'll need HTTPS (e.g., via a Cloudflare tunnel).

Text chat works on any connection (HTTP or HTTPS).

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model to use for conversation |

## Key Pages

- **AI Advisor** - Text and voice chat for the suitability assessment
- **Model Card** - Full explainability documentation: scoring methodology, risk analysis, test results, and roadmap
- **Audit Trail** - Real-time scoring breakdown, restrictions, and decision log (inside AI Advisor page)

## Disclaimer

This is a **demonstration system** for educational and research purposes. It is not financial advice and has not been validated by financial regulators. See the Model Card page for a full risk analysis.
