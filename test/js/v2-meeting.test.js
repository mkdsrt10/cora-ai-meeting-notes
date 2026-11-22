// Meeting page (T4): tabs and property rows by contribution, the checklist
// calling the Action items API, chip order and +N, the selection bar, the
// confirm panel by kind, live captions and Draft labels. Made-up meeting only.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadPage, text } = require('./v2-dom');

const REC = {
  id: 'r1', title: 'Weekly product sync', recorded_at: '2026-11-18T10:00:00', duration_seconds: 2520, analysis_stage: 'ready',
  participant_names: ['Alex Rivera', 'Sam Kim'], folder_id: null, notes: 'my own line', metadata: {},
  enhanced_notes: '## Overview\nPricing for the team tier is close.\n\n## Action Items\n- Draft pricing copy (Owner: You)\n\n## Decisions\n- Ship the dashboard v1',
  transcript_view: { source: 'full', label: 'Transcript' },
  transcript_segments: [{ start: '00:00', end: '00:05', speaker_id: 'You', speaker_name: 'You', text: 'Morning all.' }],
  participants: [{ raw_name: 'Alex R', display_name: 'Alex Rivera', person_id: null }], live_transcript: [],
};
const ITEMS = [
  { id: 'a1', text: 'Draft pricing copy', owner: 'You', due: 'Fri', done: false },
  { id: 'a2', text: 'Book five interviews', owner: null, due: null, done: false },
];
const P = (o) => ({ plugin_id: 'p-one', ...o });
const ROWS = [
  P({ surface: 'action_item.chip', kind: 'annotation', target: 'a1', label: 'Link to task: Pricing', state: 'pending', proposal_key: 'k1', shown: true, more: 1 }),
  P({ surface: 'action_item.chip', kind: 'annotation', target: 'a1', label: 'Tracker', state: 'link', url: 'https://example.invalid/t', shown: false }),
  P({ surface: 'recording.property', kind: 'annotation', label: 'Tracker', detail: 'Call Log ✓', url: 'https://example.invalid/log' }),
  P({ surface: 'recording.tab', kind: 'panel', label: 'Insights', panel: { title: 'Insights', blocks: [{ type: 'kv', rows: [['Talk time', '40%']] }] } }),
  P({ surface: 'recording.footer', kind: 'annotation', label: '2 tracker suggestions', badge: 2, proposal_key: 'k1' }),
  P({ surface: 'selection.action', kind: 'action', label: 'Send to chat', action: { id: 'send', applies_to: 'selection' } }),
  P({ surface: 'recording.menu', kind: 'action', label: 'Suggest again', action: { id: 'again', applies_to: 'recording' } }),
];
const PROPOSALS = [
  { key: 'k1', kind: 'task.link', title: 'Link to Pricing v2', state: 'pending', action_item_ids: ['a1'], target: { id: 't1', title: 'Pricing v2', url: 'https://example.invalid/t1' }, fields: [{ name: 'comment', label: 'Comment', value: 'From the sync', editable: true, type: 'textarea' }], sends: 'A comment on Pricing v2' },
  { key: 'k2', kind: 'task.create', title: 'Create “Book five interviews”', state: 'pending', action_item_ids: ['a2'], fields: [{ name: 'title', label: 'Title', value: 'Book five interviews', editable: true }], sends: 'A new task' },
];

function replies({ record = REC, rows = ROWS, items = ITEMS, proposals = PROPOSALS } = {}) {
  return {
    '/api/dashboard': { recordings: [record] }, '/api/folders': { folders: [{ id: 'f1', name: 'Product' }] },
    '/api/outbox/count': { count: 2 }, '/api/plugins': { stages: {} }, '/api/onboarding/meeting-types': { meeting_types: [] },
    'GET /api/surfaces': (url) => ({ contributions: url.includes('context=recording') ? rows : [] }),
    '/api/recording': record, '/api/action-items': { items }, '/api/outbox/recording': { proposals, links: [] }, '/api/outbox': { proposals },
    '/api/people': { people: [{ id: 'p1', name: 'Alex Rivera' }] },
    'POST /api/action-items*': (url, body) => ({ ok: true, item: { ...items[0], ...body } }),
    'POST /api/outbox/confirm': { ok: true }, 'POST /api/outbox/dismiss': { ok: true },
    'POST /api/surfaces/action': { proposal: { key: 'k9', kind: 'message.post', title: 'Send 2 Action items', fields: [{ name: 'text', label: 'Message', value: 'hi', type: 'textarea' }], sends: 'One message' } },
    '/api/recording/live-transcript': { lines: [{ recording_id: 'r1', track: 'mic', seg: 1, start: 1, text: 'Hello there', final: true }], cursor: 10 },
  };
}
async function meeting(opts = {}, before) {
  const p = loadPage('v2/index.html', { replies: replies(opts), before });
  await p.flush();
  await p.run('go("meeting", { id: "r1" })');
  await p.flush();
  return p;
}

