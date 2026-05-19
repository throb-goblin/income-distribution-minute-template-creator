# Trust Deed Review And Income Distribution Minute Template

This is a work-in-progress Python FastAPI action service for an Australian trust deed review and income distribution minute template Custom GPT.

The intended workflow is:

1. Upload a trust instrument and, where relevant, a company report.
2. Extract trust facts, clause references, company details and unresolved issues.
3. Present a Markdown trust review checklist for user approval.
4. After approval, generate a final checklist DOCX and a deed-specific trust minute template DOCX.

## Public Repository Scope

This public WIP repository intentionally excludes proprietary Word template binaries and matter-specific client documents.

Excluded:

- source `.docm` / `.dotm` / `.docx` / `.dotx` templates
- prepared working Word templates
- matter-specific trust deeds and company reports
- logs, temporary files and local tunnel binaries

Template folders are retained with placeholder files only:

- `templates/source/`
- `templates/working/`

To run full DOCX generation locally, supply your own source templates and run:

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

The `gpt/` folder contains action-backed GPT instruction assets. Use the separate `trust-deed-review` repository if you only need deed review and Markdown checklist generation without a hosted endpoint.

## License

MIT.
