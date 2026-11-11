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
  let current = null;
  let busy = false;

  async function onFallback({ reason, apps }) {
    if (current || busy) return;
    busy = true;
    try {
      if (await getFlag()) return;
      await setFlag();
      current = { reason, text: hintText(reason, apps) };
      send(current);
    } catch (err) {
      console.warn('[detect-hint] not shown:', err && err.message);
    } finally {
      busy = false;
    }
  }

  return { onFallback, pending: () => current };
}

module.exports = { createDetectHint };
