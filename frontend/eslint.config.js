import js from '@eslint/js'
import svelte from 'eslint-plugin-svelte'
import globals from 'globals'
import svelteConfig from './svelte.config.js'

export default [
  { ignores: ['dist/**', 'node_modules/**', 'public/**'] },

  js.configs.recommended,
  ...svelte.configs['flat/base'],

  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      // `const { [id]: _, ...rest } = obj` is the standard omit-a-key idiom;
      // the discarded binding is never meant to be read.
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },

  {
    files: ['**/*.svelte'],
    languageOptions: {
      parserOptions: { svelteConfig },
    },
    rules: {
      // ESLint analyses a `$:` block as straight-line code, so it cannot see
      // that a value assigned at the end of the block is read at the top of
      // the *next* run (Results.svelte's `_wasRunning` latch, AdminUsers'
      // `fetched` guard). Every report in this codebase was a false positive.
      'no-useless-assignment': 'off',

      // Catches a mutable built-in Set/Map/Date/URL held as component state,
      // where mutations are invisible to the reactivity system. This is the
      // rule that independently flagged the plain Set in Review.svelte.
      'svelte/prefer-svelte-reactivity': 'error',

      // Guards against reassigning a value that a `$:` statement derives.
      // Note this only covers `$:`-declared values — it does NOT catch a
      // reactive block writing to a plain `let`.
      'svelte/no-reactive-reassign': 'error',
    },
  },

  {
    // TODO: delete this exemption once #76 lands — it replaces this file's
    // plain Set with SvelteSet, which is exactly what the rule asks for.
    // Without the exemption this config cannot pass CI on its own.
    files: ['src/routes/Review.svelte'],
    rules: { 'svelte/prefer-svelte-reactivity': 'off' },
  },

  {
    files: ['**/*.test.js', 'src/setupTests.js'],
    languageOptions: { globals: globals.vitest },
  },
]
