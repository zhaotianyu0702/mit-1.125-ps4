# Staged run logs

Each selected run’s `summary.json` lists the sanitized receipt filenames under `stage_receipts.latest_receipts` and `stage_receipts.historical_failures`. The files are stored under the same `runs/RUN_ID/logs/` relative paths named in those entries. These receipts preserve stage, status, exit code, item counts, UTC times, portable tool labels, model/token usage, and cost values (including unknown `null` values). Raw error bodies, absolute paths, and raw model request/response logs are omitted.

The package-generation review and run receipts are in `revisions/20261012T225329Z-student-feedback/logs/`; `package_operation_receipts.json` maps its operation stages to those files. This was an editorial-revision package operation, not an additional full live run.

## Approval portability

The original revision review and package passed in the source checkout under the student's matching approval. This public copy is relocated and sanitizes the feedback provenance identifier and local media/transcript paths. The content fingerprint includes absolute checkout paths and those item fields, so a fresh review in another checkout receives a different review ID even though the three article files, three video-script files, and all referenced retained text and segment bytes are unchanged. The saved approval records the original gate result; the package gate correctly rejects it against a newly computed review ID. This relocation does not mean the original review failed, and the historical approval must not be treated as approval of a newly computed review ID. A new review ID requires a matching student approval before packaging in that checkout.
