// The one place that decides "is a Call live in this tab?" for Google Meet,
// Slack and Zoom in a browser. Two consumers embed this exact text:
//   - src/meeting-detector.js sends PAGE_EXPRESSION to each Meet/Slack tab
//     through AppleScript and reads the JSON answer;
//   - capture/SpeakerWatcher.swift carries a generated copy (the region between
//     the "live-call-snippet" markers, written by scripts/gen-live-call-snippet.js
//     and refreshed by `make build-native`) and uses liveCall() for its own
//     active decision.
// test/js/live-call-snippet-drift.test.js fails when the Swift copy differs.
//
// Both consumers flatten the text onto ONE line before the browser sees it, so
// the snippet below must never contain a `//` line comment (block comments only).

const LIVE_CALL_JS = `function liveCall() {
  /* Answers {live, label} for the current tab. Slack hosts get the huddle
     rules; anything else (Meet) gets the leave-call rules. */
  const host = typeof location !== 'undefined' && location.hostname ? String(location.hostname).toLowerCase() : '';
  const text = el => String((el && (el.getAttribute('aria-label') || el.innerText)) || '').trim();
  const buttons = root => Array.from(root.querySelectorAll('button, [role="button"]'));
  if (host === 'slack.com' || host.endsWith('.slack.com')) {
    /* Expanded huddle: participant tiles. Older layouts: a huddle dialog
       holding a Leave/End huddle button, or such a button anywhere. Collapsed
       to the bottom mini-bar: a non-empty huddle_details_title. The content
       container alone does not count as live; the speaker watcher uses it
       only to scope where names are read. */
    const isLeave = b => /^(?:leave|end)(?: the)? huddle/i.test(text(b));
    const isHuddleRoot = r => /huddle/i.test(r.getAttribute('aria-label') || r.getAttribute('data-qa') || r.getAttribute('data-testid') || '');
    const mini = document.querySelector('[data-qa="huddle_details_title"]');
    const live = !!document.querySelector('[data-qa^="huddle_peer_tile_userId_"]')
      || Array.from(document.querySelectorAll('[role="dialog"], [data-qa*="huddle"], [data-testid*="huddle"]')).some(r => isHuddleRoot(r) && buttons(r).some(isLeave))
      || buttons(document).some(isLeave)
      || String((mini && mini.innerText) || '').trim() !== '';
    return { live, label: 'Slack Huddle' };
  }
  if (host === 'zoom.us' || host.endsWith('.zoom.us')) {
    /* Zoom web client: joined means the footer Leave/End control exists; the
       pre-join screen and the /j/ launch page have only Join/Launch buttons. */
    const live = !!document.querySelector('button.footer__leave-btn')
      || buttons(document).some(b => /^(?:leave|end)(?: the)?(?: meeting)?$/i.test(text(b)));
    return { live, label: 'Zoom' };
  }
  /* Meet: joined means a Leave call control exists; the green room has none.
     Only "Leave call" counts: other controls say Leave too (Leave feedback). */
  const live = !!document.querySelector('button[aria-label^="Leave call"], [data-tooltip^="Leave call"]')
    || buttons(document).some(b => /^(?:leave|end)(?: the)? call/i.test(text(b)));
  return { live, label: 'Google Meet' };
}`;

// What the detector runs in a tab: the answer as a JSON string, which both
// Chrome's "execute javascript" and Safari's "do JavaScript" return as text.
const PAGE_EXPRESSION = `(() => { ${LIVE_CALL_JS} return JSON.stringify(liveCall()); })()`;

module.exports = { LIVE_CALL_JS, PAGE_EXPRESSION };
