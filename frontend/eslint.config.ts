import { globalIgnores } from 'eslint/config'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'
import pluginVitest from '@vitest/eslint-plugin'
import pluginOxlint from 'eslint-plugin-oxlint'
import skipFormatting from 'eslint-config-prettier/flat'

// To allow more languages other than `ts` in `.vue` files, uncomment the following lines:
// import { configureVueProject } from '@vue/eslint-config-typescript'
// configureVueProject({ scriptLangs: ['ts', 'tsx'] })
// More info at https://github.com/vuejs/eslint-config-typescript/#advanced-setup

export default defineConfigWithVueTs(
  {
    name: 'app/files-to-lint',
    files: ['**/*.{vue,ts,mts,tsx}'],
  },

  globalIgnores(['**/dist/**', '**/dist-ssr/**', '**/coverage/**']),

  ...pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,

  {
    ...pluginVitest.configs.recommended,
    files: ['src/**/__tests__/*'],
  },

  ...pluginOxlint.buildFromOxlintConfigFile('.oxlintrc.json'),

  {
    name: 'allow-common-component-names',
    files: ['src/components/common/*.vue'],
    rules: {
      'vue/multi-word-component-names': 'off',
    },
  },

  {
    name: 'kb-config-form-model-pass-through',
    // KB 配置页「父持有表单模型、子组件分节编辑」模式：子组件 v-model 绑定
    // prop 对象的属性（configForm.xxx）。Vue 官方允许（对象引用共享，非替换
    // prop 本身），vue/no-mutating-props 按模板表达式字面量误报。五个
    // Kb*Section 组件成组出现，豁免限于此清单防止扩散到真正的违规。
    files: [
      'src/components/knowledge/KbMultimodalParsingSection.vue',
      'src/components/knowledge/KbQuestionGenerationSection.vue',
      'src/components/knowledge/KbSplittingSection.vue',
      'src/components/knowledge/KbTextParsingSection.vue',
      'src/components/knowledge/KbWikiSection.vue',
    ],
    rules: {
      'vue/no-mutating-props': 'off',
    },
  },

  {
    name: 'allow-underscore-unused-vars',
    // 下划线前缀 = 有意不用（如解构排除字段），不视为死代码
    files: ['**/*.{vue,ts,mts,tsx}'],
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
    },
  },

  skipFormatting,
)
