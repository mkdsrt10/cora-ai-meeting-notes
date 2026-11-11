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

During the beta Cora sends usage data and some full recordings to the Cora team to check accuracy:
see [BETA_POLICY.md](BETA_POLICY.md) for what is sent and how to turn it off.

## 2. Grant permissions (2 min)

Onboarding's **Permissions** step has a button for each. Click it, switch Cora on, come back, and
click **Check again**:

| Permission | Why |
|---|---|
| Microphone | Records your side of the call |
| Screen Recording | Captures the other side's audio (no video is recorded) |
| Accessibility | Detects meetings and who is speaking |

macOS may ask you to quit and reopen Cora after Screen Recording. These grants carry over to future updates.

## 3. Let Cora look inside your browser tabs (1 min, once per browser)

Cora uses this to read participant names (Meet, Zoom web and Slack huddles in Chrome, Brave, Edge
or Arc) and to tell when you are really in a Meet or a Slack huddle (Chrome, Brave, Edge or Safari):

1. In the browser menu bar, tick **Allow JavaScript from Apple Events**:
   - Chrome, Brave, Edge (and Arc): **View › Developer › Allow JavaScript from Apple Events**.
   - Safari: **Develop › Allow JavaScript from Apple Events** (turn on the Develop menu first in
     Safari › Settings › Advanced).
2. During your first meeting, macOS asks "Cora wants to control *Brave*". Click **OK**.

Skip this and recordings still work, but everyone shows up as "Participant", huddles in a browser
are not detected, and Meet may prompt while you are still in the green room. Cora reminds you once
per app start with a notification: "Cora can't see inside *Brave*. Turn on View › Developer ›
Allow JavaScript from Apple Events…". That notification means this step is missing for that browser.

## 4. Finish onboarding and add the Gemini key (2 min)

1. Enter your name (this is how Cora labels *you* in transcripts), meeting types and, optionally, key people.
2. On **Models & privacy**, leave **Processing mode** on **Cloud · cloud audio + notes** (ignore the
   local model lists). Click **Finish setup**.
3. A credentials window opens. Choose the **Google AI Studio** tab, paste the Gemini key, click
   **Test Connection**, then **Save Settings**. The key is stored in your macOS Keychain.

## 5. Record your first meeting

- Join a Google Meet, Zoom (app or web client) or Slack huddle (app or browser, expanded or
  collapsed to the mini-bar). Within a few seconds of your mic turning on, Cora shows
  "*Google Meet* call detected. Start recording?". Click **Start Recording**. Nothing records until
  you click; you can also start from the menu-bar icon › **Start Recording** at any time. For Meet,
  the prompt comes after you click Join, not in the green room. When you leave the call, the
  recording stops.
- When the call ends, Cora transcribes with Gemini and writes the summary, decisions and action items.
  Allow a few minutes for an hour-long call.
- Open the meeting from **Home**. If names are missing, the meeting page says why (usually step 3).

## Updating

Cora checks for a new release when it starts and every 6 hours. When one is out, a banner at the
top of the window says **Cora X.Y.Z is available**:

- **Update** downloads the new version, checks it against its published checksum, puts it in
  place and restarts Cora. If any step fails the banner shows why and the installed Cora is left
  as it was.
- **Later** hides the banner for 24 hours. If the Cora team marks your version as no longer
  supported, there is no Later.
- While a meeting is being recorded, or a recording is still processing, **Update** is greyed out
  and the banner says why; it comes back when Cora is done. If a recording starts while the update
  is installing, Cora waits until it has ended and been processed before restarting.

Recordings, settings and permissions are kept. Under enterprise lockdown Cora does not check for
updates. If the banner never appears or an update fails, run the step 1 command again; it does the
same install by hand.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Gemini key was rejected" | Re-copy the key from the password manager; ask Mayank if it was rotated |
| Everyone is "Participant" | Step 3 for the browser you used, then rejoin the call |
| Nothing recorded from the other side | Screen Recording is off: System Settings › Privacy & Security › Screen Recording |
| No "call detected" prompt | Check Accessibility is on (step 2) and, for a Meet or huddle in a browser, step 3 for that browser. Detection covers Chrome, Brave, Edge and Safari, not Arc. You can always start from the menu-bar icon |
| "Cora can't see inside *browser*" notification | Step 3 is off for that browser: tick Allow JavaScript from Apple Events (Chrome/Brave/Edge: View › Developer; Safari: Develop). Shown once per app start |
| Meet prompt appears before you join | Same cause: without step 3 Cora only sees the Meet address, not whether you joined |
| Anything else | Send Mayank the file at `~/Library/Application Support/Cora AI Meeting Notes/logs` for that meeting (it never leaves your Mac otherwise) |
