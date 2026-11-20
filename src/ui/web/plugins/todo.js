// To-dos plugin page: action items from every processed meeting, with done state,
// and a Suggested tab listing pending Proposals across meetings (js/outbox.js).
// Loaded by js/plugin-host.js after the core scripts; shares their global scope.

registerView('todo', {onShow: renderTodoView});

let todoTab = 'open';

function todoRow(item){
  return `<div class="session-row todo-row${item.done ? ' todo-done' : ''}" style="grid-template-columns:auto 1fr auto">
    <input type="checkbox" data-track="tick_todo" data-todo-id="${esc(item.id)}"${item.done ? ' checked' : ''} aria-label="Done">
    <div><h4>${esc(item.text)}</h4>${item.owner || item.due ? `<p class="muted">${esc([item.owner && `Owner: ${item.owner}`, item.due && `Due: ${item.due}`].filter(Boolean).join(' · '))}</p>` : ''}</div>
    <button type="button" class="button secondary small" data-open-id="${esc(item.recording_id)}">${esc(item.recording_title)} · ${fmtDate(item.recorded_at)}</button>
  </div>`;
}

async function renderTodoView(root){
  root.innerHTML = '<p class="muted">Loading…</p>';
  const [{ items }, { count }] = await Promise.all([api('/api/plugins/todo/items'), api('/api/outbox/count')]);
  const tabs = `<div class="todo-tabs"><button type="button" class="button secondary small${todoTab === 'open' ? ' active' : ''}" data-todo-tab="open">To-dos</button>
    <button type="button" class="button secondary small${todoTab === 'suggested' ? ' active' : ''}" data-todo-tab="suggested">Suggested${count ? ` (${count})` : ''}</button></div>`;
  if(todoTab === 'suggested'){
    root.innerHTML = tabs + '<div id="todoSuggested"><p class="muted">Loading…</p></div>';
    await renderSuggestedTab($('#todoSuggested'));
    return;
  }
  if(!items.length){ root.innerHTML = tabs + '<p class="muted">No action items yet. They show up here once a meeting\'s notes are ready.</p>'; return; }
  const open = items.filter(i => !i.done), done = items.filter(i => i.done);
  root.innerHTML = tabs + `<div class="session-table">${open.map(todoRow).join('') || '<p class="muted">Everything is done.</p>'}</div>`
    + (done.length ? `<h3>Done</h3><div class="session-table">${done.map(todoRow).join('')}</div>` : '');
}

addEventListener('click', async event => {
  const tab = event.target.closest('[data-todo-tab]'); if(!tab) return;
  todoTab = tab.dataset.todoTab;
  await renderTodoView($('#view-todo')).catch(error => toast(error.message, true));
});

addEventListener('change', async event => {
  const box = event.target.closest('[data-todo-id]'); if(!box) return;
  try{
    await api('/api/plugins/todo/done', {method:'POST', body:JSON.stringify({id: box.dataset.todoId, done: box.checked})});
    await renderTodoView($('#view-todo'));
    refreshSuggestedCount();
  }catch(error){ box.checked = !box.checked; toast(error.message, true); }
});
