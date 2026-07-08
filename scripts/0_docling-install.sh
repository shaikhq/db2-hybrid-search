#!/usr/bin/env bash
# 0_docling-install.sh — set up the Python venv for the pipeline: Docling (PDF
# extract/chunk), ibm_db, transformers, and the UI deps. Also installs the libGL
# system library Docling's OpenCV needs. One-time. Does not run anything.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# System lib for Docling's OpenCV (libGL.so.1).
if ! ldconfig -p 2>/dev/null | grep -q libGL.so.1; then
  sudo dnf install -y libglvnd-glx        # Debian/Ubuntu: sudo apt-get install -y libgl1
fi

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
# CPU-only torch first, so pip doesn't pull multi-GB CUDA wheels.
pip install --index-url https://download.pytorch.org/whl/cpu torch==2.12.1 torchvision==0.27.1
pip install -r requirements.txt

python -c "import docling, ibm_db, transformers; print('OK — docling + deps installed in .venv')"
