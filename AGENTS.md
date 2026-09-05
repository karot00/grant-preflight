# Agent Working Agreement

This project is implemented under strict user supervision.

## Required Workflow

1. Read `implementation_plan.md` and `project_progress.md` before starting implementation work.
2. Select one clearly bounded work unit that is small enough to implement and verify in a single session.
3. Never take the entire application, a whole complex phase, or multiple unrelated features as one work unit.
4. Split a complex phase into smaller independently verifiable units before starting it.
5. Complete only the selected work unit, including its relevant tests or other verification.
6. Do not start the next work unit automatically.
7. Append a progress entry to `project_progress.md` immediately after completing or stopping the work unit. Never replace or rewrite earlier entries.
8. Report the result to the user and request explicit confirmation and permission before continuing to the next work unit.

## Progress Entry Requirements

Every entry appended to `project_progress.md` must include:

- Date and time in UTC
- Work unit scope
- Files changed
- Commands and tests run, with observed results
- Completed behavior
- Remaining issues or blockers
- Proposed next work unit, which must not begin without user approval

## Scope And Safety

- Follow `implementation_plan.md` as the authoritative implementation specification.
- Prefer the smallest correct change and avoid unrelated edits.
- Do not claim unrun tests, working integrations, completed deployment, or other unverified outcomes.
- Never write credentials, API keys, private-key contents, passphrases, or other secrets to source-controlled files, logs, progress entries, prompts, or responses.
- If the current work unit grows substantially beyond its stated scope, stop at a safe boundary, record progress, and request approval for a smaller follow-up unit.
