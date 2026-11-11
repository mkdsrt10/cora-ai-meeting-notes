// The version stamp Electron hands the Python server at spawn: from the
// build-info.json the build script writes into a packaged app, or from the
// checkout when running from source.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { buildInfoEnv } = require('../../src/build-info');

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'cora-build-info-'));
}

test('packaged app stamps the server env from build-info.json in its resources', () => {
  const resourcesPath = tmpDir();
  fs.writeFileSync(path.join(resourcesPath, 'build-info.json'), JSON.stringify({
    version: '0.4.0', commit: 'abc1234', variant: 'team', receiver_url: 'https://receiver.example', token: 't0k',
  }));
  assert.deepEqual(buildInfoEnv({ isPackaged: true, resourcesPath, appVersion: '0.4.0' }), {
    CORA_APP_VERSION: '0.4.0',
    CORA_GIT_COMMIT: 'abc1234',
    CORA_BUILD_VARIANT: 'team',
    CORA_BETA_RECEIVER_URL: 'https://receiver.example',
    CORA_BETA_TOKEN: 't0k',
  });
});

test('from source the stamp is the app version, the short HEAD commit and the public variant', () => {
  const rootDir = path.resolve(__dirname, '..', '..');
  const env = buildInfoEnv({ isPackaged: false, resourcesPath: tmpDir(), appVersion: '0.3.3', rootDir, env: {} });
  assert.equal(env.CORA_APP_VERSION, '0.3.3');
  assert.match(env.CORA_GIT_COMMIT, /^[0-9a-f]{7,12}$/);
  assert.equal(env.CORA_BUILD_VARIANT, 'public');
  assert.equal(env.CORA_BETA_RECEIVER_URL, '');
  assert.equal(env.CORA_BETA_TOKEN, '');
});

test('from source a stray build-info.json is ignored, and a checkout without git has no commit', () => {
  const resourcesPath = tmpDir();
  fs.writeFileSync(path.join(resourcesPath, 'build-info.json'), JSON.stringify({ commit: 'abc1234', variant: 'team' }));
  const env = buildInfoEnv({ isPackaged: false, resourcesPath, appVersion: '0.3.3', rootDir: tmpDir(), env: {} });
  assert.equal(env.CORA_GIT_COMMIT, '');
  assert.equal(env.CORA_BUILD_VARIANT, 'public');
});

test('from source a developer can point at a receiver and pick the variant through the shell env', () => {
  const env = buildInfoEnv({
    isPackaged: false, resourcesPath: tmpDir(), appVersion: '0.3.3', rootDir: tmpDir(),
    env: { CORA_BUILD_VARIANT: 'team', CORA_BETA_RECEIVER_URL: 'http://127.0.0.1:9999', CORA_BETA_TOKEN: 'dev' },
  });
  assert.equal(env.CORA_BUILD_VARIANT, 'team');
  assert.equal(env.CORA_BETA_RECEIVER_URL, 'http://127.0.0.1:9999');
  assert.equal(env.CORA_BETA_TOKEN, 'dev');
});

test('a packaged app without build-info.json still starts as a public build with sending disabled', () => {
  assert.deepEqual(buildInfoEnv({ isPackaged: true, resourcesPath: tmpDir(), appVersion: '0.4.0' }), {
    CORA_APP_VERSION: '0.4.0',
    CORA_GIT_COMMIT: '',
    CORA_BUILD_VARIANT: 'public',
    CORA_BETA_RECEIVER_URL: '',
    CORA_BETA_TOKEN: '',
  });
});
