#!/usr/bin/env node
// Lint the dashboard scripts as the browser runs them: the classic scripts
// listed in index.html share one global scope, so per-file ESLint would
// flag every cross-file reference. Concatenate them in load order, lint the
// result with scope-aware rules, and map findings back to file:line.
const fs = require('fs');
const path = require('path');
const { Linter } = require('eslint');
const globals = require('globals');

const webDir = path.join(__dirname, '..', 'src', 'ui', 'web');
const html = fs.readFileSync(path.join(webDir, 'index.html'), 'utf8');
const files = [...html.matchAll(/<script src="\/([^"?]+)[^"]*"><\/script>/g)].map(m => m[1]);

// Plugin page scripts (src/ui/web/plugins/<id>.js) are loaded at runtime by
// js/plugin-host.js, after every core script and before init.js runs load().
// Lint them in that position, and check each one is a real bundled Plugin
// whose View the host creates (no hand-written section in index.html).
const repoRoot = path.join(__dirname, '..');
const pluginDir = path.join(webDir, 'plugins');
const pluginFiles = fs.existsSync(pluginDir) ? fs.readdirSync(pluginDir).filter(f => f.endsWith('.js')).sort() : [];
const problems = [];
for (const file of pluginFiles) {
  const id = file.slice(0, -3);
  const text = fs.readFileSync(path.join(pluginDir, file), 'utf8');
  if (!fs.existsSync(path.join(repoRoot, 'plugins', id, '__init__.py'))) problems.push(`src/ui/web/plugins/${file}: no bundled plugin plugins/${id}/`);
  if (!new RegExp(`registerView\\(\\s*['"]${id}['"]`).test(text)) problems.push(`src/ui/web/plugins/${file}: must call registerView('${id}', ...)`);
  if (html.includes(`id="view-${id}"`)) problems.push(`src/ui/web/index.html: section view-${id} is created by the plugin host; remove it`);
}
const initAt = files.indexOf('js/init.js');
files.splice(initAt < 0 ? files.length : initAt, 0, ...pluginFiles.map(f => `plugins/${f}`));

let combined = '';
const spans = [];
for (const rel of files) {
  const text = fs.readFileSync(path.join(webDir, rel), 'utf8');
  const start = combined.split('\n').length;
  combined += text.endsWith('\n') ? text : text + '\n';
  spans.push({ rel, start, lines: text.split('\n').length });
}

const messages = new Linter({ configType: 'flat' }).verify(combined, [{
  languageOptions: { ecmaVersion: 2023, sourceType: 'script', globals: { ...globals.browser } },
  rules: {
    'no-undef': 'error',
    'no-redeclare': 'error',
    'no-unused-vars': ['warn', { args: 'none', caughtErrors: 'none', vars: 'local' }],
    'no-eval': 'error',
    'no-implied-eval': 'error',
  },
}]);

let errors = problems.length;
problems.forEach(p => console.log(`${p}  error  (plugin-view)`));
for (const m of messages) {
  const span = spans.findLast(s => m.line >= s.start) || spans[0];
  const where = `src/ui/web/${span.rel}:${m.line - span.start + 1}:${m.column}`;
  console.log(`${where}  ${m.severity === 2 ? 'error' : 'warning'}  ${m.message}  (${m.ruleId})`);
  if (m.severity === 2) errors++;
}
console.log(`${files.length} scripts, ${messages.length} problem(s), ${errors} error(s)`);
process.exit(errors ? 1 : 0);
