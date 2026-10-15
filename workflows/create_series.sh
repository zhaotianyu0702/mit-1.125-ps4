#!/usr/bin/env bash
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib/env.sh"
[[ "$#" -eq 1 && -f "$1/run.json" ]] || { echo 'Usage: create_series.sh RUN_DIR' >&2; exit 2; }
run_dir="$1"
export PS4_RUN_DIR="$run_dir"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
code=0
run_stage() {
  local script="$1" input="$2" output="$3" rc
  if [[ ! -f "$input" ]]; then echo "Missing upstream artifact: $input" >&2; return 1; fi
  bash "$script" "$run_dir" < "$input" > "$output.partial"
  rc=$?
  if [[ "$rc" -eq 0 ]]; then mv "$output.partial" "$output"; else
    [[ -s "$output.partial" ]] || rm -f "$output.partial"
  fi
  return "$rc"
}
if run_stage editorial/select_items.sh "$run_dir/eligible.jsonl" "$run_dir/decisions.jsonl"; then
  if run_stage editorial/create_briefs.sh "$run_dir/decisions.jsonl" "$run_dir/briefs.jsonl"; then
    run_stage content/write_articles.sh "$run_dir/briefs.jsonl" "$run_dir/articles.jsonl" || code=1
    run_stage content/write_video_scripts.sh "$run_dir/briefs.jsonl" "$run_dir/video_scripts.jsonl" || code=1
  else code=1; fi
else code=1; fi
# Even a blocked generation gets an honest assessment of missing artifacts.
if bash review/check_content.sh "$run_dir" > "$run_dir/.review.tmp"; then
  mv "$run_dir/.review.tmp" "$run_dir/review.json"
  "$PS4_PYTHON" -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("passed") else 1)' "$run_dir/review.json" || code=1
else code=1; fi
"$PS4_PYTHON" lib/runtime.py receipt "$run_dir" workflows/create_series "$started" "$code"
exit "$code"
