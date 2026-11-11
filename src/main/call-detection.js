// Call detection as Electron main uses it (see GLOSSARY.md, Call): one
// detector, two signals. The mic turning on asks the detector once (signal
// 'mic'); the watcher polls as a backstop (signal 'poll'). Each Call is
// offered once: a call_detected Usage event, then a notification whose click
// or action starts a Recording labelled with the Call. Main supplies the
// adapters; this module holds no Electron or HTTP of its own.

// ['A'] -> 'A'; ['A', 'B'] -> 'A and B'; ['A', 'B', 'C'] -> 'A, B and C'.
function joinNames(names) {
  const unique = [...new Set(names)];
  if (unique.length <= 1) return unique.join('');
  return `${unique.slice(0, -1).join(', ')} and ${unique[unique.length - 1]}`;
}

function createCallDetection({ detector, notify, startRecording, stopRecording, track, isCapturing }) {
  let notified = false;

  // A Meet or Slack tab the page could not be asked about: say which browser
  // setting lets Cora see inside. The watcher fires onUnanswered at most once
  // per start(), so it alone decides how often this shows.
  function hint(browsers) {
    if (!browsers || !browsers.length) return;
    notify({
      title: 'Cora',
      body: `Cora can't see inside ${joinNames(browsers)}. Turn on View > Developer > Allow JavaScript from Apple Events`
        + ' (Safari: Develop menu) so huddles and Meet are detected.',
    });
  }

  function detected(call, signal) {
    if (notified || isCapturing()) return;
    notified = true;
    track('call_detected', { app: call.label, signal, confirmed: Boolean(call.confirmed) });
    const notification = notify({
      title: 'Cora',
      body: `${call.label} call detected. Start recording?`,
      actions: [{ type: 'button', text: 'Start Recording' }],
      closeButtonText: 'Dismiss',
    }, { show: false });
    notification.on('click', () => startRecording(call.label));
    notification.on('action', () => startRecording(call.label));
    notification.show();
  }

  // The mic turning on is the fast, OS-level signal; the detector still has
  // to find a known app, tab or huddle, so dictation or Voice Memos never
  // prompt.
  async function onMicOn() {
    if (notified || isCapturing()) return;
    const call = await detector.checkOnce();
    if (call) detected(call, 'mic');
  }

  // The Call ended (the app released the mic, or its tab or window went
  // away): the next one may be offered, and a capturing Recording stops.
  function ended(reason) {
    notified = false;
    if (isCapturing()) stopRecording(reason);
  }

  const onMicOff = () => ended('mic-off');

  function start() {
    return detector.startWatcher({
      onDetected: (call) => detected(call, 'poll'),
      onEnded: () => ended('meeting-ended'),
      onUnanswered: hint,
    });
  }

  return { start, onMicOn, onMicOff };
}

module.exports = { createCallDetection };
