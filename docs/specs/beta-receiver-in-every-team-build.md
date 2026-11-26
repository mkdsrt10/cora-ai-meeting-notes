---
title: Every team build carries the beta receiver, and Cora says when it cannot share
status: ready-for-agent
created: 2026-11-17
issue: https://github.com/mkdsrt10/cora-ai-meeting-notes/issues/25
plan_item: team beta, 0.4.5
glossary: Team build, Beta receiver, Install, Usage event
---

# Every team build carries the beta receiver, and Cora says when it cannot share

## Problem Statement

A teammate used Cora every day for several days and never appeared in the beta usage data. Their Mac ran a 0.4.4 **team** build, the Settings › Beta "Share usage" switch was on, and Cora had queued 120+ Usage events, none of them ever sent. The cause: that copy was a `--team` copy built without the beta receiver URL and token. `scripts/build-app.sh --team` only prints a warning when they are missing and finishes the build anyway, so a build that can never send looked exactly like one that does.

Nothing told anyone. Settings showed the switch on. `GET /api/beta/status` said `sharing_enabled: false` with no reason. The sender never logs why it is idle. Diagnosing it took a day of back-and-forth (network, VPN, proxy) before the build itself was found to be the problem.

## Solution

Every team build that can reach a tester carries the beta receiver, or it is not built. When a copy of Cora cannot share, Settings › Beta says why, in words the tester can act on. Testers who already have a build without the receiver get a working one through the normal in-app update banner, with nothing to do but click Update.

## User Stories

1. As the person cutting a beta release, I want `build-app.sh --team` to stop before any slow step when the receiver URL or token is missing, so that a build that cannot send never exists.
2. As the person cutting a release, I want the receiver settings read from a local file on the release Mac when they are not in my shell, so that I do not have to export them by hand each time.
3. As the person cutting a release, I want the build to read back the stamped `build-info.json` and fail if the receiver is empty, so that a stamping bug cannot slip through.
4. As a developer, I want `--team --no-telemetry` for a local `--team` copy that must not send, with a warning that it must never be published, so that the guard does not block local testing.
5. As a beta tester, I want Settings › Beta to tell me when this copy of Cora cannot share (built without the receiver, or enterprise lockdown), so that a switched-on toggle never misleads me.
6. As a beta tester with sharing working, I want to see when Cora last sent, how many events are waiting, or the last send error, so that I can tell if it is working.
7. As a support person, I want `GET /api/beta/status` to return a `sharing_off_reason` (`lockdown`, `switched_off`, `no_receiver`), so that one command on a tester's Mac shows the cause.
8. As a beta tester on a build without the receiver, I want the next release's update banner to replace it with the published build, so that I start sending without reinstalling by hand, and my queued events (up to 7 days old) go out.

## Implementation Decisions

- `scripts/lib/beta-receiver.sh` (sourced by the build and the tests): `beta_receiver_load` reads the env file (tolerates `export`, quotes, spaces around `=`, `#` lines, CRLF, no final newline; shell values win), `beta_receiver_problem` names what is wrong without printing the token, `beta_receiver_check_stamped` reads `build-info.json` back. A public build never carries the receiver (its DMG is public): it is unset, and a stamped one fails the build.
- `scripts/build-app.sh`: receiver preflight right after option parsing (env vars, else `$CORA_BETA_ENV_FILE`, default `~/.cora-signing/beta-receiver.env`, KEY=value lines, never in the repo); `--no-telemetry` only with `--team`; read-back of `build-info.json` after stamping.
- `usage_events.sharing_off_reason()` is the single source; `sharing_enabled()` is defined from it.
- `/api/beta/status` adds `sharing_off_reason`. Settings › Beta shows one line under the toggle (`#settingsShareStatus`), re-read when the toggle changes; nothing when the toggle is simply off.
- The in-app updater already offers any newer release to any packaged copy and checks only the release checksum, so a build without the receiver is replaced by the published one on update. No updater change.

## Testing Decisions

- Python: status reason for none / lockdown / switched off / missing URL / missing token, through the real route.
- Renderer (Node VM, as `test_beta_settings_ui.py`): the line for no receiver, lockdown, switched off, waiting count, last sent, last error; re-read on toggle.
- Build script: `--team` with no receiver exits 1 before building; an empty env file does not count; `--no-telemetry` alone is refused; the env file supplies both values (a token may contain `=`).

## Out of Scope

- Moving the receiver off its current host (separate decision).
- Logging sender errors to a file (the status line covers the tester-facing need).

## Further Notes

- **Release Mac setup, once.** Create `~/.cora-signing/beta-receiver.env` (mode 600) with
  `CORA_BETA_RECEIVER_URL=…` and `CORA_BETA_TOKEN=…`, next to the signing keychain. The values
  can be copied from an installed Team build's `Contents/Resources/build-info.json`. After that,
  `scripts/build-app.sh --team` needs nothing exported.
- **Testers on a build without the receiver.** Nothing to do on their side beyond clicking
  Update when 0.4.5 is offered. Their unsent Usage events are kept up to 7 days
  (`QUEUE_MAX_AGE_DAYS`) and go out on the first start of the updated app. If that copy was signed
  with a different identity, macOS may ask for permissions again after the update.
- **Teammates do not build Cora** for daily use; `docs/TEAM_SETUP.md` step 1 is the only install path.
