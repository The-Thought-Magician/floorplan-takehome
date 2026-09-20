"""Dimensioned floor plans from phone captures."""

import os

# This machine has no Python headers, so anything that JIT-compiles Triton fails.
# Both switches keep torch on its prebuilt CUDA kernels. Harmless where headers exist.
os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")
