# Cora for the Sutra team: setup in 10 minutes

Team builds use **Gemini** for transcription and notes, so any Apple Silicon Mac works and nothing
large downloads to your laptop.

## Before you start

- A Mac with Apple Silicon (M1 or later) on macOS 14 Sonoma or newer.
  Check: Apple menu › About This Mac shows "Chip: Apple M…". Intel Macs are not supported.
- The team's Gemini API key, shared with you through the password manager (never Slack or email).

## 1. Install (2 min)

Open **Terminal** and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/mkdsrt10/cora-ai-meeting-notes/production/scripts/install.sh | bash -s -- --open
```

This installs **Cora AI Meeting Notes** into Applications and opens it. Nothing else to install.

## 2. Grant permissions (2 min)

Onboarding's **Permissions** step has a button for each. Click it, switch Cora on, come back, and
click **Check again**:

| Permission | Why |
|---|---|
| Microphone | Records your side of the call |
| Screen Recording | Captures the other side's audio (no video is recorded) |
| Accessibility | Detects meetings and who is speaking |

macOS may ask you to quit and reopen Cora after Screen Recording. These grants carry over to future updates.

## 3. Let Cora read participant names in your browser (1 min, once per browser)

Meet, Zoom web and Slack huddles in Chrome, Brave, Edge or Arc:

1. In the browser menu bar: **View › Developer › Allow JavaScript from Apple Events** (make sure it's ticked).
2. During your first meeting, macOS asks "Cora wants to control *Brave*". Click **OK**.

Skip this and recordings still work, but everyone shows up as "Participant".

## 4. Finish onboarding and add the Gemini key (2 min)

1. Enter your name (this is how Cora labels *you* in transcripts), meeting types and, optionally, key people.
2. On **Models & privacy**, leave **Processing mode** on **Cloud · cloud audio + notes** (ignore the
   local model lists). Click **Finish setup**.
3. A credentials window opens. Choose the **Google AI Studio** tab, paste the Gemini key, click
   **Test Connection**, then **Save Settings**. The key is stored in your macOS Keychain.

## 5. Record your first meeting

- Join a Meet, Zoom or Slack huddle. Cora detects it and starts recording (or click the menu-bar icon › **Start Recording**).
- When the call ends, Cora transcribes with Gemini and writes the summary, decisions and action items.
  Allow a few minutes for an hour-long call.
- Open the meeting from **Home**. If names are missing, the meeting page says why (usually step 3).

## Updating

Run the step 1 command again. Recordings, settings and permissions are kept.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Gemini key was rejected" | Re-copy the key from the password manager; ask Mayank if it was rotated |
| Everyone is "Participant" | Step 3 for the browser you used, then rejoin the call |
| Nothing recorded from the other side | Screen Recording is off: System Settings › Privacy & Security › Screen Recording |
| Meeting not auto-detected | Accessibility is off, or start manually from the menu-bar icon |
| Anything else | Send Mayank the file at `~/Library/Application Support/Cora AI Meeting Notes/logs` for that meeting (it never leaves your Mac otherwise) |
