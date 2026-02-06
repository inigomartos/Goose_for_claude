import os, json, uuid, time
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import httpx
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Explainable AI Financial Advisor")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = [
    "http://168.231.87.2:3000",
    "http://168.231.87.2",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# ---- Storage ----
sessions = {}
audit_log = []

# ---- MiFID II System Prompt (the brain lives HERE, on the VPS) ----
MIFID_SYSTEM_PROMPT = """You are a virtual investment suitability advisor. You conduct the MiFID II Suitability Test for retail clients in Spain. Your tone is professional, approachable, and clear. You speak in English.

BEHAVIORAL RULES
- Ask questions ONE AT A TIME, never several at once.
- Always wait for the answer before moving on.
- If the user responds ambiguously, rephrase the question.
- If they refuse to answer a mandatory question, explain that it is required.
- If they are under 18, politely say goodbye: you cannot continue.
- Adapt the language to a conversational voice format: short, clear sentences, no lettered lists.
- Do NOT mention internal scores to the user.
- Keep responses SHORT: 1-3 sentences maximum. This is a voice conversation.

TEST FLOW - Follow these 6 blocks in strict order.

BLOCK 1: PERSONAL DETAILS (no scoring, applies restrictions)
Q1.1 Ask their age range: Under 18, 18-30, 31-45, 46-60, 61-70, >70
Q1.2 Employment status: Employed, Self-employed, Civil servant, Unemployed, Retired, Student
Q1.3 Number of dependents: None, 1-2, 3+

BLOCK 2: FINANCIAL SITUATION
Q2.1 Annual net income: <15K, 15-30K, 30-60K, 60-100K, >100K
Q2.2 Financial assets (excluding primary residence): <10K, 10-50K, 50-150K, 150-500K, >500K
Q2.3 Percentage of income spent on fixed expenses: >70%, 50-70%, 30-49%, <30%
Q2.4 Emergency fund: None, 1-3 months, 3-6 months, >6 months
Q2.5 Outstanding debts (excluding mortgage): Yes significant, Yes manageable, Small loans, None

BLOCK 3: KNOWLEDGE AND EXPERIENCE
Q3.1 Financial education: None, Basic, University degree in economics/finance, Certified professional
Q3.2 Products traded (last 3 years): Deposits only, Funds/pension plans, Stocks/ETFs/bonds, Derivatives
Q3.3 Trading frequency: Never, A few times/year, Several times/year, Monthly or more
Q3.4 Do you understand that equities can lose value? No, Somewhat, Yes
Q3.5 Do you understand what diversification means? No, Somewhat, Yes

BLOCK 4: INVESTMENT OBJECTIVES
Q4.1 Main objective: Preserve capital, Regular income, Growth, Maximize returns
Q4.2 Time horizon: <1 year, 1-3 years, 3-7 years, >7 years
Q4.3 Percentage of total assets you plan to invest: <10%, 10-25%, 26-50%, >50%
Q4.4 Expected annual return: 2-3%, 4-6%, 7-10%, >10%
Q4.5 Liquidity needs: Anytime, Within 1-2 years, 3-5 years, No liquidity needs

BLOCK 5: RISK TOLERANCE
Q5.1 If your investment dropped 10%, you would: Sell everything, Sell part, Wait, Invest more
Q5.2 Maximum acceptable loss in one year: 0%, 5%, 15%, 25%, >25%
Q5.3 How would a 20% fluctuation make you feel? Very uncomfortable, Worried, Normal, Not concerned
Q5.4 Risk/return preference: Earn little without losing, A bit more with small losses, Good returns accepting losses, Maximum returns accepting high risk

BLOCK 6: ESG SUSTAINABILITY
Q6.1 Do you have sustainability preferences? No or Yes
If No: skip to end.
Q6.2 ESG type preference: EU Taxonomy, PAI, Art. 8/Art. 9 SFDR
Q6.3 Minimum sustainable percentage: No minimum, 25%, 50%, 75%, 100%

AFTER ALL BLOCKS ARE COMPLETE:
You MUST call the calculate_profile tool with ALL answers formatted as a JSON object. The keys are p1_1 through p6_3 with 0-based option indices matching the order listed above. Wait for the tool result, then present it conversationally.

PRESENTING THE RESULT:
- State the profile and what it means in plain language
- Mention the asset allocation conversationally
- Name 3-4 suitable products
- If there were restrictions, explain them tactfully
- If they have ESG preferences, mention it
- Remind them of the 3-year validity period
- ALWAYS include a disclaimer: this is a demo, not real financial advice."""


