# Setup and execution

This repository implements the MIT 1.125 PS04 pipeline for **Ship, Then Verify**, a publication about evaluating AI coding assistants for small software teams. The project configuration, source list, editorial policy, four prompts, and all 16 required Bash entrypoints are included. Each live run stores its own captured date, configuration, prompts, evidence records, decisions, briefs, drafts, review, and stage receipts.

## Requirements

- Bash and Python 3.12 (core helpers also support Python 3.9).
- Install the pinned packages with:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
```

- `yt-dlp` supports YouTube source retrieval. `ffmpeg` is used for audio conversion when needed. `whisper-cli` and the model in `models/provenance.json` are optional local transcription fallbacks.
- Editorial inference is configured for OpenAI Codex CLI, model `gpt-6-luna`, through the existing ChatGPT login. The adapter finds `codex` on `PATH`, or accepts an executable path in `PS4_CODEX_BIN`; no API key or API billing is used. Existing login and Codex access are prerequisites.

## Commands

```bash
bash tests/run_checks.sh
bash run.sh
# Resume only on the same UTC date, using the printed run directory:
bash run.sh --resume runs/RUN_ID
# Package only after checking the current review and actual student approval:
bash run.sh --package runs/RUN_ID
```

The submitted actual runs are [October 12](../runs/20261012T214349Z-992554/summary.json) and [October 13](../runs/20261013T000115Z-e07304/summary.json). They are preserved as distinct UTC dates. The October 12 student-feedback revision contains the selected three article/script pairs; see `../revisions/20261012T225329Z-student-feedback/`. Run summaries preserve their historical automated status. Current review, approval, package, and publication links belong in `SUBMISSION.md`.

Use `bash data/store.sh init` to initialize a missing store; it does not erase existing records. Only the store interface accesses the SQLite database. The included records reference repository-relative `data/assets/` text and timestamp segments; downloaded source media and the database are deliberately omitted.
