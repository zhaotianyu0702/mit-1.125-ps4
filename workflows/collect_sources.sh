#!/usr/bin/env bash
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib/env.sh"
[[ "$#" -eq 1 && -f "$1/run.json" ]] || { echo 'Usage: collect_sources.sh RUN_DIR' >&2; exit 2; }
run_dir="$1"
export PS4_RUN_DIR="$run_dir"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
code=0
errors=()
mkdir -p "$run_dir/candidates"
for kind in feeds youtube podcasts; do
  bash "collectors/fetch_${kind}.sh" "$run_dir" > "$run_dir/candidates/$kind.jsonl"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then code=1; errors+=("fetch_$kind exited $rc; partial records retained"); fi
done
cat "$run_dir/candidates/feeds.jsonl" "$run_dir/candidates/youtube.jsonl" "$run_dir/candidates/podcasts.jsonl" > "$run_dir/candidates.jsonl"
# Real Unix pipe: extract consumes the record stream emitted by the input reader.
cat "$run_dir/candidates.jsonl" | bash processing/extract_content.sh "$run_dir" > "$run_dir/items.jsonl"
rc=$?
if [[ "$rc" -ne 0 ]]; then code=1; errors+=("extract_content exited $rc; successful items retained"); fi
bash data/store.sh upsert "$run_dir" < "$run_dir/items.jsonl" > "$run_dir/changes.jsonl" || { code=1; errors+=("evidence upsert failed"); }
bash data/store.sh list > "$run_dir/corpus.jsonl" || { code=1; errors+=("corpus export failed"); }
bash processing/filter_items.sh "$run_dir" < "$run_dir/corpus.jsonl" > "$run_dir/eligible.jsonl" || { code=1; errors+=("date filter failed"); }
if [[ "${#errors[@]}" -gt 0 ]]; then
  "$PS4_PYTHON" lib/runtime.py receipt "$run_dir" workflows/collect_sources "$started" "$code" "${errors[@]}"
else
  "$PS4_PYTHON" lib/runtime.py receipt "$run_dir" workflows/collect_sources "$started" "$code"
fi
exit "$code"
