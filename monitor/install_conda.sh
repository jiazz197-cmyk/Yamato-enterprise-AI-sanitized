#!/bin/bash
# Complete Installation Script with Conda Environment
# Usage: bash install_conda.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}vLLM Monitor - Complete Installation (Conda)${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Determine installation directory
if [ "$EUID" -eq 0 ]; then 
    echo -e "${YELLOW}Running as root${NC}"
    INSTALL_DIR="/opt/vllm-monitor"
    USE_SUDO=""
else
    echo -e "Running as regular user"
    INSTALL_DIR="$HOME/vllm-monitor"
    USE_SUDO="sudo"
fi

echo -e "Installation directory: ${YELLOW}${INSTALL_DIR}${NC}"
echo ""

# Step 1: Check/Install Miniconda
echo -e "${BLUE}Step 1: Checking Miniconda${NC}"
if ! command -v conda &> /dev/null; then
    echo -e "${YELLOW}Miniconda not found. Installing...${NC}"
    
    # Download Miniconda
    MINICONDA_INSTALLER="Miniconda3-latest-Linux-x86_64.sh"
    if [ ! -f "$MINICONDA_INSTALLER" ]; then
        echo "Downloading Miniconda..."
        wget -q https://repo.anaconda.com/miniconda/$MINICONDA_INSTALLER
    fi
    
    # Install Miniconda
    echo "Installing Miniconda..."
    bash $MINICONDA_INSTALLER -b -p $HOME/miniconda3
    
    # Initialize conda
    echo "Initializing conda..."
    $HOME/miniconda3/bin/conda init bash
    
    # Source conda
    source $HOME/miniconda3/etc/profile.d/conda.sh
    
    echo -e "${GREEN}✓ Miniconda installed${NC}"
else
    echo -e "${GREEN}✓ Conda found: $(conda --version)${NC}"
    
    # Make sure conda is properly initialized
    if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/miniconda3/etc/profile.d/conda.sh"
    elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/anaconda3/etc/profile.d/conda.sh"
    fi
fi
echo ""

# Step 2: Create installation directory
echo -e "${BLUE}Step 2: Setting up directories${NC}"
if [ ! -d "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
    echo -e "✓ Created directory: ${INSTALL_DIR}"
else
    echo -e "✓ Directory exists: ${INSTALL_DIR}"
fi
echo ""

# Step 3: Copy files
echo -e "${BLUE}Step 3: Copying files${NC}"
FILES=(
    "monitor.py"
    "environment.yml"
    "setup_conda_env.sh"
    "start_monitor.sh"
    "test_environment.py"
    "check_gpu_status.sh"
    "vllm-monitor.service"
    "README.md"
    "CONDA使用说明.md"
    "文件说明.txt"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        cp "$file" "$INSTALL_DIR/"
        echo "  ✓ Copied $file"
    else
        echo -e "  ${YELLOW}⚠ $file not found, skipping${NC}"
    fi
done
echo ""

# Step 4: Set permissions
echo -e "${BLUE}Step 4: Setting permissions${NC}"
chmod +x "$INSTALL_DIR/monitor.py"
chmod +x "$INSTALL_DIR/setup_conda_env.sh"
chmod +x "$INSTALL_DIR/start_monitor.sh"
chmod +x "$INSTALL_DIR/test_environment.py"
chmod +x "$INSTALL_DIR/check_gpu_status.sh"
echo -e "✓ Permissions set"
echo ""

# Step 5: Create conda environment
echo -e "${BLUE}Step 5: Creating conda environment${NC}"
cd "$INSTALL_DIR"

if conda env list | grep -q "^vllm-monitor "; then
    echo -e "${YELLOW}⚠ Environment 'vllm-monitor' already exists${NC}"
    read -p "Update it? (Y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        conda env update -n vllm-monitor -f environment.yml --prune
        echo -e "${GREEN}✓ Environment updated${NC}"
    fi
else
    conda env create -f environment.yml
    echo -e "${GREEN}✓ Environment created${NC}"
fi
echo ""

# Step 6: Test environment
echo -e "${BLUE}Step 6: Testing environment${NC}"
conda activate vllm-monitor
python test_environment.py
conda deactivate
echo ""

# Step 7: Setup systemd service (optional)
echo -e "${BLUE}Step 7: Systemd service setup (optional)${NC}"
if [ "$EUID" -eq 0 ] || groups | grep -q sudo; then
    read -p "Install as systemd service? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Update service file with correct conda path
        CONDA_PATH=$(which conda | sed 's|/bin/conda||')
        sed -i "s|/root/miniconda3|$CONDA_PATH|g" "$INSTALL_DIR/vllm-monitor.service"
        sed -i "s|/opt/vllm-monitor|$INSTALL_DIR|g" "$INSTALL_DIR/vllm-monitor.service"
        
        $USE_SUDO cp "$INSTALL_DIR/vllm-monitor.service" /etc/systemd/system/
        $USE_SUDO systemctl daemon-reload
        
        echo -e "${GREEN}✓ Service installed${NC}"
        echo ""
        echo "Enable and start with:"
        echo -e "  ${YELLOW}sudo systemctl enable vllm-monitor${NC}"
        echo -e "  ${YELLOW}sudo systemctl start vllm-monitor${NC}"
    fi
fi
echo ""

# Step 8: Create convenience scripts
echo -e "${BLUE}Step 8: Creating convenience scripts${NC}"

# Create activate script
cat > "$INSTALL_DIR/activate.sh" << 'EOF'
#!/bin/bash
# Quick activation script
source ~/miniconda3/etc/profile.d/conda.sh 2>/dev/null || source ~/anaconda3/etc/profile.d/conda.sh 2>/dev/null
conda activate vllm-monitor
EOF
chmod +x "$INSTALL_DIR/activate.sh"
echo -e "✓ Created activate.sh"

# Create quick start alias
cat > "$INSTALL_DIR/start.sh" << 'EOF'
#!/bin/bash
cd $(dirname "$0")
./start_monitor.sh
EOF
chmod +x "$INSTALL_DIR/start.sh"
echo -e "✓ Created start.sh (alias for start_monitor.sh)"

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}✅ Installation Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "📁 Installation directory: ${YELLOW}${INSTALL_DIR}${NC}"
echo -e "🐍 Conda environment: ${YELLOW}vllm-monitor${NC}"
echo ""
echo -e "${BLUE}Quick Start:${NC}"
echo -e "  ${YELLOW}cd ${INSTALL_DIR}${NC}"
echo -e "  ${YELLOW}./start.sh${NC}"
echo ""
echo -e "${BLUE}Or manually:${NC}"
echo -e "  ${YELLOW}cd ${INSTALL_DIR}${NC}"
echo -e "  ${YELLOW}conda activate vllm-monitor${NC}"
echo -e "  ${YELLOW}python monitor.py${NC}"
echo ""
echo -e "${BLUE}Check GPU status:${NC}"
echo -e "  ${YELLOW}cd ${INSTALL_DIR}${NC}"
echo -e "  ${YELLOW}./check_gpu_status.sh${NC}"
echo ""
echo -e "📊 Metrics endpoint: ${BLUE}http://localhost:9400/metrics${NC}"
echo ""
echo -e "${YELLOW}Note: If this is your first conda installation, please:${NC}"
echo -e "${YELLOW}  1. Close and reopen your terminal${NC}"
echo -e "${YELLOW}  2. Then run: cd ${INSTALL_DIR} && ./start.sh${NC}"
echo ""

