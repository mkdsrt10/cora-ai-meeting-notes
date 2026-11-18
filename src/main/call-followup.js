// Green-room follow-up (see GLOSSARY.md, Green room): the mic is on but no live
// Call exists yet, so re-check every intervalMs until boundMs after mic-on.
// Ticks never overlap (the next is scheduled after the check settles) and each
// check has a budget. The owner stops it on a Call found, mic off, a Recording
// starting or Dismiss; after the bound only the watcher's slow poll remains.
// timers is injectable: { now, setTimeout, clearTimeout }.
const { TICK_BUDGET_MS } = require('../meeting-detector');

function createFollowup({ check, onFound, timers = { now: Date.now, setTimeout, clearTimeout }, intervalMs = 3000, boundMs = 120000, budgetMs = TICK_BUDGET_MS }) {
  let active = false;
  let timer = null;
  let micOnAt = 0;
  let run = 0;

  function schedule(id) {
    const left = micOnAt + boundMs - timers.now();
    if (left <= 0) { active = false; return; }
    timer = timers.setTimeout(() => tick(id), Math.min(intervalMs, left));
  }

  async function tick(id) {
    timer = null;
    let result;
    try { result = await check({ budgetMs }); } catch { result = null; }
    if (id !== run || !active) return;
    if (result && result.status === 'found' && result.call) {
      active = false;
      onFound(result.call, Math.round((timers.now() - micOnAt) / 1000));
      return;
    }
    schedule(id);
  }

  return {
    // micOnAtMs: when the mic went on (defaults to now).
    start(micOnAtMs) {
      this.stop();
      active = true;
      micOnAt = micOnAtMs === undefined ? timers.now() : micOnAtMs;
      schedule(run);
    },
    stop() {
      active = false;
      run += 1;
      if (timer !== null) timers.clearTimeout(timer);
      timer = null;
    },
    get active() { return active; },
  };
}

module.exports = { createFollowup };
