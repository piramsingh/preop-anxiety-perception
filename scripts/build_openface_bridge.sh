#!/usr/bin/env bash
# Builds the local bridge to OpenFace. Requires OpenFace built in ~/DEV/OpenFace (or OPENFACE_DIR).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
openface="${OPENFACE_DIR:-$HOME/DEV/OpenFace}"
prefix="$(brew --prefix openblas);$(brew --prefix dlib);$(brew --prefix tbb);$(brew --prefix boost)"
cmake -S "$root/native/openface_bridge" -B "$root/native/openface_bridge/build" \
  -DOPENFACE_DIR="$openface" \
  -DOpenCV_DIR="$(brew --prefix opencv@4)/lib/cmake/opencv4" \
  -DCMAKE_PREFIX_PATH="$prefix" -Wno-dev
cmake --build "$root/native/openface_bridge/build" -j8
