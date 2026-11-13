// Export: the save dialog opens in Downloads with the suggested name, a
// cancel writes nothing, and the result never carries the chosen folder.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createExportFile } = require('../../src/main/export-file');

function harness({ choice = { canceled: false, filePath: '/Users/me/Desktop/notes.md' }, failWith } = {}) {
  const h = { dialogs: [], writes: [] };
  h.save = createExportFile({
    downloadsDir: '/Users/me/Downloads',
    showSaveDialog: async (options) => { h.dialogs.push(options); return choice; },
    writeFile: async (file, text) => {
      if (failWith) { const err = new Error('nope'); err.code = failWith; throw err; }
      h.writes.push([file, text]);
    },
  });
  return h;
}

test('saves to the chosen file and reports only its name', async () => {
  const h = harness();
  const result = await h.save({ filename: '2026-11-12 Weekly sync.md', markdown: '# Weekly sync\n' });
  assert.equal(h.dialogs[0].defaultPath, '/Users/me/Downloads/2026-11-12 Weekly sync.md');
  assert.deepEqual(h.writes, [['/Users/me/Desktop/notes.md', '# Weekly sync\n']]);
  assert.deepEqual(result, { outcome: 'saved', name: 'notes.md' });
});

test('cancel writes nothing', async () => {
  const h = harness({ choice: { canceled: true } });
  assert.deepEqual(await h.save({ filename: 'a.md', markdown: 'x' }), { outcome: 'cancelled' });
  assert.equal(h.writes.length, 0);
});

test('a name without an extension gets .md', async () => {
  const h = harness({ choice: { canceled: false, filePath: '/tmp/out' } });
  await h.save({ filename: 'a.md', markdown: 'x' });
  assert.equal(h.writes[0][0], '/tmp/out.md');
});

test('an unsafe suggested name falls back to Meeting.md', async () => {
  const h = harness();
  await h.save({ filename: '../../etc/passwd.md', markdown: 'x' });
  assert.equal(h.dialogs[0].defaultPath, '/Users/me/Downloads/Meeting.md');
});

test('empty text and write errors fail without a path', async () => {
  assert.equal((await harness().save({ filename: 'a.md', markdown: '' })).outcome, 'failed');
  const result = await harness({ failWith: 'EACCES' }).save({ filename: 'a.md', markdown: 'x' });
  assert.equal(result.outcome, 'failed');
  assert.doesNotMatch(JSON.stringify(result), /Desktop/);
});
