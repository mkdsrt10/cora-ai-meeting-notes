# Installing Cora AI Meeting Notes

## Requirements

- A Mac with Apple Silicon (M1 or later), macOS 14 Sonoma or newer
- ~2 GB free for the app, plus ~1–3 GB for models downloaded on first use

Nothing else: the app bundles its own Python runtime and ffmpeg.

## Quick install (recommended)

Paste this in Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/mkdsrt10/cora-ai-meeting-notes/production/scripts/install.sh | bash
```

It downloads the latest release over HTTPS, checks it against the release's published SHA-256, copies
the app into `/Applications` (or `~/Applications` if that isn't writable) and finishes. No `sudo`, and it
never runs anything from the download. The script is short, so [read it first](../scripts/install.sh) if
you like. Options: `--version v0.2.2`, `--dir PATH`, `--open`, `--dry-run`. Running it again updates the
app in place; your recordings and settings are kept.

> ### Why isn't Cora "verified" by Apple?
>
> Cora is **open source and not notarized**. Apple only notarizes apps from paid Developer Program
> members ($99/year), and this project doesn't have one yet. Without it, macOS shows *"Apple could not
> verify Cora is free of malware"* when you open a DMG you downloaded in a browser.
>
> That warning means "Apple hasn't checked this", not "this is malware". You don't have to take our word
> for it: the code is in this repository, every release has a published checksum, and you can
> [build the same app yourself](#building-it-yourself). The quick-install script above avoids the
> warning because files downloaded with `curl` aren't quarantined by macOS.
>
> Releases are signed with one persistent (self-signed) certificate, so Microphone / Screen Recording /
> Accessibility grants survive updates. We'll notarize once the project can fund it.

## Participant names in browser meetings

Google Meet, Zoom (web client) and Slack huddles running in Chrome, Brave, Edge or Arc need two
one-time switches so Cora can read who is in the call:

1. In the browser: **View › Developer › Allow JavaScript from Apple Events**.
2. When macOS asks whether Cora may control the browser, click **Allow** (or later: System Settings ›
   Privacy & Security › Automation › Cora AI Meeting Notes).

Without them, recordings still work and speaker turns are kept, but names show as "Participant". A
recording's detail page tells you if this is what went wrong. Safari and the native Zoom/Teams/Slack
apps use Accessibility only.

## Team builds

`./scripts/build-app.sh --team` builds the same app with Gemini as the default for transcription and
notes on new installs (`"default_processing_mode": "cloud"`), so nothing heavy runs or downloads
locally; each user pastes the Gemini key on first launch. Existing installs keep their `config.json`. Release signing needs a one-time `./scripts/signing-setup.sh` on the build machine;
back up `~/.cora-signing` (losing it means everyone re-grants permissions once).

## Install the DMG by hand

1. Download `Cora-AI-Meeting-Notes-<version>-arm64.dmg` from the
   [latest release](https://github.com/mkdsrt10/cora-ai-meeting-notes/releases/latest).
   Optionally verify it: `shasum -a 256 -c Cora-AI-Meeting-Notes-<version>-arm64.dmg.sha256`.
2. Open the DMG and drag **Cora AI Meeting Notes** into **Applications**.
3. **First launch.** Because of the above, macOS refuses to open it the normal way. Either:
   - open **System Settings → Privacy & Security**, scroll to the message about Cora being blocked,
     and click **Open Anyway** (on recent macOS this only appears after you've tried to open the app once); or
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
