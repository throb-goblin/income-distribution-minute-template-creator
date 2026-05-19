# Trust Minute Field Dictionary

All extracted values use the evidence-bearing object shape:

`value`, `source_document_id`, `page`, `clause_ref`, `heading`, `quote`, `confidence`, `issue_if_any`.

Key linked clause fields:

- `trust.vesting.clause_ref`: Vesting, termination or perpetuity-period provision reference. Used in both checklist and minute recitals.
- `trust.vesting.date`: Latest vesting date, termination date, or formula/mechanism by which trust assets must vest.
- `income.definition_clause_ref`: Trust income, net income or distributable income definition.
- `income.distribution_power_clause_ref`: Trustee power or obligation to distribute, pay or accumulate income.
- `income.streaming_clause_ref`: Power to stream or classify income.
- `income.accumulation_clause_ref`: Power to accumulate income.
- `capital.determination_clause_ref`: Power to determine, allocate or advance capital.
- `beneficiaries.definition_clause_ref`: Beneficiary definition for discretionary trusts.
- `unitholders.register_clause_ref`: Unit register or unitholder definition for unit trusts.
- `distribution.method_clause_ref`: Clause supporting the method of distribution.
- `distribution.resolution_deadline_clause_ref`: Clause requiring resolution before a specific date, including before 30 June.
- `amendment_review.power_clause_ref`: Power to amend or vary the deed.

Template selection:

- `trust.type = discretionary`: use the discretionary trust minute template.
- `trust.type = unit`: use the unit trust minute template.
- `trustee.is_corporate = true` and two or more directors: use corporate multi-director execution.
- `trustee.is_corporate = true` and one director: use corporate sole-director execution.
- `trustee.is_corporate = false` and one trustee: use individual sole-trustee execution.
- `trustee.is_corporate = false` and two or more trustees: use individual multi-trustee execution.

Checklist output:

- `generateTrustChecklist` returns `checklist_summary.checklist_markdown` for chat review.
- The checklist columns are `Item`, `Relevant clause(s)`, `Extracted detail` and `Status`.
- `Trust Review Checklist.csv` contains only clean row metadata: `row_id`, `Item` and `Applies to`.
- `templates/fieldmaps/checklist_helper_map.json` contains helper prompts, canonical field paths, applicability and builder mapping. Do not preserve helper text in generated chat or DOCX output.
- The GPT presents the Markdown checklist in chat and asks the user to approve or correct each row.
- The final checklist DOCX is generated only when `generateTrustMinute` is called after approval. It is landscape, Arial 8.
- If a relevant clause cannot be identified, write `Clause not found` in both `Relevant clause(s)` and the detail/notes cell, and set `Status` to `Review`.

Trust type extraction:

- Unit trust: deed uses `unit`, `units`, `unit holder`, `unitholder`, `initial unitholder`, `unit register`, `unit certificate` or similar unit-capital language.
- Discretionary trust: deed uses discretionary/family trust wording and beneficiary-class concepts without unit-capital language.
- Hybrid or unsure: both concepts appear, or the evidence does not support a confident classification. Raise an issue and require checklist review.

Vesting and perpetuity extraction:

- Identify the latest date or mechanism by which the trust assets vest. This may be an explicit date or a formula tied to the perpetuity period.
- Search for `Vesting Date`, `Termination Date`, `perpetuity period`, `rule against perpetuities`, `less one day`, and jurisdiction-specific perpetuity wording.
- Do not invent a calendar date. Calculate or state a calendar date only if the deed date, governing law and formula clearly support it.
- Where the deed uses the jurisdiction's perpetuity period, include the jurisdiction note in `trust.vesting.date` and retain the supporting quote.

Jurisdiction perpetuity guide for review:

- New South Wales: 80 years from the date the settlement takes effect.
- Victoria: 80 years from the date the settlement takes effect.
- Queensland: 125 years from the day the disposition is made unless the trust terms state or imply a shorter period. The 125-year regime commenced on 1 August 2025.
- South Australia: no fixed statutory perpetuity period; rules against perpetuities and excessive accumulations are abolished.
- Western Australia: 80 years from the date the settlement takes effect.
- Tasmania: 80 years from the date the settlement takes effect.
- Australian Capital Territory: 80 years from the date the settlement takes effect.
- Northern Territory: either lives in being plus 21 years, or 80 years from settlement taking effect, whichever is specified in the settlement. If no period is specified, 80 years applies.

Validation blockers:

- Trust type is `unsure`.
- Trustee type is unresolved.
- Corporate trustee details are missing where a corporate trustee is required.
- Trust instrument is missing.
- Vesting date or vesting clause is missing.
- Income definition or distribution power clause is missing.
- A deed amendment is noted but the amended deed is not included.

Annual details such as income year, resolution date, named beneficiaries or unitholders, proportions, streaming choices and method of distribution are not validation blockers for deed-specific minute template generation.

The GPT should obtain validation-blocker fields from the extraction result and checklist, not by separately asking the user to type them in. The user approval point is checklist review: the user either approves the extracted details or corrects them there.

Drafting guardrails:

- Never guess a clause number.
- Use `Clause not found` where the deed does not disclose a clause.
- Preserve evidence and confidence for practitioner review.
- Generated documents are drafting aids for review by an Australian legal practitioner.

Minute template guardrails:

- Preserve the source minute template format and wording.
- Do not add generated trust/deed details tables, clause-reference schedules, drafting-aid disclaimers or explanatory comments.
- Keep the standard income determination, income class/category, capital non-determination, method of distribution and confirmation wording unless the deed requires a mandatory change or the user asks for one.
- For broadly defined discretionary trust beneficiaries, use the default discretionary template wording.
- For unit trusts, use schedule/unit register/unit certificate evidence to identify unit holdings where available.
