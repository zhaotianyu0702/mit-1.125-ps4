#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib/env.sh"
exec "$PS4_PYTHON" "collectors/collect.py" youtube "$@"