test('document page: breadcrumb, editable title, When/People/Folder rows and plugin property rows', async () => {
  const p = await meeting();
  assert.match(text(p.$('#crumb')), /Home.*Weekly product sync/);
  assert.equal(p.$('#meetingTitle').getAttribute('contenteditable'), 'true');
  const props = p.$$('#props .k').map(text);
  assert.deepEqual(props, ['When', 'People', 'Folder', 'Key phrases', 'T Tracker']);
  assert.equal(p.$('#props a').getAttribute('href'), 'https://example.invalid/log');
  p.$('#meetingTitle').textContent = 'Pricing sync';
  p.$('#meetingTitle').dispatchEvent(new (require('./v2-dom').Event)('focusout'));
  await p.flush();
  assert.ok(p.posts().some((c) => c.url === '/api/recording/title' && c.body.title === 'Pricing sync'));
});

test('tabs: Notes / Transcript / Notepad and the rest, plus a plugin tab only when contributed', async () => {
  let p = await meeting();
  assert.deepEqual(p.$$('#tabs [data-tab]').map(text), ['Notes', 'Transcript', 'Notepad', 'Participants', 'Timeline', 'Processing', 'Insights']);
  await p.click('[data-tab="plugin:0"]');
  assert.deepEqual(p.$('#tabBody .kv').children.map(text), ['Talk time', '40%']);
  p = await meeting({ rows: [] });
  assert.equal(p.$('[data-tab^="plugin:"]'), null, 'no empty plugin tab');
  assert.equal(p.$('#props .smark'), null);
});

test('Notes: the Action items section becomes the checklist; chips and +N; footer Review all', async () => {
  const p = await meeting();
  assert.deepEqual(p.$$('#notesBody h3').map(text), ['Overview', 'Action Items', 'Decisions']);
  assert.equal(p.$$('#checklist .row').length, 2);
  const a1 = p.$('[data-item="a1"]');
  assert.equal(text(a1.querySelector('.chip .t')), 'Link to task: Pricing');
  assert.equal(text(a1.querySelector('[data-chip-more]')), '+1');
  assert.equal(p.$('[data-item="a2"] .chip'), null);
  assert.match(text(p.$('#suggestionRow')), /2 tracker suggestions.*Review all/);
  await p.click('[data-review-all]');
  assert.equal(p.$('#confirmPanel').hidden, false);
  assert.equal(p.$('#confirmPanel').dataset.key, 'k1');
  assert.match(text(p.$('.ph')), /1 of 2/);
  await p.click('[data-confirm-proposal]');
  assert.deepEqual(p.posts().find((c) => c.url === '/api/outbox/confirm').body, { key: 'k1', edits: { comment: 'From the sync' } });
  assert.equal(p.$('#confirmPanel').dataset.key, 'k2', 'Review all advances');
  await p.click('[data-dismiss-proposal]');
  assert.equal(p.$('#confirmPanel').hidden, true);
});

test('checklist: tick, edit, add and delete go through the Action items API', async () => {
  const p = await meeting();
  await p.click('[data-tick="a1"]');
  assert.deepEqual(p.posts().find((c) => c.url === '/api/action-items/a1').body, { done: true });
  const rt = p.$('[data-edit-item="a2"]');
  rt.textContent = 'Book six interviews';
  rt.dispatchEvent(new (require('./v2-dom').Event)('focusout'));
  await p.flush();
  assert.ok(p.posts().some((c) => c.url === '/api/action-items/a2' && c.body.text === 'Book six interviews'));
  await p.input('#addItem', 'Write the screener');
  await p.key('Enter', {}, p.$('#addItem'));
  assert.deepEqual(p.posts().find((c) => c.url === '/api/action-items').body, { recording_id: 'r1', text: 'Write the screener' });
  await p.click('[data-delete-item="a2"]');
  assert.ok(p.posts().some((c) => c.url === '/api/action-items/a2/delete'));
});

