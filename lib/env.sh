#!/usr/bin/env bash
# Shared environment only: substantive behavior remains in each component.
PS4_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PS4_ROOT
if [[ -z "${PS4_PYTHON:-}" ]]; then
  if [[ -x "$PS4_ROOT/.venv/bin/python" ]]; then
    PS4_PYTHON="$PS4_ROOT/.venv/bin/python"
  else
    PS4_PYTHON="python3"
  fi
fi
export PS4_PYTHON
export PATH="$PS4_ROOT/.venv/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1
if [[ -z "${PS4_FFMPEG:-}" ]]; then
  PS4_FFMPEG="$($PS4_PYTHON -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null)" || PS4_FFMPEG="ffmpeg"
  export PS4_FFMPEG
fi
cd "$PS4_ROOT" || exit 2
