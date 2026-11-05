# Paper queue

Branch for the reading-list pipeline. It has no app code, so pushes here never restart Deadline or Die.

1. A weekly scheduled search adds up to 2 papers in `queue/<date>.json`.
2. The push runs `import_papers.py` in GitHub Actions, which adds the papers to the Zotero "To Read" and "LCR HCR CVxR" collections.
3. Deadline or Die already reads "To Read", so the papers appear in the app.

Processed files move to `done/`, and `imported.jsonl` records every outcome.

Needs the `ZOTERO_USER_ID` and `ZOTERO_API_KEY` Actions secrets, and the key needs write access.
After fixing a failed run, open it in the Actions tab and choose "Re-run all jobs".

Queue entry: `doi`, `pmcid` or `pmid`, plus `title`, `tags` and `level` (foundational, core, specialized or niche). Add `before` with a title from `reading-order.json` to place it ahead of that paper; otherwise it joins the end of its level. Each run adds at most 2 papers. For a page with no identifier, use
`"kind": "webpage"` with `title`, `url` and `source`.
