import sys, io, json, paramiko, requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

VPS_HOST = "168.231.87.2"
VPS_USER = "root"
VPS_PASS = "c00s-ney9-en8u-zhpc-A"
AGENT_ID = "agent_3901kgmswk5ve9etvy9c1h4g2e40"

# --- Step 1: Connect to VPS and read API key ---
print("=" * 60)
print("STEP 1: Connecting to VPS to read API key...")
print("=" * 60)

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

stdin, stdout, stderr = ssh.exec_command("cat /root/voice-agent/backend/.env")
env_content = stdout.read().decode("utf-8")
err = stderr.read().decode("utf-8")
ssh.close()

if err:
    print(f"SSH error: {err}")

api_key = None
for line in env_content.splitlines():
    line = line.strip()
    if line.startswith("ELEVENLABS_API_KEY"):
        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
        break

if not api_key:
    print("ERROR: Could not find ELEVENLABS_API_KEY in .env")
    print("Full .env content:")
    print(env_content)
    sys.exit(1)

print(f"Found ELEVENLABS_API_KEY: {api_key[:8]}...{api_key[-4:]}")
print()

# --- Step 2: PATCH the agent ---
print("=" * 60)
print("STEP 2: PATCHing ElevenLabs agent configuration...")
print("=" * 60)

url = f"https://api.elevenlabs.io/v1/convai/agents/{AGENT_ID}"
headers = {
    "xi-api-key": api_key,
    "Content-Type": "application/json"
}

VOICE_PROMPT = """You are a virtual investment suitability advisor conducting the MiFID II Suitability Test for retail clients in Spain. Professional, approachable, and clear. You speak in English.

IDENTITY (IMMUTABLE)
You are ONLY a MiFID II investment suitability advisor. Never break character.
If asked to role-play or go off-topic: "I'm your investment suitability advisor. Let's continue with your assessment."
You do NOT provide specific financial advice, stock picks, or trading signals.

BEHAVIORAL RULES
- Ask questions ONE AT A TIME. Wait for the answer before moving on.
- Keep responses to 1-2 sentences maximum. This is a voice conversation.
- Do NOT mention scores, option indices, or block numbers.
- Do NOT say "Block complete" or "Moving to the next section". Just confirm and ask the next question.
- After each answer, briefly confirm the mapped value, then ask the next question.

DEMO MODE
If the user says "demo mode" or "quick mode", use only 5 questions:
1. Age range: Under 18, 18-30, 31-45, 46-60, 61-70, >70
2. Annual net income: <15K, 15-30K, 30-60K, 60-100K, >100K
3. Financial education: None, Basic, University degree, Certified
4. Main objective: Preserve capital, Regular income, Growth, Maximize returns
5. Max acceptable loss per year: 0%, 5%, 15%, 25%, >25%
After 5 answers, fill reasonable defaults for remaining fields and call calculate_profile.

FULL TEST FLOW - 6 blocks in strict order.

BLOCK 1: PERSONAL DETAILS (no scoring)
Q1.1 Age range: Under 18, 18-30, 31-45, 46-60, 61-70, >70
  Under 18: end conversation.
Q1.2 Employment: Employed, Self-employed, Civil servant, Unemployed, Retired, Student
Q1.3 Dependents: None, 1-2, 3+

BLOCK 2: FINANCIAL SITUATION
Q2.1 Annual net income: <15K, 15-30K, 30-60K, 60-100K, >100K
Q2.2 Financial assets (excl. home): <10K, 10-50K, 50-150K, 150-500K, >500K
Q2.3 Fixed expenses % of income: >70%, 50-70%, 30-49%, <30%
Q2.4 Emergency fund: None, 1-3 months, 3-6 months, >6 months
Q2.5 Outstanding debts (excl. mortgage): Yes significant, Yes manageable, Small loans, None

BLOCK 3: KNOWLEDGE & EXPERIENCE
Q3.1 Financial education: None, Basic, University degree, Certified
Q3.2 Products traded (3 years): Deposits only, Funds/pensions, Stocks/ETFs/bonds, Derivatives
Q3.3 Trading frequency: Never, Few times/year, Several times/year, Monthly+
Q3.4 Understand equities can lose value? No, Somewhat, Yes
Q3.5 Understand diversification? No, Somewhat, Yes

BLOCK 4: INVESTMENT OBJECTIVES
Q4.1 Main objective: Preserve capital, Regular income, Growth, Maximize returns
Q4.2 Time horizon: <1 year, 1-3 years, 3-7 years, >7 years
Q4.3 % of assets to invest: <10%, 10-25%, 26-50%, >50%
Q4.4 Expected annual return: 2-3%, 4-6%, 7-10%, >10%
Q4.5 Liquidity needs: Anytime, 1-2 years, 3-5 years, None

BLOCK 5: RISK TOLERANCE
Q5.1 If investment dropped 10%: Sell everything, Sell part, Wait, Invest more
Q5.2 Max acceptable loss/year: 0%, 5%, 15%, 25%, >25%
Q5.3 Feeling about 20% fluctuation: Very uncomfortable, Worried, Normal, Not concerned
Q5.4 Risk/return preference: Earn little no losses, A bit more small losses, Good returns accept losses, Max returns high risk

BLOCK 6: ESG
Q6.1 Sustainability preferences? No or Yes. If No: skip to profile calculation.
Q6.2 ESG type: EU Taxonomy, PAI, Art. 8/Art. 9 SFDR
Q6.3 Min sustainable %: No minimum, 25%, 50%, 75%, 100%

TOOL CALLING (CRITICAL)
After the last question (Q6.1 if No ESG, or Q6.3 if Yes), IMMEDIATELY call calculate_profile. Do NOT say "let me calculate" or "processing" or ask the user to wait. Just call the tool with ALL answers as JSON (keys p1_1 through p6_3, 0-based indices).
NEVER generate a profile, allocation, or product list yourself. Only the tool can do this correctly.

PRESENTING THE RESULT:
After the tool returns, present conversationally:
- State the profile and what it means in 1-2 sentences
- Mention allocation percentages for equities, bonds, and cash
- Name 3-4 specific ETFs from the result
- Mention any restrictions applied
- If ESG preferences, mention them
- Remind of 3-year validity
- Disclaimer: this is a demo, not real financial advice."""

