// The shared "is a Call live in this tab?" snippet, run the way a browser runs
// it: the exact page expression the detector sends, evaluated against a tiny
// fake document. The expected answers come from the contract's selector list.
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { el, runPage } = require('./fake-page');

function ask(hostname, elements = []) {
  const raw = runPage(hostname, elements);
  assert.equal(typeof raw, 'string', 'the page answers with a JSON string');
  return JSON.parse(raw);
}

const BUTTON = 'button';
const HUDDLE_ROOT = '[role="dialog"]';

test('a Meet page with no leave control is not live', () => {
  assert.deepEqual(ask('meet.google.com'), { live: false, label: 'Google Meet' });
  assert.deepEqual(ask('meet.google.com', [el({ sel: [BUTTON], attrs: { 'aria-label': 'Join now' } })]), { live: false, label: 'Google Meet' });
});

test('a Meet page with a Leave call control is live', () => {
  for (const sel of ['button[aria-label^="Leave call"]', '[data-tooltip^="Leave call"]', '[jsname][aria-label*="Leave"]']) {
    assert.deepEqual(ask('meet.google.com', [el({ sel: [sel] })]), { live: true, label: 'Google Meet' }, sel);
  }
});

test('a Meet button whose label or text starts with Leave call / End call is live', () => {
  assert.equal(ask('meet.google.com', [el({ sel: [BUTTON], text: 'Leave call' })]).live, true);
  assert.equal(ask('meet.google.com', [el({ sel: [BUTTON], attrs: { 'aria-label': 'End call for everyone' } })]).live, true);
});

test('a Slack chat tab with no huddle is not live', () => {
  assert.deepEqual(ask('app.slack.com'), { live: false, label: 'Slack Huddle' });
  const chat = [
    el({ sel: [BUTTON], attrs: { 'aria-label': 'Leave call' } }),
    el({ sel: [HUDDLE_ROOT], attrs: { role: 'dialog', 'aria-label': 'Huddle' }, children: [el({ sel: [BUTTON], text: 'Start huddle' })] }),
    el({ sel: ['[data-qa="huddle_details_title"]'], text: '   ' }),
  ];
  assert.deepEqual(ask('app.slack.com', chat), { live: false, label: 'Slack Huddle' });
});

test('an expanded Slack huddle (participant tiles) is live', () => {
  assert.deepEqual(ask('app.slack.com', [el({ sel: ['[data-qa^="huddle_peer_tile_userId_"]'] })]), { live: true, label: 'Slack Huddle' });
  const container = el({ sel: ['[data-qa="huddle_window_content_container"]'], children: [el({ sel: ['[data-qa^="huddle_peer_tile_userId_"]'] })] });
  assert.equal(ask('acme.slack.com', [container]).live, true);
});

test('the huddle content container alone is not live', () => {
  assert.deepEqual(ask('app.slack.com', [el({ sel: ['[data-qa="huddle_window_content_container"]'] })]), { live: false, label: 'Slack Huddle' });
});

test('a Slack huddle dialog with a Leave or End huddle button is live', () => {
  const dialog = (button) => el({ sel: [HUDDLE_ROOT], attrs: { 'aria-label': 'Huddle in #design' }, children: [button] });
  assert.equal(ask('app.slack.com', [dialog(el({ sel: [BUTTON], attrs: { 'aria-label': 'Leave huddle' } }))]).live, true);
  assert.equal(ask('app.slack.com', [dialog(el({ sel: [BUTTON], text: 'End the huddle' }))]).live, true);
  const huddleBar = el({ sel: ['[data-qa*="huddle"]'], attrs: { 'data-qa': 'huddle_bottom_bar_content' }, children: [el({ sel: [BUTTON], attrs: { 'aria-label': 'End huddle' } })] });
  assert.equal(ask('app.slack.com', [huddleBar]).live, true);
  const notHuddle = el({ sel: [HUDDLE_ROOT], attrs: { 'aria-label': 'Huddle in #design' }, children: [el({ sel: [BUTTON], text: 'Leave channel' })] });
  assert.equal(ask('app.slack.com', [notHuddle]).live, false);
});

test('a Leave or End huddle button anywhere on a Slack page is live', () => {
  assert.equal(ask('app.slack.com', [el({ sel: [BUTTON], attrs: { 'aria-label': 'Leave huddle' } })]).live, true);
  const elsewhere = el({ sel: [HUDDLE_ROOT], attrs: { 'aria-label': 'Preferences' }, children: [el({ sel: ['[role="button"]'], text: 'End the huddle' })] });
  assert.equal(ask('app.slack.com', [elsewhere]).live, true);
});

test('a Slack huddle collapsed to the mini-bar is live', () => {
  assert.equal(ask('app.slack.com', [el({ sel: ['[data-qa="huddle_details_title"]'], text: 'Huddle with Ana' })]).live, true);
  assert.equal(ask('app.slack.com', [el({ sel: ['[data-qa="huddle_details_title"]'], text: 'Huddle in #general' })]).live, true);
});

test('the snippet survives being flattened onto one line', () => {
  const { LIVE_CALL_JS } = require('../../capture/live-call-snippet');
  assert.doesNotThrow(() => new vm.Script(LIVE_CALL_JS.replace(/\n/g, ' ')));
  assert.ok(!/(^|[^:])\/\//.test(LIVE_CALL_JS), 'no // line comments');
});
