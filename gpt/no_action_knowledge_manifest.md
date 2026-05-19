# No-Action GPT Knowledge Manifest

Use this file to set up the alternative GPT that prepares the trust review checklist in chat without using an action endpoint.

## Upload These Knowledge Files

Upload:

- `gpt/no_action_trust_review_instructions.md`
- `gpt/field_dictionary.md`
- `Trust Review Checklist.csv`
- `templates/fieldmaps/checklist_helper_map.json`

Optional:

- `gpt/no_action_conversation_starters.md`

## Do Not Upload These As Knowledge

- Matter-specific trust deeds.
- Matter-specific company reports.
- Client files.
- `templates/source/*.docm` or `templates/source/*.dotm`.
- `openapi/trust-minute-action.openapi.yaml`.

Matter documents should be uploaded only inside the relevant GPT chat.

## Recommended GPT Settings

- Name: `Australian Trust Deed Checklist Assistant`
- Description: `Reviews Australian trust deeds and company reports, extracts clause-backed trust facts, and prepares a Markdown checklist for practitioner review.`
- Capabilities: enable file uploads / data analysis if available.
- Actions: none.
- Knowledge: upload the files listed above.

This GPT is for extraction, checklist review and issue spotting only. Use the action-backed GPT once Azure App Service is available and exact DOCX checklist/minute generation is required.
