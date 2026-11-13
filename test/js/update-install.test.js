// The install step the updater runs on Update: download the release dmg and
// its .sha256 (stub asset server over real HTTP), verify, mount, copy over
// the installed bundle, unmount. hdiutil/ditto/xattr are a stub runner that
// mounts a fake dmg folder and copies with fs; nothing real is downloaded or
// mounted. Assertions are on the installed bundle on disk and the commands run.
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { createInstaller, bundlePathFromExe } = require('../../src/main/update-install');

const APP = 'Cora AI Meeting Notes.app';
const DMG_BYTES = Buffer.from('pretend this is a 650 MB disk image');

async function stubAssets({ sha = crypto.createHash('sha256').update(DMG_BYTES).digest('hex'), dmgStatus = 200 } = {}) {
  const srv = { requests: [] };
  const server = http.createServer((req, res) => {
    srv.requests.push(req.url);
    if (req.url.endsWith('.dmg.sha256')) {
      res.writeHead(200);
      res.end(`${sha}  Cora-AI-Meeting-Notes-0.4.0-arm64.dmg\n`);
    } else if (req.url.endsWith('.dmg')) {
      res.writeHead(dmgStatus);
      res.end(dmgStatus === 200 ? DMG_BYTES : 'nope');
    } else {
      res.writeHead(404); res.end();
    }
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}/download/v0.4.0`;
  srv.release = {
    version: '0.4.0',
    dmgName: 'Cora-AI-Meeting-Notes-0.4.0-arm64.dmg',
    dmgUrl: `${base}/Cora-AI-Meeting-Notes-0.4.0-arm64.dmg`,
    sha256Url: `${base}/Cora-AI-Meeting-Notes-0.4.0-arm64.dmg.sha256`,
  };
  srv.close = () => new Promise((r) => server.close(r));
  return srv;
}

// An installed bundle with a marker file, a temp root, and a stub runner:
// `hdiutil attach` lays out a new bundle at the mountpoint (unless
// `dmgHasApp` is false), `ditto` copies with fs (or fails on demand).
function setup(t, { dmgHasApp = true, dittoFails = false, attachFails = false } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-update-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const apps = path.join(root, 'Applications');
  const target = path.join(apps, APP);
  fs.mkdirSync(path.join(target, 'Contents', 'MacOS'), { recursive: true });
  fs.writeFileSync(path.join(target, 'Contents', 'version.txt'), 'old');
  const tmpRoot = path.join(root, 'tmp');
  fs.mkdirSync(tmpRoot);
  const commands = [];
  async function run(cmd, args) {
    commands.push([path.basename(cmd), ...args]);
    const name = path.basename(cmd);
    if (name === 'hdiutil' && args[0] === 'attach') {
      if (attachFails) throw Object.assign(new Error('hdiutil: attach failed'), { code: 1 });
      const dmg = args[1];
      assert.deepEqual(fs.readFileSync(dmg), DMG_BYTES, 'mounts the verified download');
      const mnt = args[args.indexOf('-mountpoint') + 1];
      fs.mkdirSync(mnt, { recursive: true });
      if (dmgHasApp) {
        fs.mkdirSync(path.join(mnt, APP, 'Contents', 'MacOS'), { recursive: true });
        fs.writeFileSync(path.join(mnt, APP, 'Contents', 'version.txt'), 'new');
      }
    } else if (name === 'ditto') {
      if (dittoFails) throw new Error('ditto: No space left on device');
      fs.cpSync(args[0], args[1], { recursive: true });
    }
  }
  const installed = () => fs.readFileSync(path.join(target, 'Contents', 'version.txt'), 'utf8');
  const leftovers = () => fs.readdirSync(apps).filter((n) => n !== APP);
  return { root, target, tmpRoot, run, commands, installed, leftovers };
}

test('the installed bundle path is derived from the running executable', () => {
  assert.equal(
    bundlePathFromExe('/Applications/Cora AI Meeting Notes.app/Contents/MacOS/Cora AI Meeting Notes'),
    '/Applications/Cora AI Meeting Notes.app',
  );
  assert.throws(() => bundlePathFromExe('/usr/local/bin/electron'), /not running from an app bundle/);
});

test('a verified download is staged beside the app; swapIn replaces the installed app', async (t) => {
  const assets = await stubAssets();
  t.after(() => assets.close());
  const s = setup(t);
  const install = createInstaller({ bundlePath: s.target, tmpRoot: s.tmpRoot, fetch: globalThis.fetch, run: s.run });
  const staged = await install(assets.release);
  assert.equal(s.installed(), 'old', 'the running bundle stays in place until swapIn');
  assert.deepEqual(s.leftovers(), [`${APP}.updating`], 'the new bundle is staged beside the app');
  staged.swapIn();
  assert.equal(s.installed(), 'new');
  assert.deepEqual(s.leftovers(), [], 'no staging or backup copy left next to the app');
  const names = s.commands.map((c) => `${c[0]} ${c[1]}`);
  assert.ok(names.includes('hdiutil attach'));
  assert.ok(names.includes('hdiutil detach'), 'unmounted');
  const attach = s.commands.find((c) => c[0] === 'hdiutil' && c[1] === 'attach');
  for (const flag of ['-nobrowse', '-readonly', '-noautoopen']) assert.ok(attach.includes(flag), flag);
  assert.deepEqual(fs.readdirSync(s.tmpRoot), [], 'temp download removed');
});

test('a checksum mismatch leaves the installed app untouched and never mounts', async (t) => {
  const assets = await stubAssets({ sha: 'f'.repeat(64) });
  t.after(() => assets.close());
  const s = setup(t);
  const install = createInstaller({ bundlePath: s.target, tmpRoot: s.tmpRoot, fetch: globalThis.fetch, run: s.run });
  await assert.rejects(install(assets.release), (err) => err.code === 'checksum_mismatch' && /checksum/.test(err.message));
  assert.equal(s.installed(), 'old');
  assert.deepEqual(s.commands, []);
  assert.deepEqual(fs.readdirSync(s.tmpRoot), []);
});

test('a failed download leaves the installed app untouched', async (t) => {
  const assets = await stubAssets({ dmgStatus: 404 });
  t.after(() => assets.close());
  const s = setup(t);
  const install = createInstaller({ bundlePath: s.target, tmpRoot: s.tmpRoot, fetch: globalThis.fetch, run: s.run });
  await assert.rejects(install(assets.release), (err) => err.code === 'download_failed');
  assert.equal(s.installed(), 'old');
});

test('a failed mount, a dmg without the app, or a failed copy leave the installed app untouched', async (t) => {
  const assets = await stubAssets();
  t.after(() => assets.close());
  for (const [opts, code] of [
    [{ attachFails: true }, 'mount_failed'],
    [{ dmgHasApp: false }, 'bad_dmg'],
    [{ dittoFails: true }, 'copy_failed'],
  ]) {
    const s = setup(t, opts);
    const install = createInstaller({ bundlePath: s.target, tmpRoot: s.tmpRoot, fetch: globalThis.fetch, run: s.run });
    await assert.rejects(install(assets.release), (err) => err.code === code, code);
    assert.equal(s.installed(), 'old', code);
    assert.deepEqual(s.leftovers(), [], `${code}: nothing left beside the app`);
    if (!opts.attachFails) assert.ok(s.commands.some((c) => c[0] === 'hdiutil' && c[1] === 'detach'), `${code}: unmounted`);
  }
});

test('a failed swap puts the old app back and removes the staged copy', async (t) => {
  const assets = await stubAssets();
  t.after(() => assets.close());
  const s = setup(t);
  const install = createInstaller({ bundlePath: s.target, tmpRoot: s.tmpRoot, fetch: globalThis.fetch, run: s.run });
  const staged = await install(assets.release);
  fs.rmSync(`${s.target}.updating`, { recursive: true, force: true }); // staged copy vanished meanwhile
  assert.throws(() => staged.swapIn(), (err) => err.code === 'copy_failed');
  assert.equal(s.installed(), 'old');
  assert.deepEqual(s.leftovers(), []);
});
