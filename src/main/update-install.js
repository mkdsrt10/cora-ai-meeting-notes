// The install step behind the update banner's Update button: the same steps
// as scripts/install.sh (download the release dmg and its .sha256, verify,
// hdiutil attach, ditto the .app out, detach), with one difference: the new
// bundle is staged beside the installed one and swapped in by rename, so any
// failed step leaves the installed app exactly as it was. Staging and the swap
// are two steps: the slow part (download, verify, copy) runs at once, the swap
// waits until nothing runs from the old bundle any more (the updater calls it
// only when idle, right before relaunch). Pure Node (no electron): main passes
// the bundle path and the command runner.
//
//   createInstaller({ bundlePath, tmpRoot, fetch, run, log }) -> install(release) -> { swapIn() }
//     release = { version, dmgName, dmgUrl, sha256Url }   (from src/updater.js)
//     install rejects with err.code: download_failed | checksum_mismatch | mount_failed | bad_dmg | copy_failed
//     swapIn throws err.code copy_failed (the installed app is left as it was)
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');
const { Readable } = require('stream');
const { pipeline } = require('stream/promises');

const HDIUTIL = '/usr/bin/hdiutil';
const DITTO = '/usr/bin/ditto';
const XATTR = '/usr/bin/xattr';

// <bundle>.app/Contents/MacOS/<exe> -> <bundle>.app
function bundlePathFromExe(exe) {
  const bundle = path.resolve(exe, '..', '..', '..');
  if (!bundle.endsWith('.app') || path.basename(path.dirname(exe)) !== 'MacOS') {
    throw Object.assign(new Error('Cora is not running from an app bundle, so it cannot update itself.'), { code: 'not_packaged' });
  }
  return bundle;
}

function defaultRun(cmd, args) {
  return new Promise((resolve, reject) => {
    execFile(cmd, args, { timeout: 10 * 60 * 1000 }, (err, stdout) => (err ? reject(err) : resolve(stdout)));
  });
}

function fail(code, message, cause) {
  return Object.assign(new Error(message), { code, cause });
}

async function download(fetch, url, file) {
  let res;
  try {
    res = await fetch(url, { redirect: 'follow' });
  } catch (err) {
    throw fail('download_failed', 'The update could not be downloaded. Check the connection and try again.', err);
  }
  if (!res.ok || !res.body) {
    throw fail('download_failed', `The update could not be downloaded (HTTP ${res.status}).`);
  }
  try {
    await pipeline(Readable.fromWeb(res.body), fs.createWriteStream(file, { mode: 0o600 }));
  } catch (err) {
    throw fail('download_failed', 'The update download was interrupted. Try again.', err);
  }
}

async function sha256Of(file) {
  const hash = crypto.createHash('sha256');
  await pipeline(fs.createReadStream(file), hash);
  return hash.digest('hex');
}

function createInstaller({ bundlePath, tmpRoot = os.tmpdir(), fetch = globalThis.fetch, run = defaultRun, log = () => {} }) {
  const appName = path.basename(bundlePath);
  const staging = `${bundlePath}.updating`;
  const previous = `${bundlePath}.previous`;

  // Swap the staged bundle in by rename (same volume), putting the old one
  // back if the second rename fails. Only safe once nothing runs from the old
  // bundle: its files are deleted here.
  function swapIn() {
    try {
      fs.rmSync(previous, { recursive: true, force: true });
      fs.renameSync(bundlePath, previous);
      try {
        fs.renameSync(staging, bundlePath);
      } catch (err) {
        fs.renameSync(previous, bundlePath);
        throw err;
      }
      fs.rmSync(previous, { recursive: true, force: true });
    } catch (err) {
      fs.rmSync(staging, { recursive: true, force: true });
      throw fail('copy_failed', 'The update could not be put into place. Cora was not changed.', err);
    }
  }

  return async function install(release) {
    const work = fs.mkdtempSync(path.join(tmpRoot, 'cora-update-'));
    const dmg = path.join(work, path.basename(release.dmgName || 'Cora.dmg'));
    const mnt = path.join(work, 'mnt');
    let mounted = false;
    let staged = false;
    try {
      log(`downloading ${release.dmgName}`);
      await download(fetch, release.dmgUrl, dmg);
      await download(fetch, release.sha256Url, `${dmg}.sha256`);
      const expected = (fs.readFileSync(`${dmg}.sha256`, 'utf8').trim().split(/\s+/)[0] || '').toLowerCase();
      const actual = await sha256Of(dmg);
      if (!/^[0-9a-f]{64}$/.test(expected) || expected !== actual) {
        throw fail('checksum_mismatch', 'The download did not match its published checksum, so it was not installed.');
      }
      log(`sha256 ${actual}`);

      fs.mkdirSync(mnt);
      mounted = true; // detach even after a failed attach, as install.sh does
      try {
        await run(HDIUTIL, ['attach', dmg, '-nobrowse', '-readonly', '-noautoopen', '-mountpoint', mnt, '-quiet']);
      } catch (err) {
        throw fail('mount_failed', 'The update could not be opened (disk image did not mount).', err);
      }
      const source = path.join(mnt, appName);
      if (!fs.existsSync(source)) throw fail('bad_dmg', `The update does not contain ${appName}.`);

      fs.rmSync(staging, { recursive: true, force: true });
      try {
        await run(DITTO, [source, staging]);
        await run(XATTR, ['-dr', 'com.apple.quarantine', staging]).catch(() => {});
      } catch (err) {
        throw fail('copy_failed', 'The update could not be copied into place (is the disk full?). Cora was not changed.', err);
      }
      staged = true;
      log(`staged ${release.version} at ${staging}`);
      return {
        swapIn() {
          swapIn();
          log(`installed ${release.version} at ${bundlePath}`);
        },
      };
    } finally {
      if (!staged) fs.rmSync(staging, { recursive: true, force: true });
      if (mounted) await run(HDIUTIL, ['detach', mnt, '-quiet']).catch((err) => log(`detach failed: ${err.message}`));
      fs.rmSync(work, { recursive: true, force: true });
    }
  };
}

module.exports = { createInstaller, bundlePathFromExe };