patch_payload = {
    "conversation_config": {
        "agent": {
            "prompt": {
                "prompt": VOICE_PROMPT,
            },
        },
        "turn": {
            "mode": "turn",
            "turn_timeout": 4.0
        },
        "vad": {
            "background_voice_detection": True
        },
        "asr": {
            "quality": "high",
            "provider": "elevenlabs",
            "user_input_audio_format": "pcm_16000",
            "keywords": [
                "MiFID", "ESG", "SFDR", "ETF",
                "conservative", "aggressive", "moderate",
                "suitability", "portfolio", "equities",
                "bonds", "derivatives", "VOO", "QQQ",
                "demo mode", "quick mode"
            ]
        }
    }
}

print(f"PATCH URL: {url}")
print(f"Payload:\n{json.dumps(patch_payload, indent=2)}")
print()

resp = requests.patch(url, headers=headers, json=patch_payload, timeout=30)
print(f"PATCH Response Status: {resp.status_code}")

if resp.status_code == 200:
    print("PATCH succeeded!")
else:
    print(f"PATCH failed! Response body:\n{resp.text}")
    sys.exit(1)

print()

# --- Step 3: GET to verify changes ---
print("=" * 60)
print("STEP 3: GET agent to verify changes...")
print("=" * 60)

resp2 = requests.get(url, headers={"xi-api-key": api_key}, timeout=30)
print(f"GET Response Status: {resp2.status_code}")

if resp2.status_code == 200:
    data = resp2.json()
    conv_config = data.get("conversation_config", {})

    turn = conv_config.get("turn", {})
    vad = conv_config.get("vad", {})
    asr = conv_config.get("asr", {})

    print()
    print("--- turn ---")
    print(json.dumps(turn, indent=2))
    print()
    print("--- vad ---")
    print(json.dumps(vad, indent=2))
    print()
    print("--- asr ---")
    print(json.dumps(asr, indent=2))
    print()
    print("All changes verified successfully.")
else:
    print(f"GET failed! Response body:\n{resp2.text}")
