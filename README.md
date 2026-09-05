# Grant Preflight

Find the fit. Check the evidence. Draft with facts.

Grant Preflight is a Streamlit application that imports a supported funding
page, extracts requirements with Google Gemini, stores reviewed evidence,
computes a pursue/clarify/skip decision in pure Python from human-reviewed
evidence, and produces an editable first-draft proposal or clarification email
grounded in approved organization facts.

## Status

This repository is a Phase 1 project skeleton. Implementation proceeds under
`implementation_plan.md` (the authoritative runbook); `weekend_plan.md` and
`initial_plan.md` are historical planning context. The full README - setup
commands, exact version matrix, configuration variables, public versus operator
modes, Snowflake administration steps, test results, and known limitations - is
completed in Phase 7 (P7.1).

## Modes

- **Public demo** (`APP_MODE=public_demo`): recorded AI output and
  session-memory storage only; never holds API keys or database credentials.
- **Operator** (`APP_MODE=operator`): local process bound to `127.0.0.1:8501`
  with live Gemini extraction/drafting and Snowflake persistence. No public
  operator endpoint exists.

## License

MIT - see [LICENSE](LICENSE). Copyright 2026 Grant Preflight contributors.
