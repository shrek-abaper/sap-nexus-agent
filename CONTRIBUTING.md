# Contributing to sap-nexus-agent

Thanks for your interest in contributing! This guide covers the basics.

## Development setup

1. Clone the repository.
2. Copy `.env.example` to `.env` and fill in your SAP destination and LLM
   credentials. **Never commit `.env`.**
3. Frontend: `npm --prefix frontend install`.
4. Agent (Python): create a venv and `pip install -e agent`.
5. Gateway (Java/JCo): see `services/gateway/README.md`. You must supply the
   proprietary `sapjco3.jar` yourself under a valid SAP license; it is not
   bundled and is git-ignored.

## Workflow

This project uses the **Comet** change workflow (see `.comet/config.yaml` and
`CLAUDE.md` for the authoritative rules). In short:

- The default workflow is **native** (entry: `/comet`).
- Structural schema / OWL / Neo4j migrations, or any change whose spec delta
  must be reviewable as an OpenSpec artifact, use **classic**
  (entry: `/comet-classic`).
- Do not run a native and a classic change on the same files at the same time.

If you are not using Comet, that is fine — keep changes surgical, verify before
opening a PR, and follow the commit rules below.

## Verification

Run only what your change touches:

| Change type                  | Command                                                    |
| ---------------------------- | ---------------------------------------------------------- |
| Schema / registry / ontology | `openspec list --json && openspec validate --all --strict` |
| Frontend                     | `npm --prefix frontend run verify`                         |
| Agent call-plan              | `scripts/verify-agent-callplan-evidence.sh`                |

Always run `git status --short` before and after non-trivial edits.

## Commit conventions

- Write clear commit messages describing **what** and **why**.
- Never commit `.env`, credentials, tokens, API keys, or runtime traces.
- Keep commits focused; one logical change per commit.

## Security

If your contribution touches the SAP WRITE path or credential handling, read
`SECURITY.md` first. WRITE capabilities require Human Approval before
execution; READ capabilities must never call `BAPI_TRANSACTION_COMMIT` or
`BAPI_TRANSACTION_ROLLBACK`.

## Licensing

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
