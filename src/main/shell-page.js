// Which page the main window loads: the classic shell or UI shell v2
// (docs/specs/ui-shell-v2.md). Both are served by the same local server and
// read the same APIs; the stored setting ui_shell picks one (the server's
// default is v2 since 1.0.1). Setup (onboarding) exists only in the classic
// page, so until it is finished the classic page opens whatever the setting.
// Settings in either page writes the setting and navigates itself; this only
// decides the page a new window or a reload opens.
const SHELL_PATHS = { classic: '', v2: '/v2/' };

function shellUrl(baseUrl, value) {
  return baseUrl + (SHELL_PATHS[value] ?? SHELL_PATHS.classic);
}

/** The URL for the stored choice; classic when the setting can't be read or
 * setup is not finished (onboardingComplete() false). */
async function resolveShellUrl(baseUrl, fetchSetting, onboardingComplete = async () => true) {
  try {
    const choice = await fetchSetting('ui_shell');
    if (choice === 'v2' && !(await onboardingComplete())) return shellUrl(baseUrl, 'classic');
    return shellUrl(baseUrl, choice);
  } catch (_err) {
    return shellUrl(baseUrl, 'classic');
  }
}

module.exports = { SHELL_PATHS, shellUrl, resolveShellUrl };
