// The app's own CPU and memory while recording (src/main/app-resources.js):
// sampled every 10 s, aggregated onto recording_stopped. ps and
// getAppMetrics are faked.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createResourceSampler, parsePs, sampleOf, aggregate } = require('../../src/main/app-resources');
const { fakeClock, flush } = require('./fakes');

const PS = `  100     1   12.0  250000 /Applications/Cora AI Meeting Notes.app/Contents/MacOS/Cora AI Meeting Notes
  201   100    8.5   40960 /Applications/Cora AI Meeting Notes.app/Contents/Resources/bin/dual-capture
  202   100    1.5   20480 /Applications/Cora AI Meeting Notes.app/Contents/Resources/bin/speaker-watch
  203   100   30.0  512000 /Applications/Cora AI Meeting Notes.app/Contents/Resources/python/bin/python3
  300     1   50.0   99999 /usr/bin/dual-capture
`;

test('ps lines become pid, parent, cpu, rss and a bare executable name (no path)', () => {
  const rows = parsePs(PS);
  assert.equal(rows.length, 5);
  assert.deepEqual(rows[1], { pid: 201, ppid: 100, cpu: 8.5, rssKb: 40960, name: 'dual-capture' });
  assert.ok(rows.every((r) => !r.name.includes('/')));
});

test('a sample sums Electron processes, our own helpers and the Python server only', () => {
  const s = sampleOf({
    metrics: [{ cpu: { percentCPUUsage: 3 }, memory: { workingSetSize: 200000 } },
      { cpu: { percentCPUUsage: 7 }, memory: { workingSetSize: 100000 } }],
    processes: parsePs(PS), mainPid: 100, pythonPid: 203,
  });
  assert.deepEqual(s, { appCpu: 10, appRssKb: 300000, helpersCpu: 10, helpersRssKb: 61440, pythonRssKb: 512000 });
});

test('no samples means every aggregate is null', () => {
  assert.deepEqual(aggregate([]), { app_cpu_avg: null, app_cpu_max: null, app_rss_max_mb: null,
    helpers_cpu_avg: null, helpers_rss_max_mb: null, python_rss_max_mb: null });
});

test('samples every 10 s from start to stop and reports averages and peaks', async () => {
  const clock = fakeClock();
  const cpus = [10, 30, 20];
  let i = 0;
  const sampler = createResourceSampler({
    getAppMetrics: () => [{ cpu: { percentCPUUsage: cpus[Math.min(i++, 2)] }, memory: { workingSetSize: 1024 * (100 + i) } }],
    listProcesses: async () => parsePs(PS), mainPid: 100, pythonPid: () => 203, clock,
  });
  sampler.start();
  await clock.advance(25000);
  const out = sampler.stop();
  assert.deepEqual(out, { app_cpu_avg: 20, app_cpu_max: 30, app_rss_max_mb: 103, helpers_cpu_avg: 10,
    helpers_rss_max_mb: 60, python_rss_max_mb: 500 });
  await clock.advance(30000);
  assert.equal(clock.pendingTimers(), 0, 'stopped: no more sampling');
  await flush();
});
