// The version stamp the Python server receives at spawn (CORA_* env).
// A packaged app has no package.json or .git at its code root, so the build
// script writes build-info.json into the app resources; from source the
// stamp comes from the checkout. Pure Node (no electron) so it is testable
// and the build script can call it.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const BUILD_INFO_FILE = 'build-info.json';

function readBuildInfo(resourcesPath) {
  try {
    return JSON.parse(fs.readFileSync(path.join(resourcesPath, BUILD_INFO_FILE), 'utf8'));
  } catch {
    return null;
  }
}

function sourceCommit(rootDir) {
  try {
    return execFileSync('git', ['rev-parse', '--short', 'HEAD'], {
      cwd: rootDir, encoding: 'utf8', timeout: 3000, stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return '';
  }
}

// From source the commit is the checkout's HEAD and the rest comes from the
// developer's shell (variant defaults to public, sending off).
function sourceBuildInfo(rootDir, env) {
  return {
    commit: sourceCommit(rootDir),
    variant: env.CORA_BUILD_VARIANT,
    receiver_url: env.CORA_BETA_RECEIVER_URL,
    token: env.CORA_BETA_TOKEN,
  };
}

function buildInfoEnv({ isPackaged, resourcesPath, appVersion, rootDir, env = process.env }) {
  const info = (isPackaged ? readBuildInfo(resourcesPath) : sourceBuildInfo(rootDir, env)) || {};
  return {
    CORA_APP_VERSION: appVersion || info.version || '',
    CORA_GIT_COMMIT: info.commit || '',
    CORA_BUILD_VARIANT: info.variant || 'public',
    CORA_BETA_RECEIVER_URL: info.receiver_url || '',
    CORA_BETA_TOKEN: info.token || '',
  };
}

module.exports = { BUILD_INFO_FILE, readBuildInfo, buildInfoEnv };
