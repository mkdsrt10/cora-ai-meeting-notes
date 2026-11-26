// Metrics-only meeting processing history; never render stored prompts or responses.
let processingHistoryRequest = 0;
let processingHistoryTimer = null;

function processingMetric(value, suffix = '', digits = 1) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toLocaleString(undefined, {maximumFractionDigits:digits})}${suffix}` : '—';
}

function processingTime(epoch) {
  return typeof epoch === 'number' ? new Date(epoch * 1000).toLocaleString() : 'Unknown time';
}

function renderProcessingRun(run, calls, open) {
  const known = key => calls.filter(c => typeof c[key] === 'number');
  const tokens = key => known(key).length ? processingMetric(known(key).reduce((sum,c)=>sum+c[key],0), '', 0) : '—';
  const memory = known('peak_memory_mb');
  const priced = known('cost_usd');
  const cost = priced.reduce((sum,c)=>sum+c.cost_usd,0);
  const costText = !calls.length ? '—' : priced.length === calls.length ? `$${cost.toFixed(4)} API` : priced.length && cost > 0 ? `$${cost.toFixed(4)} reported · partial` : 'Cloud cost not reported';
  const wall = run.duration_s ?? (run.status === 'running' ? (Date.now()/1000 - run.started_at) : null);
  const rows = calls.map(call => {
    const offset = Math.max(0, call.started_at - run.started_at);
    const callCost = call.cost_usd == null ? 'Not reported' : call.cost_source === 'local_api' ? '$0 API' : `$${call.cost_usd.toFixed(6)}`;
    const width = wall > 0 ? Math.max(0.5, Math.min(100, (call.duration_s || 0) / wall * 100)) : 0;
    const left = wall > 0 ? Math.min(99.5, offset / wall * 100) : 0;
    return `<tr>
      <td><strong>${esc(call.name)}</strong><small>${esc(call.kind)} · ${esc(call.status || 'unknown')}</small>${call.error ? `<small class="processing-error">${esc(call.error)}</small>` : ''}</td>
      <td>${esc(call.provider || 'Unknown')}<small>${esc(call.model || 'Not recorded')}</small>${call.model_revision ? `<small>Revision ${esc(call.model_revision.slice(0,12))}</small>` : ''}</td>
      <td title="${esc(processingTime(call.started_at))}">+${processingMetric(offset, 's')}<small>${esc(new Date(call.started_at*1000).toLocaleTimeString())}</small><div class="processing-call-track"><span style="margin-left:${left}%;width:${Math.min(width,100-left)}%"></span></div></td>
      <td>${processingMetric(call.duration_s,'s')}</td>
      <td>${processingMetric(call.input_tokens,'',0)} / ${processingMetric(call.output_tokens,'',0)}</td>
      <td>${processingMetric(call.generation_tps ?? call.tokens_per_s,' tok/s')}<small>${call.audio_s != null ? processingMetric(call.audio_s,'s audio') : ''}${call.rtf != null ? ` · ${processingMetric(call.rtf,' RTF',3)}` : ''}</small></td>
      <td>${processingMetric(call.peak_memory_mb,' MB')}<small>${call.process_peak_rss_mb != null ? `Process peak ${processingMetric(call.process_peak_rss_mb,' MB')}` : ''}</small></td>
      <td>${esc(callCost)}</td></tr>`;
  }).join('');
  return `<details class="processing-run" data-run-id="${esc(run.id)}" ${open ? 'open' : ''}><summary><strong>${esc(run.pipeline)}</strong> · ${esc(processingTime(run.started_at))} · ${esc(run.status || 'unknown')} · ${processingMetric(wall,'s')}</summary>
    ${run.error ? `<p class="processing-error">${esc(run.error)}</p>` : ''}
    <div class="processing-run-metrics"><span>${calls.length} recorded events</span><span>Reported tokens: ${tokens('input_tokens')} in / ${tokens('output_tokens')} out</span><span>Metal peak: ${memory.length ? processingMetric(Math.max(...memory.map(c=>c.peak_memory_mb)),' MB') : '—'}</span><span>${esc(costText)}</span></div>
    ${run.process_peak_rss_mb != null ? `<p class="muted">Process lifetime peak RSS: ${processingMetric(run.process_peak_rss_mb,' MB')}</p>` : ''}
    ${calls.length ? `<div class="processing-table-scroll"><table class="processing-table"><thead><tr><th>Call / status</th><th>Provider / model</th><th>Start</th><th>Duration</th><th>Tokens in / out</th><th>Throughput</th><th>Metal peak</th><th>Cost (USD)</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="muted">No completed model calls recorded yet. Refresh while processing.</p>'}
  </details>`;
}

async function loadProcessingHistory(quiet = false) {
  clearTimeout(processingHistoryTimer);
  const record = selectedRecording();
  const host = $('#processingHistory');
  if (!host) return;
  const request = ++processingHistoryRequest;
  if (!record) { host.innerHTML = ''; return; }
  const expanded = new Set([...host.querySelectorAll('details[open][data-run-id]')].map(el=>el.dataset.runId));
  if (!quiet) host.innerHTML = '<p class="muted">Loading processing history…</p>';
  try {
    const data = await api(`/api/recording/processing?id=${encodeURIComponent(record.id)}`);
    if (request !== processingHistoryRequest || selectedRecording()?.id !== record.id) return;
    const runs = [...data.runs];
    const knownRuns = new Set(runs.map(run=>run.id));
    const ungrouped = data.calls.filter(call=>!knownRuns.has(call.run_id));
    if (ungrouped.length) runs.push({id:'ungrouped',pipeline:'Other recorded calls',started_at:Math.min(...ungrouped.map(c=>c.started_at)),status:'recorded'});
    host.innerHTML = (!data.enabled ? '<p class="muted">Local tracing is currently disabled. Existing history is shown below.</p>' : '') +
      (data.truncated ? '<p class="muted">Showing the latest 50 runs and 2,000 calls. Older history is not included here.</p>' : '') +
      (runs.length ? runs.map((run,i)=>renderProcessingRun(run, run.id === 'ungrouped' ? ungrouped : data.calls.filter(c=>c.run_id===run.id), quiet ? expanded.has(run.id) : i===0)).join('') : '<p class="muted">No processing traces are available for this meeting. Older meetings may predate tracing or have expired history. New processing runs will appear here when local tracing is enabled.</p>') +
      '<p class="processing-history-footnote muted">— means not recorded. Tokens are provider-reported or measured locally; missing usage is excluded. Metal memory is a per-call peak, never a sum. Process RSS is the process lifetime high-water mark and includes other work. Local API cost excludes electricity and hardware; cloud prices are not guessed. A “running” run may have been interrupted if its process exited before finalizing.</p>';
    if (data.runs.some(run => run.status === 'running')) {
      processingHistoryTimer = setTimeout(() => {
        if (!document.hidden && $('[data-notepad-tab="processing"]')?.classList.contains('active') && selectedRecording()?.id === record.id) loadProcessingHistory(true);
      }, 3000);
    }
  } catch (error) {
    if (request === processingHistoryRequest && selectedRecording()?.id === record.id) host.innerHTML = `<p class="processing-error">${esc(error.message)}</p>`;
  }
}

$('#refreshProcessingHistory')?.addEventListener('click', () => loadProcessingHistory());
