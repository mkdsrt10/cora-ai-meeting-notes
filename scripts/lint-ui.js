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

let errors = 0;
for (const m of messages) {
  const span = spans.findLast(s => m.line >= s.start) || spans[0];
  const where = `src/ui/web/${span.rel}:${m.line - span.start + 1}:${m.column}`;
  console.log(`${where}  ${m.severity === 2 ? 'error' : 'warning'}  ${m.message}  (${m.ruleId})`);
  if (m.severity === 2) errors++;
}
console.log(`${files.length} scripts, ${messages.length} problem(s), ${errors} error(s)`);
process.exit(errors ? 1 : 0);
