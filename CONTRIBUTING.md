# Contributing to Cora AI Meeting Notes

Thanks for helping! Cora is a local-first macOS app, so every change should keep two promises:
**meeting data stays on the user's Mac unless they explicitly opt in**, and **the app keeps working
offline on Apple Silicon**.

## Getting set up

You need macOS 14+ on Apple Silicon, the Xcode Command Line Tools and Homebrew.

```bash
make setup   # locked Python + Node deps, Swift helpers, git hooks
make dev     # run the app
```

To run a dev copy next to an everyday install, with throwaway data, see
[docs/SETUP.md](docs/SETUP.md#running-a-second-instance-for-development).

## Code map

| Area | Where | Notes |
|---|---|---|
| Electron shell | `src/main.js`, `src/main/` | tray, windows, capture state machine; `security.js` gates IPC |
| Dashboard UI | `src/ui/web/js/*.js` | classic scripts sharing one scope, loaded in `index.html` order |
| Local API | `python/api/` | add endpoints in `routes/<area>.py` with `@route(...)` |
| Pipeline | `python/pipeline/` | `runner.py` orchestrates audio → transcript → speakers → notes |
| Data locations | `python/paths.py` | never hardcode paths; user data lives in the data dir |
| Outbound policy | `python/policy.py` | every network feature must respect enterprise lockdown |
| AI tracing | `python/ai_trace.py` | wrap new model calls in `ai_trace.span(...)` |
| Native helpers | `capture/`, `bin/` | Swift, built by `make build-native` |

`python -m pipeline.runner <recording-id>` runs the pipeline on one recording from the command line.

## Before you open a PR

```bash
make lint    # ruff, ESLint, cross-file UI lint
make test    # pytest (MLX-heavy tests are marked and skipped in CI)
```

- Keep changes focused; match the surrounding style and comment density.
- Add or update tests for behaviour changes (`tests/`); the API auth tests must keep passing.
- **Security-sensitive areas** — `python/api/auth.py`, `python/api/http.py`, `src/main/security.js`,
  `python/policy.py`, anything that renders user or model text into HTML — need an explicit note in the
  PR describing the threat you considered.
- **Never commit** recordings, transcripts, voice clips, databases, API keys or personal config.
  `.gitignore` and the gitleaks pre-commit hook help, but the responsibility is yours.
- New outbound network calls must be opt-in, blocked by `policy.require_outbound_allowed(...)` under
  lockdown, and documented in the README's Privacy section.

## Commit messages

Conventional-ish prefixes help the changelog: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `build:`,
`chore:`. By contributing you agree your work is licensed under the project's [MIT License](LICENSE).

## Reporting bugs and security issues

Use the issue templates for bugs and ideas. **Do not** file public issues for vulnerabilities — see
[SECURITY.md](SECURITY.md). Please never attach real meeting recordings or transcripts to issues.
