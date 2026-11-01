// Startup: onboarding check, then initial loads.
// Classic script sharing global scope with the other files in index.html (load order matters).

(async function init(){
  const plugins = loadPlugins().catch(error => console.error('Plugins failed to load:', error));
  try{
    const status = await api('/api/onboarding/status');
    if(!status.complete){ await openOnboarding(); return; }
  }catch(error){ console.error('Onboarding status check failed:', error); }
  setupTitleEditor();
  setupTranscriptSearch();
  await plugins;
  load().catch(error=>toast(error.message,true));
  loadFolders();
  loadLocalStats();
  checkModelsOnStartup();
})();
