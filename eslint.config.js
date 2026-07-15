import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    ignores: ['node_modules/**', 'playwright-report/**', 'test-results/**'],
  },
  js.configs.recommended,
  {
    files: ['static/**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'script',
      globals: globals.browser,
    },
    rules: {
      'no-empty': ['error', {allowEmptyCatch: true}],
      'no-undef': 'off',
      'no-unused-vars': 'off',
      'no-useless-assignment': 'off',
    },
  },
  {
    files: ['tests/js/**/*.js'],
    languageOptions: {
      globals: {...globals.browser, ...globals.node},
    },
  },
  {
    files: ['tests/browser/**/*.js'],
    languageOptions: {
      globals: {...globals.node, ...globals.browser},
    },
  },
  {
    files: ['*.config.js'],
    languageOptions: {
      globals: globals.node,
    },
  },
];
