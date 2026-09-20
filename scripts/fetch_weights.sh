#!/usr/bin/env bash
# Download model weights into the Hugging Face cache. Run once, about 5 GB.
# Xet transfer is disabled: it stalled at 0 MB/s on this machine, plain HTTP resumes fine.
set -euo pipefail
cd "$(dirname "$0")/.."
export HF_HUB_DISABLE_XET=1
uv run hf download facebook/VGGT-1B model.safetensors config.json
echo "weights ready"
