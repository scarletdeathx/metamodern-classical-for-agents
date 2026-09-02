#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
UPSTREAM_ROOT=${1:-"$PROJECT_ROOT/vendor/tsotchke_quantum_rng"}
OUTPUT_ROOT=${2:-"$PROJECT_ROOT/.dependency-work/builds"}
SOURCE_ROOT="$UPSTREAM_ROOT/src"
OUTPUT_PATH="$OUTPUT_ROOT/libmcfa_tsotchke.dylib"

if [ ! -f "$UPSTREAM_ROOT/LICENSE" ] || [ ! -f "$SOURCE_ROOT/quantum_rng/quantum_rng_v3.c" ]; then
  echo "error: expected the pinned quantum_rng source snapshot at $UPSTREAM_ROOT" >&2
  exit 2
fi

mkdir -p "$OUTPUT_ROOT"

clang -dynamiclib -O3 -fPIC -Wall -Wextra -std=c11 -D_GNU_SOURCE \
  -install_name @rpath/libmcfa_tsotchke.dylib \
  -I "$SOURCE_ROOT/quantum_rng" \
  -I "$SOURCE_ROOT/entropy" \
  -I "$SOURCE_ROOT/health" \
  -I "$SOURCE_ROOT/profiling" \
  -I "$SOURCE_ROOT/common" \
  "$SOURCE_ROOT/quantum_rng/quantum_rng_v3.c" \
  "$SOURCE_ROOT/quantum_rng/quantum_state.c" \
  "$SOURCE_ROOT/quantum_rng/quantum_gates.c" \
  "$SOURCE_ROOT/quantum_rng/bell_test.c" \
  "$SOURCE_ROOT/quantum_rng/grover.c" \
  "$SOURCE_ROOT/quantum_rng/matrix_math.c" \
  "$SOURCE_ROOT/quantum_rng/simd_ops.c" \
  "$SOURCE_ROOT/quantum_rng/accelerate_ops.c" \
  "$SOURCE_ROOT/entropy/entropy_pool.c" \
  "$SOURCE_ROOT/entropy/hardware_entropy.c" \
  "$SOURCE_ROOT/health/health_tests.c" \
  "$SOURCE_ROOT/profiling/performance_monitor.c" \
  -framework Accelerate -lm -lpthread \
  -o "$OUTPUT_PATH"

echo "$OUTPUT_PATH"
