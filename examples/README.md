# Fictional Interface Examples

These records illustrate the required data contracts. All publishers, URLs, excerpts, and claims are invented. Dates are fixed to the example as-of date **2026-10-08**. Never use these records as collected evidence or publish the sample content.

## Record shapes

Read `sources.json`, `candidates.jsonl`, and `items.jsonl` to see the difference between a configured source, a discovered item, and retained evidence. The item records point to real local text and segment files within this example folder. There are no downloadable media files; the `.example` URLs deliberately do not identify live sources.

`decisions.jsonl`, `briefs.jsonl`, `articles.jsonl`, and `video_scripts.jsonl` show how decisions and claims connect to evidence versions and content files. Only one brief and short content fragments are included. They are deliberately below the assignment's quantity and length requirements.

`review.json` and `approval.json` illustrate a failed check and a request to revise. They do not authorize any real publication. `publication_links.json` illustrates the three-piece link record before publication.

## Deterministic checks after implementation

Run these checks in a disposable copy of your completed repository so the fictional items stay separate from live evidence.

1. Initialize an empty store. Ingest `items.jsonl` and compare the ordered change records to `initial_changes_expected.jsonl`. Expect three new items.
2. Ingest `replay_items.jsonl` into that same store. Compare to `replay_changes_expected.jsonl`. Expect four unchanged observations, including a duplicate and refreshed retrieval timestamps, followed by one changed version. The store should still contain three logical items, with two versions of the podcast item. The first version must remain retrievable.
3. Run the date filter with `run.json` as the example run metadata and `filter_input.jsonl` on stdin. Compare eligible IDs and exclusion reasons with `filter_expected.json`, ignoring output order. The 30-date window is September 9 through October 8, inclusive. The deliberately malformed date should be excluded with `invalid_date`, rather than crashing the filter.
4. Inspect the references in `briefs.jsonl`. Each quote or segment must resolve to the specified item version and its retained source file.

For these examples, version IDs hash sorted, compact JSON containing title, URL, publication date, extracted text, and transcript segments. Your implementation may use another documented deterministic version computation. The store checks treat supplied version IDs as opaque strings; retrieval timestamps must not cause a new version.

These are bounded component checks. Passing them does not demonstrate live collection, good editorial judgment, complete content generation, or publication. Show those capabilities using your own sources and outputs.
