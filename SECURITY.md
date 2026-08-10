# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in sap-nexus-agent, please report it
responsibly:

- **Do not** open a public GitHub issue.
- Use GitHub's private vulnerability reporting ("Report a vulnerability") on
  the repository, or email the maintainer at the address listed on the GitHub
  profile.
- Include a description of the issue, steps to reproduce, and an impact
  assessment.
- You will receive an acknowledgement within 5 business days.

Please do not include real SAP credentials or production data in a report.

## Security Model

sap-nexus-agent mediates LLM-driven access to SAP systems. The architecture
enforces the hard boundaries below. The authoritative list lives in `CLAUDE.md`
§2; this document summarizes it for external contributors.

### Capability execution

- The LLM selects from **registered capabilities only**; it can never generate
  arbitrary RFC names.
- The Gateway accepts a `capabilityId` only, never a request-provided `rfcName`.
- Missing or invalid required parameters stop execution **before** reaching SAP.

### SAP execution

- **READ capabilities MUST NOT** call `BAPI_TRANSACTION_COMMIT` or
  `BAPI_TRANSACTION_ROLLBACK`.
- **WRITE capabilities MUST NOT** execute until Human Approval is confirmed for
  that capability. Human Approval is a recorded acceptance item ("a recorded
  human confirmation exists for this WRITE capability before execution"), not a
  chat sentence.

### Sensitive data

- Credentials, tokens, API keys, and connection strings live only in `.env` or
  the process environment. They are never committed (`.env` is git-ignored) and
  never printed (runtime output is redacted).
- `.env.example` contains placeholders only.
- Native SAP JCo libraries (`sapjco3.jar`, `libsapjco3.*`) are proprietary and
  must not be redistributed; they are git-ignored. Contributors must supply
  them locally under a valid SAP license.

## Scope

This policy covers the sap-nexus-agent codebase. Vulnerabilities in upstream
dependencies should be reported to their respective maintainers.
