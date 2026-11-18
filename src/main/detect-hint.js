// The hint for a detection fallback (Accessibility untrusted, or a browser
// refusing "Allow JavaScript from Apple Events"): shown in the permissions
// area, once per Install (a settings flag), never as a notification. main
// supplies the flag store and `send` (to the renderer); the hint is also
// kept for pending() so a window opened later can ask for it.

// ['A'] -> 'A'; ['A', 'B'] -> 'A and B'; ['A', 'B', 'C'] -> 'A, B and C'.
function joinNames(names) {
  const unique = [...new Set(names)];
  if (unique.length <= 1) return unique.join('');
  return `${unique.slice(0, -1).join(', ')} and ${unique[unique.length - 1]}`;
}

function hintText(reason, apps) {
  if (reason === 'ax_untrusted') {
    return 'Cora needs Accessibility access to tell whether you are in a call in Zoom or Slack. Until you grant it, Cora only prompts when your microphone turns on.';
  }
  const where = apps && apps.length ? `inside ${joinNames(apps)}` : 'inside your browser';
  return `Cora can't see ${where}. Turn on View > Developer > Allow JavaScript from Apple Events`
    + ' (Safari: Develop menu) so huddles and Meet are detected.';
}

function createDetectHint({ getFlag, setFlag, send }) {
  const hints = new Map();   // reason -> hint offered this run (kept for pending())
  const stored = new Set();  // reasons whose flag is persisted (a window got the hint)
  const busy = new Set();

  async function markShown(reason) {
    if (stored.has(reason)) return;
    try {
      await setFlag(reason);
      stored.add(reason);
    } catch (err) {
      console.warn('[detect-hint] flag not stored:', err && err.message);
    }
  }

  async function onFallback({ reason, apps }) {
    if (stored.has(reason) || busy.has(reason)) return;
    busy.add(reason);
    try {
      if (await getFlag(reason)) { stored.add(reason); return; }
      const hint = { reason, text: hintText(reason, apps) };
      hints.set(reason, hint);
      if (send(hint) === true) await markShown(reason);
    } catch (err) {
      console.warn('[detect-hint] not shown:', err && err.message);
    } finally {
      busy.delete(reason);
    }
  }

  // Hints to render. `delivered: true` means a live window is asking (and so
  // is getting them): that is the moment their flags are stored.
  function pending({ delivered = false } = {}) {
    const list = [...hints.values()];
    if (delivered) for (const h of list) markShown(h.reason);
    return list;
  }

  return { onFallback, pending };
}

module.exports = { createDetectHint };
