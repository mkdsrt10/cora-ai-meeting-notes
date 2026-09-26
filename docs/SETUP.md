# Setup and troubleshooting

## Fresh Mac

```bash
xcode-select --install        # once, if not already installed
make setup
make dev
```

`make setup` (`scripts/bootstrap.sh`) is safe to re-run. It:

1. checks macOS 14+ on Apple Silicon and the Xcode Command Line Tools;
2. installs `ffmpeg`, `node` and `uv` via Homebrew if missing;
3. installs Python deps exactly as locked in `uv.lock` (`uv sync --frozen`) into `.venv/`;
4. installs Node deps from `package-lock.json` (`npm ci`);
5. compiles the Swift helpers (`make build-native`) and ad-hoc signs them;
6. installs the gitleaks/ruff pre-commit hooks.

## macOS permissions

| Permission | Why | Where |
|---|---|---|
| Microphone | Record your side of the call | System Settings → Privacy & Security → Microphone |
| Screen Recording | ScreenCaptureKit needs it to capture system audio (other participants). No video is recorded. | … → Screen & System Audio Recording |
| Accessibility | Read the active-speaker indicator in Zoom/Meet/Teams for live speaker names | … → Accessibility |

When running from source, macOS attributes these to the app that launched Cora (Electron, or your
terminal). If a prompt never appears or recording is silent:

```bash
tccutil reset Microphone
tccutil reset ScreenCapture
tccutil reset Accessibility
```

then relaunch with `make dev` and accept the prompts again.

## Launching from /Applications

An installed `Cora.app` acts as a launcher for your checkout at `~/voicecoach-desktop`: it runs that
checkout's Python code and venv (see `resolveRoot()` in `src/main/paths.js`). Its own Electron code,
though, is frozen inside the bundle — after pulling or changing code, quit the app and run:

```bash
make install-app
```

Only `app.asar` is replaced, so macOS keeps the app's permissions. If the installed app opens but
shows nothing, its bundled code is out of date with the checkout — run `make install-app`.

## Running a second instance for development

You can run a dev build next to your everyday install without touching your real data:

```bash
VOICECOACH_PORT=8799 VOICECOACH_DATA_DIR=/tmp/cora-dev npx electron . --user-data-dir=/tmp/cora-dev-profile
```

## Talking to the local API from scripts

Every `/api` and `/media` request needs the per-launch token:

```bash
curl -H "X-VC-Token: $(cat "$DATA_DIR/.api_token")" http://127.0.0.1:8765/api/dashboard
```

POST bodies must be sent with `Content-Type: application/json`.

## Common problems

- **"Cora AI Meeting Notes could not start: another process is using port 8765"**: an older
  instance's server is still running. Quit the app from the tray, or `pkill -f python/server.py`.
- **Transcription fails with an ffmpeg error**: `brew install ffmpeg`, then relaunch.
- **Models download slowly on first run**: they're cached in `~/.cache/huggingface` after the first
  download.
