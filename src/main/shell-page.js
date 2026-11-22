// Which page the main window loads: the classic shell or UI shell v2
// (docs/specs/ui-shell-v2.md). Both are served by the same local server and
// read the same APIs; the stored setting ui_shell picks one (default classic).
// Settings in either page writes the setting and navigates itself; this only
// decides the page a new window or a reload opens.
const SHELL_PATHS = { classic: '', v2: '/v2/' };

function shellUrl(baseUrl, value) {
  return baseUrl + (SHELL_PATHS[value] ?? SHELL_PATHS.classic);
}

/** The URL for the stored choice; classic when the setting can't be read. */
async function resolveShellUrl(baseUrl, fetchSetting) {
  try {
    return shellUrl(baseUrl, await fetchSetting('ui_shell'));
  } catch (_err) {
    return shellUrl(baseUrl, 'classic');
  }
}

module.exports = { SHELL_PATHS, shellUrl, resolveShellUrl };
