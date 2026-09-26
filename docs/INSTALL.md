# Installing Cora AI Meeting Notes

## Requirements

- A Mac with Apple Silicon (M1 or later), macOS 14 Sonoma or newer
- ~2 GB free for the app, plus ~1–3 GB for models downloaded on first use
- [ffmpeg](https://ffmpeg.org): `brew install ffmpeg` (onboarding tells you if it's missing)

## Install from the release

1. Download `Cora-AI-Meeting-Notes-<version>-arm64.dmg` from the
   [latest release](https://github.com/mkdsrt10/cora-ai-meeting-notes/releases/latest).
   Optionally verify it: `shasum -a 256 -c Cora-AI-Meeting-Notes-<version>-arm64.dmg.sha256`.
2. Open the DMG and drag **Cora AI Meeting Notes** into **Applications**.
3. **First launch.** The app is ad-hoc signed, not notarized by Apple (no paid Developer ID yet), so
   macOS refuses to open it the normal way. Either:
   - open **System Settings → Privacy & Security**, scroll to the message about Cora being blocked,
     and click **Open Anyway**; or
   - in Terminal: `xattr -dr com.apple.quarantine "/Applications/Cora AI Meeting Notes.app"`
4. Grant **Microphone**, **Screen Recording** (needed to capture the other side of the call — no video is
   recorded) and **Accessibility** (live speaker names) when asked. See [SETUP.md](SETUP.md) if a prompt
   doesn't appear.

The first transcription downloads the speech model (`mlx-community/whisper-small-mlx` by default) and
the notes model (`mlx-community/Qwen3-4B-Instruct-2507-4bit`) from Hugging Face. After that, everything
runs offline.

## Where things live

- App: `/Applications/Cora AI Meeting Notes.app` (includes its own Python runtime)
- Your data: `~/Library/Application Support/Cora AI Meeting Notes` — recordings, transcripts, notes,
  the database, logs and `config.json`, all readable only by your account
- Models: `~/.cache/huggingface`

To uninstall, delete the app; delete the data folder too if you want your meetings gone.

## Building it yourself

```bash
make setup
make app      # -> dist/Cora-AI-Meeting-Notes-<version>-arm64.dmg
```
