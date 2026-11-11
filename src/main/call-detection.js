// Call detection as Electron main uses it (see GLOSSARY.md, Call): one
// detector, two signals. The mic turning on asks the detector once (signal
// 'mic'); the watcher polls as a backstop (signal 'poll'). Each Call is
// offered once: a call_detected Usage event, then a notification whose click
// or action starts a Recording labelled with the Call. Main supplies the
// adapters; this module holds no Electron or HTTP of its own.

const { initialPromptState, promptStep } = require('./call-prompt-state');
const { createFollowup } = require('./call-followup');

// prompt (optional): { show(call), hide() } for the Call prompt panel; show may
// throw, which falls back to the macOS banner. onPromptClosed(action, call):
// action is 'start' | 'dismiss' | 'expired' (Call ended or a Recording started
// elsewhere). onPrompted({call, signal, secondsFromMicOn}) fires when a Call
// is offered (signal 'mic' | 'poll' | 'followup'; secondsFromMicOn is null when
// no mic-on is known): the hook for Usage events. clock = { now, setTimeout,
// clearTimeout } drives the green-room follow-up (injectable for tests). Main feeds the panel's buttons into promptAction(action) and
// recording starts into onRecordingStarted().
function createCallDetection({ detector, notify, startRecording, stopRecording, track, isCapturing, prompt = null, onPromptClosed = () => {}, onPrompted = () => {}, onFallback = () => {}, clock = { now: Date.now, setTimeout, clearTimeout } }) {
  let micOnAt = null;
  const followup = createFollowup({
    check: async (opts) => checked(await detector.check(opts)),
    onFound: (call) => detected(call, 'followup'),
    timers: clock,
  });
  let promptState = initialPromptState();
  let currentCall = null;
  // The capturing Recording was started from a Call notification (click or
  // action), so the poll seeing that Call end may stop it.
  let startedFromCall = false;

  // Detection ran with less than it needs: desktop apps counted from the
  // process alone (ax_untrusted) or a browser would not answer (js_events_off).
  // Reported once per reason per run; never a banner (main shows the hint in
  // the permissions area).
  const reported = new Set();
  function fallback(reason, apps) {
    if (!reason || reported.has(reason)) return;
    reported.add(reason);
    track('detect_fallback', { reason });
    onFallback({ reason, apps: [...new Set(apps || [])] });
  }

  // A check's answer may carry either fallback.
  function checked(result) {
    if (!result) return result;
    if (result.fallback) fallback(result.fallback.reason, result.fallback.apps);
    if (result.unanswered && result.unanswered.length) fallback('js_events_off', result.unanswered);
    return result;
  }

  // Feeds the reducer and performs its effects. `call` is the Call the prompt
  // is about; the banner path is the old notification, unchanged.
  function step(event) {
    const r = promptStep(promptState, event);
    promptState = r.state;
    for (const effect of r.effects) {
      if (effect.type === 'show') showPrompt();
      else if (effect.type === 'banner') showBanner();
      else if (effect.type === 'hide') { try { prompt.hide(); } catch (err) { console.warn('[call-prompt] hide failed:', err && err.message); } }
      else if (effect.type === 'closed') {
        // Dismiss or Start ends the follow-up; so does a Recording starting.
        followup.stop();
        track('call_prompt_action', { action: effect.action });
        onPromptClosed(effect.action, currentCall);
      }
    }
  }

  const startFromCall = () => {
    startedFromCall = true;
    startRecording(currentCall.label);
  };

  // Always built (not shown) so the notifications-table entry is written
  // whichever surface the user sees.
  let notification = null;

  function showPrompt() {
    notification = notify({
      title: 'Cora',
      body: `${currentCall.label} call detected. Start recording?`,
      actions: [{ type: 'button', text: 'Start Recording' }],
      closeButtonText: 'Dismiss',
    }, { show: false });
    try {
      if (!prompt) throw new Error('no panel');
      prompt.show(currentCall);
    } catch (err) {
      if (prompt) console.warn('[call-prompt] panel failed, using banner:', err && err.message);
      step({ type: 'show-failed' });
    }
  }

  function showBanner() {
    notification.on('click', startFromCall);
    notification.on('action', startFromCall);
    notification.show();
  }

  function detected(call, signal) {
    followup.stop(); // a live Call found by any signal ends the follow-up
    if (promptState.phase !== 'idle' || isCapturing()) return;
    currentCall = call;
    const secondsFromMicOn = micOnAt === null ? null : Math.round((clock.now() - micOnAt) / 1000);
    track('call_detected', { app: call.label, trigger: signal, confirmed: Boolean(call.confirmed), seconds_to_prompt: secondsFromMicOn });
    step({ type: 'detected', capturing: false });
    onPrompted({ call, signal, secondsFromMicOn });
  }

  // The panel's buttons ('start' | 'dismiss').
  function promptAction(action) {
    if (promptState.phase !== 'visible') return;
    if (action === 'start') {
      step({ type: 'start' });
      startFromCall();
    } else if (action === 'dismiss') {
      step({ type: 'dismiss' });
    }
  }

  const onRecordingStarted = () => { followup.stop(); step({ type: 'recording-started' }); };

  // The mic turning on is the fast, OS-level signal; the detector still has
  // to find a known app, tab or huddle, so dictation or Voice Memos never
  // prompt.
  async function onMicOn() {
    if (promptState.phase !== 'idle' || isCapturing()) return;
    micOnAt = clock.now();
    const { call } = checked(await detector.check());
    if (call) detected(call, 'mic');
    else if (promptState.phase === 'idle' && !isCapturing()) followup.start(micOnAt);
  }

  // The Call ended: the next one may be offered. The app releasing the mic
  // stops any capturing Recording, as before; the poll no longer seeing the
  // tab or window stops only a Recording that Cora's prompt started, so a
  // Recording started from the tray or floater outlives a Call it overlaps.
  function ended(reason) {
    step({ type: 'call-ended' });
    const fromCall = startedFromCall;
    startedFromCall = false;
    if (!isCapturing()) return;
    if (reason === 'mic-off' || fromCall) stopRecording(reason);
  }

  const onMicOff = () => { followup.stop(); micOnAt = null; ended('mic-off'); };

  function start() {
    return detector.startWatcher({
      onDetected: (call) => detected(call, 'poll'),
      onEnded: () => ended('meeting-ended'),
      onUnanswered: (browsers) => fallback('js_events_off', browsers),
      onFallback: (f) => fallback(f.reason, f.apps),
    });
  }

  return { start, onMicOn, onMicOff, promptAction, onRecordingStarted };
}

module.exports = { createCallDetection };
