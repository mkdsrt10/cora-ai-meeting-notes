// The probe runner spawns `<bin> --probe`; tests use throwaway shell scripts as the helper.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createProbeRunner } = require('../../src/recording/desktop-probe');

function fakeBin(t, body) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'probe-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const bin = path.join(dir, 'speaker-watch');
  fs.writeFileSync(bin, `#!/bin/sh\n[ "$1" = "--probe" ] || exit 9\n${body}\n`, { mode: 0o755 });
  return bin;
}

test('resolves the one JSON line the helper prints', async (t) => {
  const bin = fakeBin(t, `echo '{"ax":"ok","zoomMeeting":true,"slackHuddle":false}'`);
  assert.deepEqual(await createProbeRunner({ bin })({ timeoutMs: 2000 }), { ax: 'ok', zoomMeeting: true, slackHuddle: false });
});

test('a non-zero exit, junk output, or a missing binary rejects', async (t) => {
  await assert.rejects(createProbeRunner({ bin: fakeBin(t, 'exit 3') })({ timeoutMs: 2000 }));
  await assert.rejects(createProbeRunner({ bin: fakeBin(t, 'echo nope') })({ timeoutMs: 2000 }), /no JSON/);
  await assert.rejects(createProbeRunner({ bin: null })({ timeoutMs: 2000 }), /no speaker-watch/);
});

test('a helper still running past the timeout is killed and rejects', async (t) => {
  const bin = fakeBin(t, 'sleep 30');
  const started = Date.now();
  await assert.rejects(createProbeRunner({ bin })({ timeoutMs: 150 }), /killed/);
  assert.ok(Date.now() - started < 5000);
});
