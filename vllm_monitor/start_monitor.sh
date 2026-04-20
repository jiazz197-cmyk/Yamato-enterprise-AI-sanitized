#!/bin/bash
# Start vLLM Monitor with Conda Environment
# Usage: ./start_monitor.sh

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Starting vLLM Monitor${NC}"
echo -e "${BLUE}Hardware: 4x RTX 4090 + 2x AMD CPU${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Get conda base path
if [ -z "$CONDA_EXE" ]; then
    # Try to find conda in common locations
    if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/miniconda3/etc/profile.d/conda.sh"
    elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/anaconda3/etc/profile.d/conda.sh"
    elif [ -f "/opt/conda/etc/profile.d/conda.sh" ]; then
        source "/opt/conda/etc/profile.d/conda.sh"
    else
        echo -e "${RED}❌ Cannot find conda installation${NC}"
        echo "Please run: conda init bash"
        echo "Then restart your shell and try again"
        exit 1
    fi
fi

# Check if environment exists
ENV_NAME="vllm-monitor"
if ! conda env list | grep -q "^${ENV_NAME} "; then
    echo -e "${RED}❌ Conda environment '${ENV_NAME}' not found!${NC}"
    echo ""
    echo "Create it first:"
    echo -e "${YELLOW}    bash setup_conda_env.sh${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Conda environment found${NC}"

# Activate environment
echo "Activating environment: ${ENV_NAME}"
conda activate ${ENV_NAME}

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to activate conda environment${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Environment activated${NC}"
echo ""

# Check Python version
PYTHON_VERSION=$(python --version)
echo -e "Python: ${GREEN}${PYTHON_VERSION}${NC}"

# Check if required packages are installed
echo "Checking packages..."
MISSING=0
for pkg in psutil requests prometheus_client pynvml docker; do
    if ! python -c "import $pkg" 2>/dev/null; then
        echo -e "${RED}  ✗ $pkg${NC}"
        MISSING=1
    else
        echo -e "${GREEN}  ✓ $pkg${NC}"
    fi
done

if [ $MISSING -eq 1 ]; then
    echo -e "${RED}❌ Some packages are missing${NC}"
    echo "Reinstall environment with: bash setup_conda_env.sh"
    exit 1
fi

echo ""

# Check if port 9400 is available
if command -v lsof &> /dev/null; then
    if lsof -Pi :9400 -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${RED}❌ Port 9400 is already in use${NC}"
        echo "Kill existing process: sudo kill \$(lsof -t -i:9400)"
        exit 1
    fi
    echo -e "${GREEN}✓ Port 9400 is available${NC}"
fi

# Check NVIDIA GPU
if command -v nvidia-smi &> /dev/null; then
    echo -e "${GREEN}✓ NVIDIA driver detected${NC}"
    nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader | while IFS=, read -r idx name mem; do
        echo "  GPU $idx: $name ($mem)"
    done
else
    echo -e "${YELLOW}⚠ nvidia-smi not found${NC}"
fi

echo ""
echo -e "${GREEN}Starting monitor...${NC}"
echo "Press Ctrl+C to stop"
echo ""
echo "Access metrics at: ${BLUE}http://localhost:9400/metrics${NC}"
echo ""

# Start monitor
python monitor.py

