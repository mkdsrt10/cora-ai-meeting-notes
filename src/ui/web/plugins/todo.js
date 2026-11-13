// To-dos plugin page: action items from every processed meeting, with done state.
// Loaded by js/plugin-host.js after the core scripts; shares their global scope.

registerView('todo', {onShow: renderTodoView});

function todoRow(item){
  return `<div class="session-row todo-row${item.done ? ' todo-done' : ''}" style="grid-template-columns:auto 1fr auto">
    <input type="checkbox" data-track="tick_todo" data-todo-recording="${esc(item.recording_id)}" data-todo-index="${item.index}"${item.done ? ' checked' : ''} aria-label="Done">
    <div><h4>${esc(item.text)}</h4></div>
    <button type="button" class="button secondary small" data-open-id="${esc(item.recording_id)}">${esc(item.recording_title)} · ${fmtDate(item.recorded_at)}</button>
  </div>`;
}

async function renderTodoView(root){
  root.innerHTML = '<p class="muted">Loading…</p>';
  const { items } = await api('/api/plugins/todo/items');
  if(!items.length){ root.innerHTML = '<p class="muted">No action items yet. They show up here once a meeting\'s notes are ready.</p>'; return; }
  const open = items.filter(i => !i.done), done = items.filter(i => i.done);
  root.innerHTML = `<div class="session-table">${open.map(todoRow).join('') || '<p class="muted">Everything is done.</p>'}</div>`
    + (done.length ? `<h3>Done</h3><div class="session-table">${done.map(todoRow).join('')}</div>` : '');
}

addEventListener('change', async event => {
  const box = event.target.closest('[data-todo-index]'); if(!box) return;
  try{
    await api('/api/plugins/todo/done', {method:'POST', body:JSON.stringify({recording_id: box.dataset.todoRecording, index: Number(box.dataset.todoIndex), done: box.checked})});
    await renderTodoView($('#view-todo'));
  }catch(error){ box.checked = !box.checked; toast(error.message, true); }
});
