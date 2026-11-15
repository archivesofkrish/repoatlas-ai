# Security Policy

## Supported versions

Security fixes are developed against the latest code on `main`. Until a release is published, no older version is considered supported.

## Reporting a vulnerability

Please do not publish exploit details in a public issue. Use GitHub's private vulnerability reporting feature for this repository where available. Include affected commit/version, impact, reproduction steps, and any suggested mitigation. Do not include real secrets or personal data.

## Security design notes

- RepoAtlas is read-only and does not execute repository code during ingestion.
- Repository content is untrusted data and must never be interpreted as system instructions.
- Secret detection is heuristic; it does not guarantee complete secret removal.
- Deployments must restrict repository paths, access credentials, and model-provider data sharing.
