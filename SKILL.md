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

## Repository Evidence Rules

- When reading `classification_input`, use `analysis_depth`, `matched_files`, `probe_summary`, and `evidence_snippets` as the primary evidence surface.
- Prefer concrete repo evidence over README-only claims; if the probe output and README disagree, trust the probe evidence and note the mismatch.
- If `analysis_depth` is `fallback` or `fallback_used` is true, say that explicitly in `reason` and keep confidence conservative.
- Keep `reason` and `summary` in Chinese.

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
        "reason": "仓库描述和 README 都明确聚焦于浏览器工作流执行。",
        "summary": "用于自动执行网站上的浏览器工作流。",
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
