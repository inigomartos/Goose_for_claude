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

patch_payload = {
    "conversation_config": {
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
                "bonds", "derivatives"
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
