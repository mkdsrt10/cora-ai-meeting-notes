// Update banner at the top of the main window ("Cora X.Y.Z is available").
// Main owns every decision (src/updater.js) and pushes its state through the
// preload bridge; this only renders it and forwards Update / Later clicks.
// Classic script; wrapped so it adds nothing to the shared global scope.

(function updateBanner(){
  const bridge = window.electronAPI;
  if(!bridge || !bridge.onUpdateState) return;  // dashboard opened outside the app

  let clickError = '';

  function render(s){
    const banner = $('#updateBanner');
    if(!banner || !s) return;
    const snoozed = Boolean(s.snoozedUntil) && !s.forced;
    banner.hidden = !s.available || snoozed;
    if(banner.hidden) return;
    $('#updateBannerText').textContent = `Cora ${s.latest} is available`
      + (s.forced ? '. This version is no longer supported; please update.' : '');
    const now = $('#updateNowBtn');
    now.disabled = Boolean(s.busyReason) || Boolean(s.installing);
    now.title = s.busyReason || '';
    const later = $('#updateLaterBtn');
    later.hidden = Boolean(s.forced);
    later.disabled = Boolean(s.installing);
    $('#updateBannerReason').textContent = s.installing
      ? 'Updating… Cora will restart when it is done.'
      : (s.busyReason || '');
    const error = s.error || clickError;
    $('#updateBannerError').textContent = error ? `Update failed: ${error}` : '';
  }

  let last = null;
  const show = s => { last = s; clickError = ''; render(s); };

  bridge.onUpdateState(show);
  if(bridge.getUpdateState) bridge.getUpdateState().then(s => { if(!last) show(s); }).catch(() => {});

  const now = $('#updateNowBtn');
  if(now) now.addEventListener('click', async () => {
    const result = await bridge.updateNow();
    if(result && result.ok === false && result.error){ clickError = result.error; render(last); }
  });
  const later = $('#updateLaterBtn');
  if(later) later.addEventListener('click', () => bridge.updateLater());
})();
