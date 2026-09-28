// Startup: onboarding check, then initial loads.
// Classic script sharing global scope with the other files in index.html (load order matters).

(async function init(){
  try{
    const status = await api('/api/onboarding/status');
    if(!status.complete){ await openOnboarding(); return; }
  }catch(error){ console.error('Onboarding status check failed:', error); }
  setupTitleEditor();
  setupTranscriptSearch();
  load().catch(error=>toast(error.message,true));
  loadFolders();
  loadLocalStats();
  checkModelsOnStartup();
})();
