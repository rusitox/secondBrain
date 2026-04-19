#!/usr/bin/env bash
set -euo pipefail

echo "=== secondBrain Installer ==="
echo ""

# Parse flags
REMOTE_MODE=false
for arg in "$@"; do
    case "$arg" in
        --remote) REMOTE_MODE=true ;;
        --help|-h)
            echo "Usage: ./install.sh [--remote]"
            echo ""
            echo "  --remote   Install CLI only (no Docker/DB), then login to a remote server"
            exit 0
            ;;
    esac
done

# 1. Check Python
if ! command -v python3 &>/dev/null; then
    echo "Python 3 not found."
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "Installing via Homebrew..."
        if ! command -v brew &>/dev/null; then
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
        brew install python@3.11
    else
        echo "Please install Python 3.8+ and re-run this script."
        echo "  Ubuntu/Debian: sudo apt install python3 python3-pip"
        echo "  Fedora: sudo dnf install python3 python3-pip"
        exit 1
    fi
fi
echo "✓ Python $(python3 --version 2>&1)"

if [ "$REMOTE_MODE" = true ]; then
    # Remote mode: install CLI package only, then login
    echo ""
    echo "Installing secondBrain CLI (remote mode)..."
    python3 -m pip install . --quiet 2>/dev/null || \
        python3 -m pip install . --quiet --break-system-packages
    echo "✓ CLI installed"

    echo ""
    echo "Now log in to your remote server:"
    echo ""
    python3 -m cli login

    echo ""
    echo "To start the CLI:"
    echo "  secondbrain"
    echo "  # or: python3 -m cli"
    exit 0
fi

# 2. Check Docker
if ! command -v docker &>/dev/null; then
    echo ""
    echo "Docker not found."
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "Installing Docker Desktop via Homebrew..."
        brew install --cask docker
        echo ""
        echo "Please start Docker Desktop and re-run this script."
        exit 1
    else
        echo "Please install Docker and re-run this script."
        echo "  https://docs.docker.com/engine/install/"
        exit 1
    fi
fi

# Check Docker daemon is running
if ! docker info &>/dev/null 2>&1; then
    echo ""
    echo "Docker is installed but not running."
    echo "Please start Docker Desktop and re-run this script."
    exit 1
fi
echo "✓ Docker $(docker --version 2>&1)"

# 3. Install Python dependencies
echo ""
echo "Installing Python dependencies..."
python3 -m pip install -r requirements.txt --quiet 2>/dev/null || \
    python3 -m pip install -r requirements.txt --quiet --break-system-packages
echo "✓ Dependencies installed"

# 4. Delegate to CLI installer
echo ""
python3 -m cli install