test('selection bar: Mark done and Copy from Cora, plugin selection actions open the confirm panel', async () => {
  const p = await meeting();
  assert.equal(p.$('#selectionBar').hidden, true);
  await p.click('[data-select-item="a1"]');
  await p.click('[data-select-item="a2"]');
  const bar = p.$('#selectionBar');
  assert.equal(bar.hidden, false);
  assert.deepEqual(bar.querySelectorAll('button').map(text), ['Mark done', 'Copy', 'Send to chat', '×']);
  assert.equal(text(bar.querySelector('.n')), '2 selected');
  await p.click('[data-surface-action="send"]');
  const post = p.posts().find((c) => c.url === '/api/surfaces/action');
  assert.deepEqual(post.body.action_item_ids, ['a1', 'a2']);
  assert.equal(p.$('#confirmPanel').dataset.key, 'k9');
  assert.equal(p.$('.ph .kind').dataset.kind, 'message.post');
  await p.click('[data-close-panel]');
  await p.click('[data-bulk="copy"]');
  assert.match(p.context.__clipboard, /Draft pricing copy \(You\)/);
  await p.click('[data-bulk="done"]');
  assert.deepEqual(p.posts().filter((c) => /\/api\/action-items\/a\d$/.test(c.url)).map((c) => [c.url, c.body.done]),
    [['/api/action-items/a1', true], ['/api/action-items/a2', true]]);
});

test('confirm panel draws every Proposal kind, task.comment and page.create included', async () => {
  const p = await meeting();
  for (const [kind, verb] of [['task.create', 'Create'], ['task.link', 'Link'], ['task.update', 'Update'], ['task.comment', 'Post comment'], ['message.post', 'Send'], ['page.create', 'Create page']]) {
    p.context.__p = { key: `k-${kind}`, kind, title: `A ${kind}`, body_md: 'Decision: ship it', target: { title: 'Pricing v2', url: 'https://example.invalid/t' }, fields: [], sends: 'exactly this' };
    p.run('closeConfirmPanel(); openConfirmPanel(__p)');
    assert.equal(text(p.$('[data-confirm-proposal]')), verb, kind);
    assert.match(text(p.$('[data-sends]')), /🔒 exactly this/);
    assert.match(text(p.$('[data-proposal-body]')), /Decision: ship it/);
    const hasTarget = !!p.$('[data-target-card]');
    assert.equal(hasTarget, ['task.link', 'task.update', 'task.comment'].includes(kind), kind);
  }
});

test('⋯ menu lists Cora commands and plugin recording.menu actions; Hide plugins posts the flag', async () => {
  const p = await meeting();
  await p.click('#meetingMenu');
  const labels = p.$$('.menu button').map(text);
  for (const l of ['Rename', 'Export notes (.md)', 'Export notes + transcript (.md)', 'Re-summarize…', 'Add to this meeting (record more)', 'Open folder in Finder', 'Participants', 'Speaker timeline', 'Processing history', 'Hide plugins for this meeting']) assert.ok(labels.includes(l), l);
  assert.ok(labels.some((l) => /Suggest again/.test(l)));
  await p.click('[data-meeting-cmd="plugins"]');
  assert.deepEqual(p.posts().find((c) => c.url === '/api/recording/plugins-excluded').body, { id: 'r1', excluded: true });
});

test('Transcript: the full transcript when ready; live captions and Draft labels follow transcript_view', async () => {
  let p = await meeting();
  await p.click('[data-tab="transcript"]');
  assert.match(text(p.$('#notepadTranscript')), /You.*Morning all\./);
  let caption;
  const before = (ctx) => { ctx.electronAPI = { onLiveCaption: (fn) => { caption = fn; }, getRecordingState: async () => 'recording', onRecordingStateChange() {} }; };
  const live = { ...REC, analysis_stage: 'recording', enhanced_notes: '', transcript_segments: [], transcript_view: { source: 'live', label: 'Live captions' } };
  p = await meeting({ record: live }, before);
  assert.match(text(p.$('[data-tab="transcript"]')), /Live captions/);
  assert.ok(p.$('#liveBar [data-rec="stop"]'), 'recording controls on the live meeting');
  await p.click('[data-tab="transcript"]');
  await p.flush();
  assert.match(text(p.$('#notepadTranscript')), /Live captions · a draft until processing finishes/);
  assert.match(text(p.$('#notepadTranscript')), /Hello there/);
  caption({ recordingId: 'r1', chunkId: 'r1', track: 'sys', seg: 2, speaker: 'Them', start: 3, text: 'Partial words', final: false });
  assert.match(text(p.$('#notepadTranscript')), /Partial words/);

  const draft = { ...REC, analysis_stage: 'processing', enhanced_notes: '', transcript_segments: [], transcript_view: { source: 'live', label: 'Draft transcript' }, draft_notes: { markdown: '## Overview\nDraft summary', label: 'Draft' } };
  p = await meeting({ record: draft });
  assert.equal(text(p.$('#notesBody .status.draft')), 'Draft');
  assert.match(text(p.$('#notesBody')), /Draft summary/);
  assert.match(text(p.$('[data-tab="transcript"]')), /Draft transcript/);
});

