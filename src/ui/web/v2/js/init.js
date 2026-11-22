// v2 startup: theme, sidebar state, data, Recording session state, then Home.
// Classic script sharing global scope with the other v2 files (load last).

(async function init(){
  restoreSidebar();
  renderSidebar();
  await loadTheme();
  watchRecordingState();
  await refreshAll();
  await go('home', {}, { push: false });
})();
