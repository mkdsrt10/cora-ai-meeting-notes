// What's new and the satisfaction survey (python/pulse.py decides what is due).
// One small card, bottom right, in both looks (index.html and v2/index.html):
// first "What's new in Cora X" after an update, with "Was this helpful?";
// otherwise, when due, "How satisfied are you with Cora?" 1-5 and a comment.
// Never while a Recording is running. Classic script; needs lib.js (api, esc)
// and usage.js (trackAction); adds only `showPulse` to the global scope.

const PULSE_DELAY_MS = 4000;     // let the window settle first

function pulseStyles(){
  if(document.getElementById('pulseStyles')) return;
  const style = document.createElement('style');
  style.id = 'pulseStyles';
  style.textContent = `
  .pulse-card{position:fixed;right:20px;bottom:20px;z-index:60;width:360px;max-width:calc(100vw - 32px);
    background:var(--bg,#fff);color:var(--ink,#1c1c1e);border:1px solid var(--line2,#e3e3e8);border-radius:12px;
    box-shadow:0 10px 30px rgba(0,0,0,.18);padding:16px 16px 14px;font-size:13px;line-height:1.45}
  .pulse-card h3{margin:0 24px 8px 0;font-size:14px}
  .pulse-card ul{margin:0 0 10px;padding-left:18px}.pulse-card li{margin:0 0 6px}
  .pulse-card .pulse-x{position:absolute;top:8px;right:8px;border:0;background:none;font-size:16px;cursor:pointer;color:inherit;opacity:.6}
  .pulse-card .pulse-row{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:8px}
  .pulse-card button.pulse-b{border:1px solid var(--line2,#e3e3e8);background:var(--bg,#fff);color:inherit;border-radius:7px;padding:4px 10px;cursor:pointer;font:inherit}
  .pulse-card button.pulse-b[aria-pressed="true"],.pulse-card button.pulse-pri{background:var(--accent,#5b5bd6);border-color:var(--accent,#5b5bd6);color:var(--onFill,#fff)}
  .pulse-card textarea{width:100%;box-sizing:border-box;margin-top:8px;border:1px solid var(--line2,#e3e3e8);border-radius:7px;padding:6px;font:inherit;background:transparent;color:inherit;resize:vertical}
  .pulse-card .pulse-muted{opacity:.65;font-size:12px}`;
  document.head.appendChild(style);
}

function closePulse(){ document.getElementById('pulseCard')?.remove(); }

function pulseCard(inner, label){
  pulseStyles();
  closePulse();
  const card = document.createElement('div');
  card.id = 'pulseCard';
  card.className = 'pulse-card';
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-label', label);
  card.innerHTML = `<button type="button" class="pulse-x" data-pulse-close aria-label="Close">×</button>${inner}`;
  document.body.appendChild(card);
  return card;
}

function showWhatsNew(entry, after){
  const card = pulseCard(`<h3>${esc(entry.title)}</h3><ul>${entry.items.map(i => `<li>${esc(i)}</li>`).join('')}</ul>
    <div class="pulse-row"><span class="pulse-muted">Was this helpful?</span>
      <button type="button" class="pulse-b" data-pulse-helpful="up" aria-label="Helpful">👍</button>
      <button type="button" class="pulse-b" data-pulse-helpful="down" aria-label="Not helpful">👎</button>
      <span style="flex:1"></span><button type="button" class="pulse-b pulse-pri" data-pulse-close>Got it</button></div>`, entry.title);
  const done = helpful => {
    closePulse();
    api('/api/pulse/whats-new', { method: 'POST', body: JSON.stringify({ version: entry.version, helpful }) }).catch(() => {});
    after?.();
  };
  card.addEventListener('click', event => {
    const vote = event.target.closest('[data-pulse-helpful]');
    if(vote){ done(vote.dataset.pulseHelpful); return; }
    if(event.target.closest('[data-pulse-close]')) done(null);
  });
}

function showCsat(trigger = 'periodic'){
  let score = null;
  const card = pulseCard(`<h3>How satisfied are you with Cora?</h3>
    <div class="pulse-row" role="radiogroup" aria-label="1 is very unsatisfied, 5 is very satisfied">${[1, 2, 3, 4, 5].map(n =>
      `<button type="button" class="pulse-b" role="radio" aria-checked="false" aria-pressed="false" data-pulse-score="${n}">${n}</button>`).join('')}
      <span class="pulse-muted">1 = not at all, 5 = very</span></div>
    <textarea data-pulse-comment maxlength="500" rows="2" placeholder="What would make it better? (optional)"></textarea>
    <div class="pulse-muted">Please don't include customer names or meeting content.</div>
    <div class="pulse-row"><button type="button" class="pulse-b" data-pulse-later>Not now</button>
      <button type="button" class="pulse-b" data-pulse-never>Don't ask again</button><span style="flex:1"></span>
      <button type="button" class="pulse-b pulse-pri" data-pulse-send disabled>Send</button></div>`, 'Satisfaction survey');
  const send = body => {
    closePulse();
    api('/api/pulse/csat', { method: 'POST', body: JSON.stringify({ trigger, ...body }) }).catch(() => {});
  };
  card.addEventListener('click', event => {
    const pick = event.target.closest('[data-pulse-score]');
    if(pick){
      score = Number(pick.dataset.pulseScore);
      card.querySelectorAll('[data-pulse-score]').forEach(b => {
        const on = b === pick;
        b.setAttribute('aria-pressed', String(on)); b.setAttribute('aria-checked', String(on));
      });
      card.querySelector('[data-pulse-send]').disabled = false;
      return;
    }
    if(event.target.closest('[data-pulse-send]') && score){
      send({ score, comment: card.querySelector('[data-pulse-comment]').value });
      if(typeof toast === 'function') toast('Thanks — sent to the Cora team.');
      return;
    }
    if(event.target.closest('[data-pulse-never]')){ send({ outcome: 'never' }); return; }
    if(event.target.closest('[data-pulse-later]') || event.target.closest('[data-pulse-close]')) send({ outcome: 'later' });
  });
}

async function recordingNow(){
  try{
    const s = await window.electronAPI?.getRecordingState?.();
    const state = typeof s === 'string' ? s : s?.state;
    return state === 'recording' || state === 'paused';
  }catch{ return false; }
}

// What's new first; the survey only when nothing else was shown this time.
async function showPulse(){
  if(await recordingNow()) return;
  let due;
  try{ due = await api('/api/pulse'); }catch{ return; }
  if(due?.whats_new?.items?.length){ showWhatsNew(due.whats_new); return; }
  if(due?.csat_due) showCsat();
}

if(typeof document !== 'undefined' && typeof setTimeout === 'function' && !globalThis.__PULSE_MANUAL__){
  setTimeout(() => { showPulse(); }, PULSE_DELAY_MS);
}
