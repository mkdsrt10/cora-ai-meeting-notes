// Export: save one Recording's Markdown (built by GET /api/recording/export)
// where the user chooses. The renderer passes a suggested file name and the
// text; only this process sees the path, and the result says what happened
// without naming it.
const path = require('path');

const SAFE_NAME = /^[^/\\:\x00-\x1f]{1,120}\.md$/;
const MAX_BYTES = 20 * 1024 * 1024;

// showSaveDialog(options) -> { canceled, filePath }; writeFile(path, text);
// downloadsDir: where the dialog opens (read at each export, so a getter may
// defer app.getPath until the app is ready).
function createExportFile(deps) {
  const { showSaveDialog, writeFile } = deps;
  return async function saveMarkdown(request) {
    const { filename, markdown } = request || {};
    if (typeof markdown !== 'string' || !markdown || Buffer.byteLength(markdown) > MAX_BYTES) {
      return { outcome: 'failed', error: 'Nothing to export.' };
    }
    const name = typeof filename === 'string' && SAFE_NAME.test(filename) ? filename : 'Meeting.md';
    const choice = await showSaveDialog({
      title: 'Export meeting',
      defaultPath: path.join(deps.downloadsDir, name),
      filters: [{ name: 'Markdown', extensions: ['md'] }],
      properties: ['createDirectory', 'showOverwriteConfirmation'],
    });
    if (!choice || choice.canceled || !choice.filePath) return { outcome: 'cancelled' };
    const target = path.extname(choice.filePath) ? choice.filePath : `${choice.filePath}.md`;
    try {
      await writeFile(target, markdown);
      return { outcome: 'saved', name: path.basename(target) };
    } catch (err) {
      return { outcome: 'failed', error: err?.code === 'EACCES' ? 'Cora cannot write to that folder.' : 'The file could not be saved.' };
    }
  };
}

module.exports = { createExportFile };
