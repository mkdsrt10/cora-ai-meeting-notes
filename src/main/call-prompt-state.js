// The Call prompt's show/hide/dismiss decisions (see GLOSSARY.md, Call prompt)
// as a pure reducer: promptStep(state, event) -> { state, effects }. No window,
// no timers; src/main/call-detection.js turns effects into Electron calls.
//
// phase: 'idle'      no prompt for the current Call
//        'visible'   panel is up (show was asked, not yet reported failed)
//        'banner'    the panel could not show; the macOS banner was used
//        'held'      this Call was acted on (Start or Dismiss) or its panel was
//                    closed by a Recording; held until the Call ends
//
// events: detected{capturing}, show-failed, start, dismiss, recording-started,
//         call-ended (mic off, or the watcher's Call-ended callback)
// effects: {type:'show'} | {type:'banner'} | {type:'hide'} |
//          {type:'closed', action:'start'|'dismiss'|'expired'}

function initialPromptState() {
  return { phase: 'idle' };
}

const same = (state) => ({ state, effects: [] });
const to = (phase, effects) => ({ state: { phase }, effects });

function promptStep(state, event) {
  const { phase } = state;
  switch (event.type) {
    case 'detected':
      if (phase !== 'idle' || event.capturing) return same(state);
      return to('visible', [{ type: 'show' }]);
    case 'show-failed':
      return phase === 'visible' ? to('banner', [{ type: 'banner' }]) : same(state);
    case 'start':
      return phase === 'visible'
        ? to('held', [{ type: 'hide' }, { type: 'closed', action: 'start' }])
        : same(state);
    case 'dismiss':
      return phase === 'visible'
        ? to('held', [{ type: 'hide' }, { type: 'closed', action: 'dismiss' }])
        : same(state);
    case 'recording-started':
      return phase === 'visible'
        ? to('held', [{ type: 'hide' }, { type: 'closed', action: 'expired' }])
        : same(state);
    case 'call-ended':
      return phase === 'visible'
        ? to('idle', [{ type: 'hide' }, { type: 'closed', action: 'expired' }])
        : to('idle', []);
    default:
      return same(state);
  }
}

module.exports = { initialPromptState, promptStep };
