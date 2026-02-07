#!/bin/bash
# ============================================================
# Goose AI Advisor — Azure GPU VM Deployment Script
# Run this ON the Azure VM after SSH-ing in
# ============================================================
set -e

echo "=== 1. Installing NVIDIA drivers ==="
sudo apt-get update
sudo apt-get install -y ubuntu-drivers-common
sudo ubuntu-drivers install
# Verify GPU is detected
nvidia-smi || echo "WARNING: nvidia-smi failed. Drivers may need a reboot."

echo "=== 2. Installing Ollama ==="
curl -fsSL https://ollama.com/install.sh | sh
sleep 3

echo "=== 3. Pulling Llama 3.1 8B ==="
ollama pull llama3.1:8b

echo "=== 4. Configuring Ollama keep-alive ==="
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf << 'CONF'
[Service]
Environment="OLLAMA_KEEP_ALIVE=30m"
CONF
systemctl daemon-reload
systemctl restart ollama
sleep 5

echo "=== 5. Installing Python + UV ==="
apt-get install -y python3 python3-venv python3-pip git
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "=== 6. Cloning project ==="
cd /root
git clone https://github.com/inigomartos/Goose_for_claude.git
cd Goose_for_claude

echo "=== 7. Creating .env ==="
cat > .env << 'ENV'
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
ENV

echo "=== 8. Starting backend ==="
nohup uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &
sleep 5

echo "=== 9. Testing ==="
curl -s http://localhost:8000/health && echo " <- Backend OK"
curl -s http://localhost:11434/api/tags | head -c 100 && echo " <- Ollama OK"

echo ""
echo "============================================"
echo "  DEPLOYMENT COMPLETE"
echo "  App: http://$(curl -s ifconfig.me):8000"
echo "============================================"
