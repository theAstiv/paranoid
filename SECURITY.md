# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.5.x   | Yes       |
| < 1.5   | No        |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Email: **astivhuman66@gmail.com**

Include in your report:
- Description of the vulnerability and its potential impact
- Steps to reproduce or proof-of-concept
- Affected version(s)
- Any suggested mitigations (optional)

You will receive an acknowledgement within **48 hours** and a status update
within **7 days**. If the issue is confirmed, a patch will be prioritised and
you will be credited in the release notes (unless you prefer to remain
anonymous).

## Scope

In scope:
- The FastAPI backend (`backend/`)
- The Svelte frontend (`frontend/`)
- The CLI (`cli/`)
- The GitHub Action (`action/`)

Out of scope:
- Vulnerabilities in third-party dependencies (report to the upstream project)
- Issues requiring physical access to the host machine
- Social engineering attacks

## Threat model notes

Paranoid is designed as a **self-hosted, single-user tool**. The threat model
assumes the operator controls the host environment and network access. API keys
are Fernet-encrypted at rest. Multi-user deployments are not yet supported and
have not been hardened for that use case.
