// Call prompt panel: label text plus two buttons. All decisions are in main
// (src/main/call-prompt-state.js); this only reports which button was pressed.
window.electronAPI.onCallPromptCall((label) => {
  document.getElementById('text').textContent = `${label} call detected`;
});
// "Live: Cloud" when starting would stream audio to the cloud live engine.
window.electronAPI.onCallPromptLive?.((cloud) => {
  document.getElementById('liveCloud').hidden = !cloud;
});
document.getElementById('btnStart').addEventListener('click', () => window.electronAPI.callPromptAction('start'));
document.getElementById('btnDismiss').addEventListener('click', () => window.electronAPI.callPromptAction('dismiss'));
