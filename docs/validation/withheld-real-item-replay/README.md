# Withheld real item replay

This is a clearly labeled **replay**, not a live pipeline run. It demonstrates the no-meaningful-new-material case required by the assignment: one actual eligible, accepted record is held out of a 35-item baseline, introduced as one new record, then replayed unchanged. All 36 records keep their original `item_id`, `version_id`, and other source metadata.

The utility reads only the named live run's `eligible.jsonl`, `decisions.jsonl`, `changes.jsonl`, and `run.json`. It copies the store/filter entrypoints and shared utility into a temporary project with a disposable SQLite database. It does not open the persistent evidence database, edit run artifacts, use the network, call a model, or fabricate an editorial decision. The replay metadata uses the source run's actual `as_of_date` and labels `mode` as `replay`.

Reproduce from the repository root:

```bash
python3 docs/validation/withheld-real-item-replay/replay.py runs/20261013T000115Z-e07304
```

By default, the script selects the first same-version `accept` decision whose record was `unchanged` in that live run. Override with `--item-id ITEM_ID` to choose another eligible item with a same-version decision. The run writes the measured change streams, disposable-store corpus, date-filter outputs, receipts, and `result.json` beside this README.

The included results record the selected item's real live decision as context. Replaying it as `new` reflects its deliberate omission from this isolated baseline; it does not mean the persistent live store lacked the item. The experiment does not claim a new editorial decision or a second live-run date.


## Staged evidence copy

This directory is a sanitized derivative of the local replay artifacts, not their original byte-for-byte archive. Private message identifiers and paths to omitted downloaded media/transcripts were removed; source item/version identifiers, external source URLs, timestamps, decisions, changes, and measured counts were retained. The replay script resolves project paths relative to this repository and requires no network or model access.
