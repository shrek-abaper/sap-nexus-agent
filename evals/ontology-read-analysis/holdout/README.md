# Sealed holdout cases

This directory is empty in the shipped change. Human-supplied combination
questions are placed here only after C2 build, as `cases-*.json` files
using the same case contract as `../cases.json`.

Rules:
- No production or test code may reference concrete holdout case ids.
- The harness runs any `cases-*.json` present; absence means zero holdout
  cases (C2 default). Real holdout evaluation is a C3/user activity.
