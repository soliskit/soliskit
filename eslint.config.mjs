import js from '@eslint/js'
import globals from 'globals'
import tseslint from 'typescript-eslint'
import promise from 'eslint-plugin-promise'
import prettierRecommended from 'eslint-plugin-prettier/recommended'

export default tseslint.config(
  { ignores: ['node_modules/'] },
  js.configs.recommended,
  tseslint.configs.recommended,
  promise.configs['flat/recommended'],
  prettierRecommended,
  {
    // tsconfig.json includes all JS with checkJs, so the project service
    // can type it.
    files: ['**/*.js'],
    extends: [
      tseslint.configs.recommendedTypeChecked,
      tseslint.configs.strictTypeChecked
    ],
    languageOptions: {
      parserOptions: { projectService: true }
    }
  },
  {
    // eslint.config.mjs has no tsconfig coverage: untyped rules only.
    files: ['*.mjs'],
    extends: [tseslint.configs.disableTypeChecked]
  },
  {
    languageOptions: {
      globals: { ...globals.node }
    },
    linterOptions: {
      reportUnusedDisableDirectives: true
    }
  }
)
