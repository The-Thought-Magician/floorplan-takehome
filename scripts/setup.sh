#!/usr/bin/env bash
# Fresh machine to first plan. Needs: NVIDIA GPU with 8 GB, CUDA driver, ffmpeg, uv, cloudflared (optional).
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync
test -d third_party/vggt-low-vram || git clone --depth 1 https://github.com/harry7557558/vggt-low-vram.git third_party/vggt-low-vram
uv pip install --no-deps -e third_party/vggt-low-vram
# MoGe-2 (metric depth anchor). Installed without deps: its pyproject pulls a CUDA build (flex-gemm) only the v3 model needs.
uv pip install --no-deps "git+https://github.com/microsoft/MoGe.git@74fbce054ebed49800de42d0ad0e83495065719a" \
  "utils3d_moge @ git+https://github.com/EasternJournalist/utils3d-moge.git@62f09d58509485564e24d5d9f6aac9ee9ebc0c37" \
  "pipeline @ git+https://github.com/EasternJournalist/pipeline.git@1c511390d90226c00c101f34b84df26a0f8789b4" click
scripts/fetch_weights.sh
uv run pytest -q
echo "setup complete. Next: uv run python scripts/floorplan.py <capture dir> <out dir>"
