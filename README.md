# Income Distribution Minute Template Creator

This is a work-in-progress Python FastAPI action service for an Australian trust deed review and income distribution minute template creator Custom GPT.

The intended workflow is:

1. Upload a trust instrument and, where relevant, a company report.
2. Extract trust facts, clause references, company details and unresolved issues.
3. Present a Markdown trust review checklist for user approval.
4. After approval, generate a final checklist DOCX and a deed-specific income distribution minute template DOCX.

## Public Repository Scope

This public WIP repository includes the source `.docm` minute templates used by the template-preparation pipeline. It intentionally excludes matter-specific client documents and generated working files.

Excluded:

- matter-specific trust deeds and company reports
- prepared working Word templates
- logs, temporary files and local tunnel binaries

Template folders:

- `templates/source/`: source `.docm` minute templates
- `templates/working/`: generated macro-free working `.docx` files, excluded from Git

To regenerate macro-free working templates locally, run:

```powershell
python scripts/prepare_templates.py
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Run Locally

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/docs
```

## Tests

Some template-rendering tests expect local working templates. In this public WIP repository, those binaries are intentionally excluded. Add local templates first before running the full suite.

```powershell
pytest
python scripts/lint_templates.py
```

## GPT Assets

The `gpt/` folder contains action-backed GPT instruction assets:

- `gpt/income_distribution_minute_template_creator_instructions.md`: Custom GPT instructions.
- `gpt/income_distribution_minute_template_creator_knowledge_manifest.json`: Setup checklist for GPT Knowledge and Actions.
- `gpt/income_distribution_minute_template_creator_conversation_starters.md`: Optional conversation starters.
- `gpt/field_dictionary.json`: Canonical fields and drafting guardrails.

The OpenAPI schema is:

- `openapi/income-distribution-minute-template-creator-action.openapi.yaml`

Use the separate `trust-deed-review` repository if you only need deed review and Markdown checklist generation without a hosted endpoint.

## License

MIT.
