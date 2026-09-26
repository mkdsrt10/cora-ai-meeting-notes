// ESLint flat config. Correctness-focused to start; tighten over time.
const globals = require('globals');

module.exports = [
  // Dashboard scripts share one global scope; scripts/lint-ui.js lints them together.
  { ignores: ['src/ui/web/js/**', 'node_modules/**', 'dist/**'] },
  {
    files: ['src/main.js', 'src/main/**/*.js', 'src/preload.js', 'src/meeting-detector.js', 'src/mic-watcher.js', 'eslint.config.js'],
    languageOptions: { ecmaVersion: 2023, sourceType: 'commonjs', globals: { ...globals.node } },
    rules: {
      'no-undef': 'error',
      'no-unused-vars': ['warn', { args: 'none', caughtErrors: 'none' }],
      'no-eval': 'error',
      'no-implied-eval': 'error',
    },
  },
  {
    files: ['src/ui/**/*.js'],
    languageOptions: { ecmaVersion: 2023, sourceType: 'script', globals: { ...globals.browser } },
    rules: {
      'no-undef': 'error',
      'no-unused-vars': ['warn', { args: 'none', caughtErrors: 'none' }],
      'no-eval': 'error',
      'no-implied-eval': 'error',
    },
  },
];
