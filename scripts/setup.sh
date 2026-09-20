#!/usr/bin/env bash
# Fresh machine to first plan. Needs: NVIDIA GPU with 8 GB, CUDA driver, ffmpeg, uv, cloudflared (optional).
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync
test -d third_party/vggt-low-vram || git clone --depth 1 https://github.com/harry7557558/vggt-low-vram.git third_party/vggt-low-vram
uv pip install --no-deps -e third_party/vggt-low-vram
scripts/fetch_weights.sh
uv run pytest -q
echo "setup complete. Next: uv run python scripts/floorplan.py <capture dir> <out dir>"
