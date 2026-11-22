// v2 startup: theme, sidebar state, data, Recording session state, then Home.
// Classic script sharing global scope with the other v2 files (load last).

// A new install sets up in the classic look (onboarding has not moved yet);
// v2 says so instead of showing an empty window.
function setupNotice(host){
  host.innerHTML = `<div class="page"><div class="empty"><strong>Finish setting up Cora first.</strong>
    Setup (your name, permissions and models) runs in the classic look for now. Come back with Settings › Try the new look.
    <p><button class="btn pri" type="button" data-switch-shell="classic">Open setup</button></p></div></div>`;
}

(async function init(){
  restoreSidebar();
  renderSidebar();
  await loadTheme();
  try{
    const status = await api('/api/onboarding/status');
    if(status.complete === false){ setupNotice($('#page')); return; }
  }catch(error){ console.error('Onboarding status check failed:', error); }
  watchRecordingState();
  await refreshAll();
  // A deep link (#page=meeting&id=…) opens that page; Home otherwise.
  const link = new URLSearchParams(String(location.hash || '').replace(/^#/, ''));
  const { page = 'home', ...params } = Object.fromEntries(link);
  await go(shell.pages[page] ? page : 'home', params, { push: false });
  maybeShowTour();  // js/tour.js: once per Install
})();
