// What Cora itself costs while a Recording is live: CPU% and memory of the
// Electron processes (main, renderers, GPU), the capture helpers
// (dual-capture, speaker-watch, mic-watch) and the Python server, sampled
// every ~10 s from start to stop. stop() returns the aggregates that ride on
// recording_stopped (python/usage_events.py CATALOG, docs/TRACING.md):
//   app_cpu_avg, app_cpu_max         Electron processes, summed, % of one core
//   app_rss_max_mb                   Electron processes, summed
//   helpers_cpu_avg, helpers_rss_max_mb   capture helpers, summed
//   python_rss_max_mb                the Python server
// Numbers only: no process arguments, paths or titles leave this module.
// Sampling failures are skipped; with no sample every value is null.

const { execFile } = require('child_process');

const HELPERS = new Set(['dual-capture', 'speaker-watch', 'mic-watch']);
const INTERVAL_MS = 10000;

// `ps -A -o pid=,ppid=,pcpu=,rss=,comm=` -> [{ pid, ppid, cpu, rssKb, name }]
// (name is the executable's basename; the path is dropped here).
function parsePs(text) {
  const out = [];
  for (const line of String(text || '').split('\n')) {
    const m = line.trim().match(/^(\d+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+(.+)$/);
    if (!m) continue;
    const name = m[5].trim().split('/').pop();
    out.push({ pid: Number(m[1]), ppid: Number(m[2]), cpu: Number(m[3]), rssKb: Number(m[4]), name });
  }
  return out;
}

function listProcesses() {
  return new Promise((resolve) => {
    execFile('ps', ['-A', '-o', 'pid=,ppid=,pcpu=,rss=,comm='], { timeout: 3000, maxBuffer: 4 * 1024 * 1024 },
      (err, stdout) => resolve(err ? [] : parsePs(stdout)));
  });
}

// One sample: Electron metrics (getAppMetrics: cpu.percentCPUUsage,
// memory.workingSetSize in KB) plus the helpers and Python among our own
// child processes (ppid = main's pid).
function sampleOf({ metrics, processes, mainPid, pythonPid }) {
  let appCpu = 0;
  let appRssKb = 0;
  for (const m of metrics || []) {
    appCpu += (m.cpu && Number(m.cpu.percentCPUUsage)) || 0;
    appRssKb += (m.memory && Number(m.memory.workingSetSize)) || 0;
  }
  let helpersCpu = 0;
  let helpersRssKb = 0;
  let pythonRssKb = null;
  for (const p of processes || []) {
    if (pythonPid && p.pid === pythonPid) { pythonRssKb = p.rssKb; continue; }
    if (p.ppid === mainPid && HELPERS.has(p.name)) {
      helpersCpu += p.cpu;
      helpersRssKb += p.rssKb;
    }
  }
  return { appCpu, appRssKb, helpersCpu, helpersRssKb, pythonRssKb };
}

const mb = (kb) => Math.round(kb / 1024);
const round1 = (x) => Math.round(x * 10) / 10;

function aggregate(samples) {
  if (!samples.length) {
    return { app_cpu_avg: null, app_cpu_max: null, app_rss_max_mb: null, helpers_cpu_avg: null, helpers_rss_max_mb: null, python_rss_max_mb: null };
  }
  const avg = (k) => round1(samples.reduce((a, s) => a + s[k], 0) / samples.length);
  const max = (k) => Math.max(...samples.map((s) => s[k]));
  const py = samples.map((s) => s.pythonRssKb).filter((v) => typeof v === 'number');
  return {
    app_cpu_avg: avg('appCpu'),
    app_cpu_max: round1(max('appCpu')),
    app_rss_max_mb: mb(max('appRssKb')),
    helpers_cpu_avg: avg('helpersCpu'),
    helpers_rss_max_mb: mb(max('helpersRssKb')),
    python_rss_max_mb: py.length ? mb(Math.max(...py)) : null,
  };
}

function createResourceSampler({ getAppMetrics, listProcesses: list = listProcesses, mainPid, pythonPid = () => null,
  clock = { setTimeout, clearTimeout }, intervalMs = INTERVAL_MS } = {}) {
  let samples = [];
  let timer = null;
  let running = false;

  async function take() {
    try {
      const [metrics, processes] = await Promise.all([Promise.resolve().then(getAppMetrics), list()]);
      if (running) samples.push(sampleOf({ metrics, processes, mainPid, pythonPid: pythonPid() }));
    } catch (err) {
      console.warn('[Cora usage] resource sample skipped:', err && err.message);
    }
  }

  function tick() {
    if (!running) return;
    take().finally(() => { if (running) timer = clock.setTimeout(tick, intervalMs); });
  }

  return {
    start() {
      if (running) return;
      running = true;
      samples = [];
      tick();
    },
    // The aggregates for the Recording that just stopped.
    stop() {
      running = false;
      if (timer) clock.clearTimeout(timer);
      timer = null;
      const out = aggregate(samples);
      samples = [];
      return out;
    },
  };
}

module.exports = { createResourceSampler, parsePs, sampleOf, aggregate, HELPERS };