test('Notepad saves what you type; Participants link to People', async () => {
  const p = await meeting();
  await p.click('[data-tab="notepad"]');
  assert.equal(p.$('#notepadText').value, 'my own line');
  await p.input('#notepadText', 'my own line, edited');
  await p.runTimers();
  assert.deepEqual(p.posts().find((c) => c.url === '/api/recording/notes').body, { id: 'r1', text: 'my own line, edited' });
  await p.click('[data-tab="participants"]');
  await p.change('[data-participant-map]', 'p1');
  assert.deepEqual(p.posts().find((c) => c.url === '/api/recording/participant').body, { id: 'r1', raw_name: 'Alex R', action: 'map', person_id: 'p1' });
});

test('notices, key phrases and earlier versions, as in the classic look', async () => {
  const record = { ...REC, needs_speaker_confirmation: true, speaker_profiles: [{ speaker_id: 'S1', label: { name: 'Speaker 1' }, turns: 4 }, { speaker_id: 'S2', turns: 2 }],
    suggested_self_speaker_id: 'S2', cloud_offer: 'slow', key_phrases: [{ term: 'Team tier' }], versions: ['20261118T120000'] };
  const p = await meeting({ record });
  assert.ok(p.$('[data-notice="speaker"]') && p.$('[data-notice="cloud"]'));
  assert.equal(p.$('#selfSpeaker').value, 'S2');
  await p.click('[data-confirm-speaker]');
  assert.deepEqual(p.posts().find((c) => c.url === '/api/recording/confirm-speaker').body, { id: 'r1', speaker_id: 'S2' });
  await p.click('[data-dismiss-cloud]');
  assert.ok(p.posts().some((c) => c.url === '/api/recording/cloud-offer/dismiss'));
  await p.input('#addPhrase', 'Pricing v2');
  await p.key('Enter', {}, p.$('#addPhrase'));
  assert.deepEqual(p.posts().find((c) => c.url === '/api/recording/key-phrase').body, { id: 'r1', action: 'add', term: 'Pricing v2' });
  assert.ok(p.$('#notesVersion'));
});

test('never shows another meeting’s Action items: on switch, while loading, while recording, or after a late reply', async () => {
  const live = { ...REC, id: 'r2', title: 'Live call', analysis_stage: 'recording', enhanced_notes: '', notes: '', transcript_view: { source: 'none', label: 'Transcript' } };
  const gates = {};
  const later = (key, value) => new Promise((resolve) => { gates[key] = () => resolve(value); });
  const p = loadPage('v2/index.html', { settings: { tour_seen: true }, replies: { ...replies(),
    '/api/recording': (url) => (url.includes('id=r2') ? live : REC),
    '/api/action-items': (url) => (url.includes('recording=r2') ? later('r2', { items: [] }) : later('r1', { items: ITEMS })),
    'GET /api/surfaces': (url) => ({ contributions: url.includes('id=r1') ? ROWS : [] }),
    '/api/outbox/recording': (url) => (url.includes('id=r1') ? { proposals: PROPOSALS, links: [] } : { proposals: [], links: [] }),
  } });
  await p.flush();

  // 1. Open r1 and let it load: its items show; select one.
  const first = p.run('go("meeting", { id: "r1" })');
  await p.flush(); gates.r1(); await first; await p.flush();
  assert.equal(p.$$('#checklist .row').length, 2);
  await p.click('[data-select-item="a1"]');
  assert.equal(p.$('#selectionBar').hidden, false);

  // 2. Switch to the live meeting r2: while it loads nothing of r1 is on screen.
  const second = p.run('go("meeting", { id: "r2" })');
  await p.flush();
  assert.equal(p.$('[data-item="a1"]'), null, 'no r1 rows while r2 loads');
  assert.equal(p.$('#selectionBar').hidden, true, 'no r1 selection while r2 loads');
  gates.r2(); await second; await p.flush();
  assert.equal(text(p.$('#meetingTitle')), 'Live call');
  assert.equal(p.$('#checklist .row'), null, 'a live meeting with no notes shows none of r1’s Action items');
  assert.equal(p.run('mt.items.length'), 0);

  // 3. A late reply for r1, after moving on to r2, is dropped.
  const back = p.run('go("meeting", { id: "r1" })');
  await p.flush();
  const third = p.run('go("meeting", { id: "r2" })');
  await p.flush(); gates.r2(); await third; await p.flush();
  gates.r1(); await back; await p.flush();
  assert.equal(text(p.$('#meetingTitle')), 'Live call');
  assert.equal(p.run('mt.id'), 'r2');
  assert.equal(p.run('mt.items.length'), 0, 'r1’s late items never land on r2');
  assert.equal(p.$('[data-item="a1"]'), null);
});
