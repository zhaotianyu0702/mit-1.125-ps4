#!/usr/bin/env bash
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
code=0
if [[ "$#" -eq 0 ]]; then
  run_dir="$($PS4_PYTHON lib/runtime.py init)" || exit 2
  export PS4_RUN_DIR="$run_dir"
  bash data/store.sh init || code=1
  bash workflows/collect_sources.sh "$run_dir" || code=1
  bash workflows/create_series.sh "$run_dir" || code=1
elif [[ "$#" -eq 2 && "$1" == "--package" ]]; then
  run_dir="$2"
  [[ -f "$run_dir/run.json" ]] || { echo 'RUN_DIR not found' >&2; exit 2; }
  export PS4_RUN_DIR="$run_dir"
  bash review/check_content.sh "$run_dir" > "$run_dir/.review.tmp" && mv "$run_dir/.review.tmp" "$run_dir/review.json" || code=1
  bash publishing/prepare_package.sh "$run_dir" > "$run_dir/.package-manifest.tmp" || code=1
  rm -f "$run_dir/.package-manifest.tmp"
elif [[ "$#" -eq 2 && "$1" == "--resume" ]]; then
  run_dir="$2"
  [[ -f "$run_dir/run.json" ]] || { echo 'RUN_DIR not found' >&2; exit 2; }
  run_dir="$("$PS4_PYTHON" lib/runtime.py resume "$run_dir")" || exit $?
  export PS4_RUN_DIR="$run_dir"
  bash workflows/create_series.sh "$run_dir" || code=1
else
  echo 'Usage: bash run.sh [--package RUN_DIR | --resume RUN_DIR]' >&2
  exit 2
fi
"$PS4_PYTHON" lib/runtime.py receipt "$run_dir" run "$started" "$code"
bash reporting/summarize_run.sh "$run_dir" > "$run_dir/.summary.tmp" || exit 1
mv "$run_dir/.summary.tmp" "$run_dir/summary.json"
cat "$run_dir/summary.json"
exit "$code"
