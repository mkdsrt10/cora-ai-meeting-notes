// Shared by both shells (index.html and v2/index.html): escaping,
// formatting and the local API client. No DOM assumptions beyond fetch and
// the clipboard. Classic script sharing global scope (load it first).

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtDate = value => value ? new Date(value).toLocaleString([], {dateStyle:'medium', timeStyle:'short'}) : 'Unknown date';
const fmtDuration = seconds => `${Math.floor((seconds || 0) / 60)}:${String(Math.round(seconds || 0) % 60).padStart(2,'0')}`;
const fmtBytes = value => { let n = Number(value || 0), u = 0; const units=['B','KB','MB','GB','TB']; while(n >= 1000 && u < units.length-1){n/=1000;u++} return `${n.toFixed(u > 1 ? 1 : 0)} ${units[u]}`; };

async function api(path, options={}) {
  const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}
async function copyText(value){
  if(navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
  const node=document.createElement('textarea'); node.value=value; document.body.appendChild(node); node.select(); document.execCommand('copy'); node.remove();
}
