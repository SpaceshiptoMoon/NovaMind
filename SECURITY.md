# Security Policy

## Supported Versions

NovaMind is under active development. Security fixes are best-effort for the latest state of the default branch.

If you run NovaMind in production, pin a known-good revision and review release notes before upgrading.

## Reporting a Vulnerability

Please do not disclose security vulnerabilities in public issues, discussions, or pull requests.

Instead, report them privately with:

- A clear description of the issue
- Affected components and configuration
- Reproduction steps or proof of concept
- Potential impact
- Suggested mitigation if available

If you do not yet have a private reporting channel configured for this repository, create one before broadly promoting the project as production-ready. Until then, treat public deployment as operator-managed risk.

## Security Notes for Operators

NovaMind includes components that need careful production hardening:

- Secrets must not be committed to the repository. Start from `.env.example`.
- Review all YAML config files before production use.
- Replace development credentials and generated defaults.
- Put the application behind HTTPS and a managed reverse proxy in production.
- Restrict access to MySQL, Redis, MinIO, and Elasticsearch to private networks.
- Review file upload and code-execution related features before exposing them to untrusted users.
- Review Agent, MCP, and terminal-like capabilities with a least-privilege mindset.

## Scope

This policy covers vulnerabilities in the code and default deployment materials in this repository. It does not cover:

- third-party infrastructure you operate incorrectly
- unsupported forks with unreviewed changes
- secrets already exposed outside this repository
