#!/bin/bash
# Setup Conda Environment for vLLM Monitor
# Usage: bash setup_conda_env.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}vLLM Monitor - Conda Environment Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if conda is installed
if ! command -v conda &> /dev/null; then
    echo -e "${RED}[error] Conda not found!${NC}"
    echo ""
    echo "Please install Miniconda first:"
    echo ""
    echo -e "${YELLOW}# Download Miniconda${NC}"
    echo "wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
    echo ""
    echo -e "${YELLOW}# Install${NC}"
    echo "bash Miniconda3-latest-Linux-x86_64.sh"
    echo ""
    echo -e "${YELLOW}# Initialize (restart shell after this)${NC}"
    echo "conda init bash"
    echo ""
    exit 1
fi

echo -e "${GREEN}[success] Conda found: $(conda --version)${NC}"
echo ""

# Check if environment.yml exists
if [ ! -f "environment.yml" ]; then
    echo -e "${RED}[error] environment.yml not found!${NC}"
    exit 1
fi

# Check if environment already exists
ENV_NAME="vllm-monitor"
if conda env list | grep -q "^${ENV_NAME} "; then
    echo -e "${YELLOW}[warning] Environment '${ENV_NAME}' already exists${NC}"
    read -p "Do you want to remove and recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Removing existing environment...${NC}"
        conda env remove -n ${ENV_NAME} -y
    else
        echo -e "${YELLOW}Updating existing environment...${NC}"
        conda env update -n ${ENV_NAME} -f environment.yml --prune
        echo -e "${GREEN}[success] Environment updated${NC}"
        exit 0
    fi
fi

# Create conda environment
echo -e "${GREEN}Creating conda environment '${ENV_NAME}'...${NC}"
conda env create -f environment.yml

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}[success] Conda Environment Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "To activate the environment, run:"
echo -e "${YELLOW}    conda activate ${ENV_NAME}${NC}"
echo ""
echo -e "To start the monitor:"
echo -e "${YELLOW}    conda activate ${ENV_NAME}${NC}"
echo -e "${YELLOW}    python monitor.py${NC}"
echo ""
echo -e "Or use the convenience script:"
echo -e "${YELLOW}    ./start_monitor_conda.sh${NC}"
echo ""

