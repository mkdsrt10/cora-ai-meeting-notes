// Detection-fallback hint in the permissions area (onboarding permissions step
// and Settings > Notifications & logs). Main decides when (once per Install,
// src/main/detect-hint.js) and pushes it; this only renders it.
// Classic script; wrapped so it adds nothing to the shared global scope.

(function detectHint(){
  const bridge = window.electronAPI;
  if(!bridge || !bridge.onDetectHint) return;  // dashboard opened outside the app

  function render(hint){
    document.querySelectorAll('[data-detect-hint]').forEach(el => {
      el.textContent = hint ? hint.text : '';
      el.hidden = !hint;
    });
  }

  bridge.onDetectHint(render);
  bridge.getDetectHint().then(render).catch(() => {});
})();
