# Security policy

Cora records meetings, so we treat vulnerabilities that could expose audio, transcripts or
credentials as critical.

## Reporting a vulnerability

Please report privately via GitHub: **Security → Report a vulnerability** on this repository
(private vulnerability reporting). Do not open a public issue or PR for security problems, and do
not include real meeting data in reports.

We aim to acknowledge reports within 3 working days and to ship a fix or mitigation for critical
issues within 30 days, crediting you in the release notes unless you prefer otherwise.

## Scope

In scope: the Electron app, the local API (`127.0.0.1:8765`), the Python pipeline, the Swift
capture helpers, and anything that could let another local user, a website, or a malicious
recording/transcript read data, run code, or send data off the machine.

Known design points (see the README's Security section): the local API requires a per-launch token
and pins Host/Origin to loopback; renderers are sandboxed with a strict CSP; enterprise lockdown
blocks all outbound features; user data is stored owner-only (0600/0700) and is not encrypted at
rest beyond FileVault.

## Supported versions

Security fixes land on `main` and in the latest release.
