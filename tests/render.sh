#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
mkdir -p .build/tests
cc -c .build/umbriel/build/wlr-layer-shell-unstable-v1-client-protocol.c -o .build/tests/layer-protocol.o
cc -c .build/umbriel/build/xdg-shell-client-protocol.c -o .build/tests/xdg-protocol.o
c++ -std=c++23 tests/glass_client.cpp .build/tests/layer-protocol.o .build/tests/xdg-protocol.o \
  -I .build/umbriel/build -lwayland-client -o .build/tests/glass-client
"${GLASS_TEST_PYTHON:-/usr/bin/python3}" tests/render.py
