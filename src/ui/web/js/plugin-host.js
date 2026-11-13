// Plugin host: turns GET /api/plugins into nav entries, page sections and
// stage labels, then loads each enabled plugin's page script
// (src/ui/web/plugins/<id>.js), which calls registerView('<id>', {onShow}).
// Classic script sharing global scope with the other files in index.html (load order matters).

function renderStageFilter(){
  const select = $('#stageFilter'); if(!select) return;
  const current = select.value;
  select.innerHTML = '<option value="">All stages</option>' + Object.entries(stageLabels)
    .map(([id, label]) => `<option value="${esc(id)}">${esc(label)}</option>`).join('');
  select.value = stageLabels[current] ? current : '';
}

function loadPluginScript(id){
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `/plugins/${encodeURIComponent(id)}.js`;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`Plugin page "${id}" failed to load`));
    document.body.appendChild(script);
  });
}

async function loadPlugins(){
  const { plugins, stages } = await api('/api/plugins');
  stageLabels = stages || {};
  renderStageFilter();
  const nav = $('.sidebar nav'), main = $('main');
  for(const plugin of plugins){
    const view = plugin.view;
    if(!view || views[view.id]) continue;
    registerView(view.id, {title: view.title, subtitle: view.subtitle});
    const section = document.createElement('section');
    section.className = 'view plugin-view';
    section.id = `view-${view.id}`;
    main.appendChild(section);
    try{
      await loadPluginScript(plugin.id);
    }catch(error){
      console.error(error);
      section.remove();
      delete views[view.id];
      continue;
    }
    const button = document.createElement('button');
    button.className = 'nav-item';
    button.dataset.view = view.id;
    button.innerHTML = `<span data-icon="${esc(view.icon)}" data-size="16"></span>${esc(view.title)}`;
    nav.appendChild(button);
    window.renderIcons?.(button);
  }
}
