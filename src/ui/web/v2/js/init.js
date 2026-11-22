// v2 startup: theme, sidebar state, the core nav, then Home.
// Classic script sharing global scope with the other v2 files (load last).

function renderCoreNav(){
  $('#navMain').innerHTML = [
    ['home', '⌂', 'Home'],
  ].map(([id, icon, label]) => `<button class="nav" type="button" data-go="${id}"><span class="ico" aria-hidden="true">${icon}</span><span class="lbl">${label}</span></button>`).join('');
}

(async function init(){
  restoreSidebar();
  renderCoreNav();
  await loadTheme();
  await go('home', {}, { push: false });
})();
