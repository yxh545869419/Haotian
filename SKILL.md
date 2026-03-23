---
name: haotian
description: Use when refreshing Haotian's GitHub-trending capability intelligence, classifying staged repositories into the local taxonomy, or generating/updating Haotian Markdown and JSON reports.
---

# Haotian

Use this skill only when the user explicitly wants a Haotian refresh or report update. Do not run it automatically on repo open.

## Workflow

1. Run `python start_haotian.py` or `python start_haotian.py --date YYYY-MM-DD`.
2. Read the printed JSON summary.
3. If `status` is `awaiting_classification`, open:
   - the referenced `classification_input`
   - `docs/capability-taxonomy.md`
4. Write `classification-output.json` in the same run directory.
5. Run the same command again to finalize the database update and report generation.
6. Summarize the resulting Markdown/JSON reports for the user.

## Classification Output Rules

- Write plain JSON only. No markdown fences.
- Top level must be an array.
- One object per `repo_full_name`.
- Use only taxonomy ids from `docs/capability-taxonomy.md`.
- Do not invent repositories that are absent from `classification-input.json`.
- If evidence is weak, lower `confidence` and set `needs_review` to `true`.
- Set `source_label` to `"codex"`.

## Required Schema

```json
[
  {
    "repo_full_name": "acme/browser-bot",
    "capabilities": [
      {
        "capability_id": "browser_automation",
        "confidence": 0.91,
        "reason": "The repo description and README both focus on browser workflow execution.",
        "summary": "Automates browser workflows for websites.",
        "needs_review": false,
        "source_label": "codex"
      }
    ]
  }
]
```

## Completion

After the second run succeeds, check:

- `data/reports/YYYY-MM-DD.md`
- `data/reports/YYYY-MM-DD.json`
- `data/runs/YYYY-MM-DD/run-summary.json`

Then give the user a short summary of the latest report findings.
