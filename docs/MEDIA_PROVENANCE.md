# Evidence and media provenance

The two submitted live runs retain candidate, item, change, corpus, eligibility, decision, brief, article, video-script, review, and summary records. Their item records keep public source URLs, publication and retrieval dates, item/version identifiers, and repository-relative paths to retained text and timestamped segments. The exact referenced `data/assets/` files are included; checksums in their filenames allow the local bytes to be checked.

The SQLite evidence index and downloaded media are omitted. The index can be reconstructed only from retained item snapshots through the store interface; never edit or delete a database file directly. Initialize a missing database with `bash data/store.sh init`, then restore a run with `cat runs/RUN_ID/items.jsonl | bash data/store.sh upsert runs/RUN_ID`. Upsert retained run snapshots oldest to newest.

Public source URLs are retrieval routes, not guarantees of byte-for-byte reproduction: publishers can edit or remove pages, captions, and audio, and access controls or rate limits can change. Local media filenames are omitted from the public derivative; item records set those local paths to null while preserving source URLs and the text/segment locators used by the review.

One YouTube transcript was produced locally by Whisper `base.en`; it contains 375 machine-generated segments and has not been personally verified against the recording. The model provenance record gives its source URL and SHA-256. No 147 MB model binary or downloaded audio/video is included. Publisher transcripts and generated transcripts should both be checked against the source recording before relying on an audio claim.

A separate focused recovery added the second video item to the store after the initial October 12 collection failure; it is not another complete pipeline run. The small recovery metadata snapshot is in `runs/focused-recovery/`. The actual Oct 12 and Oct 13 runs each retain their own evidence snapshots. The October 13 changed ReviewBench version changes promotional footer text; the core findings remain unchanged.
