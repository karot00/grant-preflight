# Project Progress

## 2026-09-05 10:51 UTC - Supervised agent workflow

- Work unit scope: Added project-level operating instructions for tightly supervised, incremental agent work.
- Files changed: `AGENTS.md`, `project_progress.md`.
- Commands and tests: Confirmed that no existing `AGENTS.md` file was present; no runtime tests were applicable.
- Completed behavior: Future coding agents must select bounded work units, verify each unit, append its outcome to this file, and obtain explicit user permission before beginning the next unit.
- Remaining issues or blockers: None for this work unit.
- Proposed next work unit: Begin the first bounded Phase 1 scaffold task only after explicit user approval.

## 2026-09-05 10:54 UTC - Phase 0 prerequisite preparation (retrospective)

- Work unit scope: Reviewed challenge readiness and prepared the human-owned external prerequisites for Google AI, Snowflake, and GitHub. DNS and deployment-host configuration were intentionally deferred.
- Files changed: `.env.operator.example`, `.gitignore`, and the ignored local `.env.operator`; no credentials or private-key material were added to source-controlled files.
- External resources prepared: The human created a Snowflake Standard trial account and the public GitHub repository `karot00/grant-preflight`. The repository was independently confirmed public and empty through its public GitHub page.
- Snowflake administration completed by the human: Queried account metadata; created the X-Small `GRANT_PREFLIGHT_WH` warehouse with auto-suspend and auto-resume; created the `GRANT_PREFLIGHT` database and `APP` schema; created the `GRANT_PREFLIGHT_APP` least-privilege role; granted warehouse, database, and schema usage; created the `GRANTS` and `ASSESSMENTS` tables; and granted the role `SELECT`, `INSERT`, and `UPDATE` on both tables.
- Snowflake authentication completed by the human: Generated an encrypted PKCS#8 RSA private key outside the repository, generated its public key, created the `GRANT_PREFLIGHT_SERVICE` service user, registered the public key, assigned the application role, and confirmed the user/role configuration in Snowflake. No key contents, account identifiers, or passphrases are recorded here.
- Local operator configuration completed: Added the Snowflake account, service user, private-key path, private-key passphrase, and fixed database/schema/warehouse/role names to the ignored `.env.operator`. Added a Gemini API key and the planned `gemini-3.5-flash` model setting to the same ignored file.
- Commands and tests: Snowflake SQL resource, table, grant, user-description, and role-assignment commands were reported successful by the human. A local non-secret validation loaded `.env.operator`, checked that required Gemini and Snowflake variables were non-empty, confirmed the private-key file existed, and ran `openssl pkey -check -noout`; observed result: `Key is valid`.
- Completed behavior: Local secret storage and cryptographic key loading are ready for the operator path. The planned Snowflake resources, tables, role, and key-pair service user exist. The public challenge repository exists within the challenge window.
- Remaining issues or blockers: A real Python Snowflake Connector login and real Gemini API request have not yet been run. DNS for `grant-preflight.karotammela.fi` is deferred. The Hetzner CX23 host is available over SSH but Docker, Compose, architecture, and ports 80/443 have not yet been verified. The local workspace has not yet been initialized or connected to the public GitHub repository.
- Proposed next work unit: Begin the smallest Phase 1 scaffold unit, including local Git/repository setup and the initial project skeleton, only after explicit user approval.
