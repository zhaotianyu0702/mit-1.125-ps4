#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib/env.sh"
"$PS4_PYTHON" -m unittest discover -s tests -v
for f in run.sh workflows/*.sh collectors/*.sh processing/*.sh data/*.sh editorial/*.sh content/*.sh review/*.sh publishing/*.sh reporting/*.sh lib/*.sh adapters/*.sh tests/*.sh; do
  bash -n "$f"
done
shellcheck run.sh workflows/*.sh collectors/*.sh processing/*.sh data/*.sh editorial/*.sh content/*.sh review/*.sh publishing/*.sh reporting/*.sh lib/*.sh adapters/*.sh tests/*.sh
echo 'PASS: unit/integration tests, Bash syntax, and ShellCheck'