# =====================================================================
# OpenAI-Compatible Endpoints (ElevenLabs Custom LLM points here)
# =====================================================================

@app.get("/v1/models")
async def list_models():
    """Model list - ElevenLabs may query this."""
    return {
        "object": "list",
        "data": [{
            "id": OLLAMA_MODEL,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "local-ollama-vps"
        }]
    }


@app.post("/v1/chat/completions")
@limiter.limit("30/minute")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completions.
    ElevenLabs sends all conversation here. We proxy to Ollama.
    Every call is logged for explainability."""

    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    # Build audit entry
    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user_msg = m.get("content", "")[:200]
            break

    audit_entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": str(datetime.now()),
        "type": "llm_call",
        "source": "elevenlabs_custom_llm",
        "model": OLLAMA_MODEL,
        "messages_count": len(messages),
        "last_user_message": last_user_msg,
        "has_tools": "tools" in body,
    }

    # Forward to Ollama - use our model, keep everything else
    ollama_body = {**body, "model": OLLAMA_MODEL, "keep_alive": "30m"}

    if stream:
        return StreamingResponse(
            _stream_from_ollama(ollama_body, audit_entry),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{OLLAMA_URL}/v1/chat/completions", json=ollama_body
                )
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                msg = choice.get("message", {})
                reply = msg.get("content", "")
                tool_calls = msg.get("tool_calls")

                audit_entry["response"] = reply[:500] if reply else None
                audit_entry["tool_calls"] = bool(tool_calls)
                audit_entry["status"] = "success"
                audit_log.append(audit_entry)

                print(f"[BRAIN] User: {last_user_msg[:80]}")
                if reply:
                    print(f"[BRAIN] AI: {reply[:120]}")
                if tool_calls:
                    print(f"[BRAIN] Tool call: {tool_calls[0]['function']['name']}")

                return data
        except Exception as e:
            audit_entry["status"] = "error"
            audit_entry["error"] = str(e)
            audit_log.append(audit_entry)
            print(f"[BRAIN ERROR] {e}")
            return JSONResponse(status_code=502, content={"error": str(e)})


async def _stream_from_ollama(body, audit_entry):
    """Stream Ollama response as SSE, logging the full response."""
    full_response = ""
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST", f"{OLLAMA_URL}/v1/chat/completions", json=body
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    yield line + "\n\n"
                    if line.startswith("data: ") and line.strip() != "data: [DONE]":
                        try:
                            chunk = json.loads(line[6:])
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            full_response += delta.get("content", "")
                        except:
                            pass

        audit_entry["response"] = full_response[:500]
        audit_entry["status"] = "success"
    except Exception as e:
        audit_entry["status"] = "error"
        audit_entry["error"] = str(e)
        error_chunk = {
            "id": "error",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": "I'm having a moment, could you repeat that?"}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    audit_log.append(audit_entry)
    if full_response:
        print(f"[BRAIN Stream] {audit_entry['last_user_message'][:60]} -> {full_response[:80]}")


# =====================================================================
# Profile Calculation (ALL logic on VPS - fully explainable)
# =====================================================================

PROFILES = [
    ("Very Conservative", 0, 15),
    ("Conservative", 16, 30),
    ("Moderate Conservative", 31, 42),
    ("Moderate", 43, 53),
    ("Moderate Aggressive", 54, 64),
    ("Aggressive", 65, 75),
]

PROFILE_ALLOCATIONS = {
    "Very Conservative":    {"Government Bonds": 70, "Cash/Money Market": 25, "Equities": 5,  "Alternatives": 0},
    "Conservative":         {"Bonds": 60, "Cash": 10, "Equities": 20, "Alternatives": 10},
    "Moderate Conservative": {"Bonds": 45, "Cash": 5,  "Equities": 35, "Alternatives": 15},
    "Moderate":             {"Bonds": 30, "Cash": 5,  "Equities": 45, "Alternatives": 20},
    "Moderate Aggressive":  {"Bonds": 15, "Cash": 5,  "Equities": 55, "Alternatives": 25},
    "Aggressive":           {"Bonds": 5,  "Cash": 5,  "Equities": 60, "Alternatives": 30},
}

PROFILE_PRODUCTS = {
    "Very Conservative": ["Spanish Government Bonds (Letras del Tesoro)", "High-yield savings accounts", "Money market funds", "Short-term bond ETFs"],
    "Conservative": ["Investment-grade bond funds", "Conservative mixed funds", "Dividend-focused ETFs", "Euro government bond ladder"],
    "Moderate Conservative": ["Balanced funds (defensive)", "Target-date retirement funds", "Blue-chip dividend stocks", "Euro REITs"],
    "Moderate": ["Global equity index funds (MSCI World)", "Balanced growth funds", "Corporate bond funds", "Sector ETFs"],
    "Moderate Aggressive": ["Growth equity funds", "International equity ETFs", "Small/mid-cap funds", "Emerging market bonds"],
    "Aggressive": ["Growth stocks / tech funds", "Emerging market equity ETFs", "Thematic ETFs (AI, clean energy)", "Private equity funds (if eligible)"],
}


@app.post("/calculate-profile")
@limiter.limit("10/minute")
async def calculate_profile(request: Request):
    """MiFID II profile calculation with FULL explainability.
    Every score, restriction, and adjustment is documented.
    This is the 'explainable' core of the demo."""

    body = await request.json()
    answers_raw = body.get("answers", "{}")

    if isinstance(answers_raw, str):
        try:
            answers = json.loads(answers_raw)
        except json.JSONDecodeError:
            return {"error": "Invalid answers JSON", "received": answers_raw}
    else:
        answers = answers_raw

    # Explanation object - this IS the explainability
    explanation = {
        "methodology": "MiFID II Suitability Assessment (EU Directive 2014/65/EU)",
        "input_answers": answers,
        "scoring_detail": {},
        "block_scores": {},
        "restrictions_applied": [],
        "coherence_checks": [],
        "total_score": 0,
        "max_possible_score": 75,
        "raw_profile": "",
        "final_profile": "",
        "adjustments": [],
    }

    max_profile_level = 5  # 0=Very Conservative ... 5=Aggressive

    # --- BLOCK 1: Personal Details (restrictions only, no scoring) ---
    age = answers.get("p1_1", 2)
    employment = answers.get("p1_2", 0)
    dependents = answers.get("p1_3", 0)

    age_labels = ["18-30", "31-45", "46-60", "61-70", ">70"]
    emp_labels = ["Employed", "Self-employed", "Civil servant", "Unemployed", "Retired", "Student"]
    dep_labels = ["None", "1-2", "3+"]

    explanation["scoring_detail"]["block_1"] = {
        "name": "Personal Details",
        "scores": False,
        "data": {
            "age_range": age_labels[min(age, 4)],
            "employment": emp_labels[min(employment, 5)],
            "dependents": dep_labels[min(dependents, 2)],
        }
    }

    if age >= 3:  # 61-70 or >70
        max_profile_level = min(max_profile_level, 3)
        explanation["restrictions_applied"].append({
            "rule": "Age restriction (MiFID II Art. 25)",
            "reason": f"Client age range {age_labels[min(age, 4)]} (>65): higher-risk profiles unsuitable",
            "effect": "Maximum profile capped at Moderate",
        })

    if employment in [3, 5]:  # Unemployed or Student
        max_profile_level = min(max_profile_level, 2)
        explanation["restrictions_applied"].append({
            "rule": "Income stability restriction",
            "reason": f"Employment status '{emp_labels[min(employment, 5)]}': limited income stability",
            "effect": "Maximum profile capped at Moderate Conservative",
        })

    reduce_for_dependents = dependents >= 2
    if reduce_for_dependents:
        explanation["restrictions_applied"].append({
            "rule": "Dependents adjustment",
            "reason": "3+ financial dependents increases obligations",
            "effect": "Profile reduced by one level",
        })

    # --- BLOCK 2: Financial Situation (max 22 pts) ---
    b2_config = [
        ("p2_1", "Annual net income", [1, 2, 3, 4, 5], ["<15K", "15-30K", "30-60K", "60-100K", ">100K"]),
        ("p2_2", "Financial assets", [1, 2, 3, 4, 5], ["<10K", "10-50K", "50-150K", "150-500K", ">500K"]),
        ("p2_3", "Fixed expenses ratio", [1, 2, 3, 4], [">70%", "50-70%", "30-49%", "<30%"]),
        ("p2_4", "Emergency fund", [1, 2, 3, 4], ["None", "1-3 months", "3-6 months", ">6 months"]),
        ("p2_5", "Outstanding debts", [1, 2, 3, 4], ["Significant", "Manageable", "Small loans", "None"]),
    ]
    b2_total, b2_details = _score_block(answers, b2_config)
    explanation["scoring_detail"]["block_2"] = {"name": "Financial Situation", "max": 22, "score": b2_total, "details": b2_details}
    explanation["block_scores"]["financial_situation"] = f"{b2_total}/22"

    if b2_total < 8:
        max_profile_level = min(max_profile_level, 1)
        explanation["restrictions_applied"].append({
            "rule": "Financial capacity restriction",
            "reason": f"Financial situation score {b2_total}/22 (below threshold of 8)",
            "effect": "Maximum profile capped at Conservative",
        })

    # --- BLOCK 3: Knowledge & Experience (max 16 pts) ---
    b3_config = [
        ("p3_1", "Financial education", [1, 2, 3, 4], ["None", "Basic", "University degree", "Certified"]),
        ("p3_2", "Products traded (3yr)", [1, 2, 3, 4], ["Deposits only", "Funds/pensions", "Stocks/ETFs/bonds", "Derivatives"]),
        ("p3_3", "Trading frequency", [1, 2, 3, 4], ["Never", "Few times/year", "Several/year", "Monthly+"]),
        ("p3_4", "Understands equity risk", [0, 1, 2], ["No", "Somewhat", "Yes"]),
        ("p3_5", "Understands diversification", [0, 1, 2], ["No", "Somewhat", "Yes"]),
    ]
    b3_total, b3_details = _score_block(answers, b3_config)
    explanation["scoring_detail"]["block_3"] = {"name": "Knowledge & Experience", "max": 16, "score": b3_total, "details": b3_details}
    explanation["block_scores"]["knowledge_experience"] = f"{b3_total}/16"

    if b3_total < 5:
        max_profile_level = min(max_profile_level, 2)
        explanation["restrictions_applied"].append({
            "rule": "Knowledge restriction (MiFID II appropriateness)",
            "reason": f"Knowledge score {b3_total}/16 (below threshold of 5)",
            "effect": "Maximum profile capped at Moderate Conservative",
        })

    # --- BLOCK 4: Investment Objectives (max 20 pts) ---
    b4_config = [
        ("p4_1", "Main objective", [1, 2, 3, 4], ["Preserve capital", "Regular income", "Growth", "Maximize returns"]),
        ("p4_2", "Time horizon", [1, 2, 3, 4], ["<1 year", "1-3 years", "3-7 years", ">7 years"]),
        ("p4_3", "% assets to invest", [4, 3, 2, 1], ["<10%", "10-25%", "26-50%", ">50%"]),  # INVERSE
        ("p4_4", "Expected return", [1, 2, 3, 4], ["2-3%", "4-6%", "7-10%", ">10%"]),
        ("p4_5", "Liquidity needs", [1, 2, 3, 4], ["Anytime", "1-2 years", "3-5 years", "None"]),
    ]
    b4_total, b4_details = _score_block(answers, b4_config)
    explanation["scoring_detail"]["block_4"] = {"name": "Investment Objectives", "max": 20, "score": b4_total, "details": b4_details}
    explanation["block_scores"]["investment_objectives"] = f"{b4_total}/20"

    if answers.get("p4_2", 2) == 0:
        max_profile_level = min(max_profile_level, 3)
        explanation["restrictions_applied"].append({
            "rule": "Short horizon restriction",
            "reason": "Investment horizon < 1 year: volatile products unsuitable",
            "effect": "Maximum profile capped at Moderate",
        })

    # --- BLOCK 5: Risk Tolerance (max 17 pts) ---
    b5_config = [
        ("p5_1", "Reaction to -10% loss", [1, 2, 3, 4], ["Sell everything", "Sell part", "Wait", "Invest more"]),
        ("p5_2", "Max acceptable annual loss", [1, 2, 3, 4, 5], ["0%", "5%", "15%", "25%", ">25%"]),
        ("p5_3", "Comfort with 20% fluctuation", [1, 2, 3, 4], ["Very uncomfortable", "Worried", "Normal", "Not concerned"]),
        ("p5_4", "Risk/return preference", [1, 2, 3, 4], ["Earn little, no losses", "A bit more, small losses", "Good returns, accept losses", "Maximum returns, high risk"]),
    ]
    b5_total, b5_details = _score_block(answers, b5_config)
    explanation["scoring_detail"]["block_5"] = {"name": "Risk Tolerance", "max": 17, "score": b5_total, "details": b5_details}
    explanation["block_scores"]["risk_tolerance"] = f"{b5_total}/17"

    # Coherence check
    q52 = answers.get("p5_2", 1)
    q54 = answers.get("p5_4", 0)
    if q52 == 0 and q54 >= 2:
        explanation["coherence_checks"].append({
            "flag": "INCONSISTENCY DETECTED",
            "detail": "Client accepts 0% loss but selected high risk/return preference",
            "recommendation": "Advisor should discuss risk expectations with client",
        })

    # --- Calculate Total ---
    total = b2_total + b3_total + b4_total + b5_total
    explanation["total_score"] = total

    # Determine raw profile from score
    raw_profile = "Moderate"
    raw_level = 3
    for i, (name, low, high) in enumerate(PROFILES):
        if low <= total <= high:
            raw_profile = name
            raw_level = i
            break

    explanation["raw_profile"] = raw_profile

    # Apply restrictions
    final_level = min(raw_level, max_profile_level)
    if reduce_for_dependents:
        final_level = max(0, final_level - 1)
        explanation["adjustments"].append("Reduced by 1 level due to 3+ dependents")

    final_profile = PROFILES[final_level][0]
    explanation["final_profile"] = final_profile

    if raw_profile != final_profile:
        explanation["adjustments"].append(
            f"Profile adjusted from '{raw_profile}' to '{final_profile}' due to regulatory restrictions"
        )

    # --- ESG ---
    esg = None
    if answers.get("p6_1", 0) == 1:
        esg_types = ["EU Taxonomy", "PAI (Principal Adverse Impact)", "Art. 8/Art. 9 SFDR"]
        esg_mins = ["No minimum", "25%", "50%", "75%", "100%"]
        esg = {
            "has_preference": True,
            "type": esg_types[min(answers.get("p6_2", 0) or 0, 2)],
            "minimum_sustainable_pct": esg_mins[min(answers.get("p6_3", 0) or 0, 4)],
        }

    allocation = PROFILE_ALLOCATIONS.get(final_profile, PROFILE_ALLOCATIONS["Moderate"])
    products = PROFILE_PRODUCTS.get(final_profile, PROFILE_PRODUCTS["Moderate"])

    result = {
        "profile": final_profile,
        "score": f"{total}/75",
        "allocation": allocation,
        "recommended_products": products,
        "esg_preferences": esg,
        "explanation": explanation,
        "validity_period": "3 years from assessment date",
        "regulatory_basis": "MiFID II Directive 2014/65/EU, Delegated Regulation 2017/565",
        "disclaimer": "DEMO ONLY. This is not real financial advice. Always consult a licensed financial advisor.",
        "assessed_at": str(datetime.now()),
        "assessed_by": "Ollama llama3.1:8b (on-premises, CPU inference)",
    }

    # Log for audit trail
    audit_log.append({
        "timestamp": str(datetime.now()),
        "type": "profile_calculation",
        "profile": final_profile,
        "score": total,
        "restrictions_count": len(explanation["restrictions_applied"]),
        "result": result,
    })

    print(f"[PROFILE] {final_profile} (score {total}/75, {len(explanation['restrictions_applied'])} restrictions)")
    return result


def _score_block(answers, config):
    """Score a block of questions. Returns (total, details_list)."""
    total = 0
    details = []
    for key, label, scores, option_labels in config:
        idx = answers.get(key, 0)
        if idx is None:
            idx = 0
        idx = min(idx, len(scores) - 1)
        score = scores[idx]
        total += score
        details.append({
            "question": label,
            "answer": option_labels[idx],
            "answer_index": idx,
            "score": score,
            "max_score": max(scores),
        })
    return total, details


# =====================================================================
# Text Chat Endpoint (React frontend - same brain, same prompt)
# =====================================================================

@app.post("/chat/{session_id}")
@limiter.limit("20/minute")
async def chat(session_id: str, request: Request):
    """Text chat from the React frontend.
    Uses the same Ollama model and MiFID personality."""

    body = await request.json()
    user_message = body.get("message", "")
    if not user_message:
        return {"error": "No message provided"}

    # Build conversation history
    if session_id not in sessions:
        sessions[session_id] = {
            "history": [], "created": str(datetime.now())
        }

    # Build messages for Ollama chat API
    messages = [{"role": "system", "content": MIFID_SYSTEM_PROMPT}]

    # Add recent history
    recent = sessions[session_id]["history"][-10:]
    for h in recent:
        if h["source"] == "user":
            messages.append({"role": "user", "content": h["transcript"]})
        elif h["source"] == "assistant":
            messages.append({"role": "assistant", "content": h["transcript"]})

    messages.append({"role": "user", "content": user_message})

    # Call Ollama chat API
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "keep_alive": "30m",
                },
            )
            data = resp.json()
            reply = data.get("message", {}).get("content", "Sorry, I had a problem.")
    except Exception as e:
        reply = f"Error connecting to AI model: {str(e)}"

    # Save to history
    sessions[session_id]["history"].append({
        "source": "user", "transcript": user_message,
        "timestamp": str(datetime.now()),
    })
    sessions[session_id]["history"].append({
        "source": "assistant", "transcript": reply,
        "timestamp": str(datetime.now()),
    })

    # Audit log
    audit_log.append({
        "timestamp": str(datetime.now()),
        "type": "text_chat",
        "session_id": session_id,
        "user_message": user_message[:200],
        "response": reply[:200],
        "model": OLLAMA_MODEL,
    })

    print(f"[TEXT] User: {user_message[:80]}")
    print(f"[TEXT] AI: {reply[:120]}")
    return {"reply": reply, "session_id": session_id}


# =====================================================================
# ElevenLabs Post-Call Webhook
# =====================================================================

@app.post("/webhook/elevenlabs")
async def elevenlabs_webhook(request: Request):
    body = await request.json()
    session_id = body.get("conversation_id", str(uuid.uuid4()))
    transcript = body.get("transcript", "")

    audit_log.append({
        "timestamp": str(datetime.now()),
        "type": "elevenlabs_webhook",
        "session_id": session_id,
        "transcript_length": len(transcript) if transcript else 0,
    })

    print(f"[WEBHOOK] Post-call data for session {session_id}")
    return {"status": "received", "session_id": session_id}


# =====================================================================
# Audit & Explainability Endpoints
# =====================================================================

@app.get("/audit")
@limiter.limit("30/minute")
async def get_audit_log(request: Request):
    """Full audit trail - every LLM call, every decision, every score.
    This is the explainability endpoint for the demo."""
    return {
        "total_entries": len(audit_log),
        "model": OLLAMA_MODEL,
        "server": "Hostinger VPS (CPU-only, on-premises)",
        "entries": audit_log[-50:],  # Last 50 entries
    }


@app.get("/audit/profiles")
async def get_profile_calculations(request: Request):
    """All profile calculations with full explanation."""
    profiles = [e for e in audit_log if e.get("type") == "profile_calculation"]
    return {
        "count": len(profiles),
        "calculations": profiles,
    }


@app.get("/audit/latest-profile")
async def get_latest_profile(request: Request):
    """Most recent profile calculation with full explainability."""
    profiles = [e for e in audit_log if e.get("type") == "profile_calculation"]
    if not profiles:
        return {"message": "No profiles calculated yet"}
    return profiles[-1]


# =====================================================================
# Utility Endpoints
# =====================================================================

@app.get("/health")
async def health():
    # Also check Ollama
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            ollama_ok = resp.status_code == 200
    except:
        pass

    return {
        "status": "ok",
        "time": str(datetime.now()),
        "model": OLLAMA_MODEL,
        "ollama_connected": ollama_ok,
        "audit_entries": len(audit_log),
        "active_sessions": len(sessions),
        "architecture": {
            "brain": f"Ollama {OLLAMA_MODEL} (on-premises VPS)",
            "voice": "ElevenLabs (STT + TTS only)",
            "backend": "FastAPI (routing + logging + explainability)",
        },
    }


@app.get("/history/{session_id}")
async def get_history(session_id: str):
    if session_id not in sessions:
        return {"history": []}
    return {"history": sessions[session_id]["history"]}


@app.get("/sessions")
async def list_sessions():
    return {"sessions": list(sessions.keys()), "count": len(sessions)}
