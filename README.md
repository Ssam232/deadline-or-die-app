# Paper queue

Branch for the reading-list pipeline. It has no app code, so pushes here never restart Deadline or Die.

1. A weekly scheduled search adds up to 5 papers in `queue/<date>.json`.
2. The push runs `import_papers.py` in GitHub Actions, which adds the papers to "LCR HCR CVxR" and its "To Read" folder in Zotero. Marking a paper Read or Dropped in Deadline or Die moves it to the "Read" or "Dropped" folder beside To Read.
3. Deadline or Die already reads "To Read", so the papers appear in the app.
4. Papers you add yourself go in the "Inbox" folder under LCR HCR CVxR. Deadline or Die can file them straight away; otherwise the Sunday 4:43 PM run moves them to To Read. Every paper the search didn't add is tagged "manual entry", and `unranked.json` lists the ones still needing an order or question tags, which the weekly search places through `placements/<date>.json`.

Processed files move to `done/`, and `imported.jsonl` records every outcome.

Needs the `ZOTERO_USER_ID` and `ZOTERO_API_KEY` Actions secrets, and the key needs write access.
After fixing a failed run, open it in the Actions tab and choose "Re-run all jobs".

Questions, used as `tags` codes:

| Code | Tag |
|---|---|
| `hcr-lcr` | Q1 What are HCR/LCR rats? |
| `remodeling` | Q2 What causes remodeling? |
| `diet-muscle` | Q3 How does diet change muscle? |
| `exercise-obese-muscle` | Q4 How does exercise change obese muscle? |
| `genetics-exercise` | Q5 How do genes and exercise interact? |
| `heart-diaphragm` | Q6 Why does heart + diaphragm failure matter? |
| `strip-testing` | Q7 How are muscle strips tested? |

Queue entry: `doi`, `pmcid` or `pmid`, plus `title`, `tags` and `level` (foundational, core, specialized or niche). Optional details become Zotero tags: `species` (rat, mouse, human), `sex` (male, female, both) and `type` (review, study, methods). Add `before` with a title from `reading-order.json` to place it ahead of that paper; otherwise it joins the end of its level. Each run adds at most 5 papers. For a page with no identifier, use
`"kind": "webpage"` with `title`, `url` and `source`.
