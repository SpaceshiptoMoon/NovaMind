<template>
  <el-dialog
    v-model="visible"
    title="技能包格式规范"
    width="720px"
    top="6vh"
    class="skill-format-dialog"
    destroy-on-close
  >
    <div class="format-doc">
      <h4>基本要求</h4>
      <ul class="format-rules">
        <li>
          上传 <b>.zip</b> 压缩包，解压后总大小不超过 <b>100MB</b>，单个资源文件不超过 <b>10MB</b>；
        </li>
        <li>
          <b>SKILL.md</b> 必须位于 ZIP 根目录或一级子目录（如 <code>my-skill/SKILL.md</code>）；
        </li>
        <li>
          SKILL.md 开头为 <b>YAML frontmatter</b>（<code>---</code> 包裹），须包含
          <code>name</code> 与 <code>description</code> 两个必填字段；
        </li>
        <li>
          <code>scripts/</code>、<code>references/</code>、<code>assets/</code>
          三个资源目录可选，其余目录与文件会被忽略。
        </li>
      </ul>

      <h4>字段说明</h4>
      <el-table :data="formatFields" size="small" border>
        <el-table-column prop="field" label="字段" width="170" />
        <el-table-column prop="required" label="必填" width="70" align="center" />
        <el-table-column prop="desc" label="说明" min-width="200" />
      </el-table>
      <el-alert
        class="format-tip"
        type="success"
        :closable="false"
        show-icon
        title="资源目录约定（scripts / references / assets）"
        description="三个目录名之外的资源不会入库：scripts/ 存放可执行脚本，references/ 存放参考文档，assets/ 存放静态资源。超出单文件 10MB 限制的资源会告警跳过，不影响技能本身上传。"
      />

      <div class="format-block-head">
        <h4>目录结构示例</h4>
        <div class="format-block-actions">
          <el-button size="small" text @click="copyExample('tree')">
            <el-icon><CopyDocument /></el-icon>
            复制
          </el-button>
          <el-button size="small" text @click="downloadTemplate('tree')">
            <el-icon><Download /></el-icon>
            下载模板
          </el-button>
        </div>
      </div>
      <pre class="format-pre"><code>{{ FORMAT_EXAMPLES.tree }}</code></pre>

      <div class="format-block-head">
        <h4>SKILL.md 示例</h4>
        <div class="format-block-actions">
          <el-button size="small" text @click="copyExample('md')">
            <el-icon><CopyDocument /></el-icon>
            复制
          </el-button>
          <el-button size="small" text @click="downloadTemplate('md')">
            <el-icon><Download /></el-icon>
            下载模板
          </el-button>
        </div>
      </div>
      <pre class="format-pre"><code>{{ FORMAT_EXAMPLES.md }}</code></pre>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="解析规则要点"
        description="name 须为 kebab-case（小写字母、数字、连字符，以字母开头），description 不超过 1024 字符；frontmatter 之外的多余字段会被忽略；SKILL.md 正文（frontmatter 之后的 Markdown）即注入 Agent 的技能指令，为空时仅给出告警。"
      />
    </div>
  </el-dialog>

  <el-tooltip content="查看技能包格式规范" placement="bottom">
    <el-button @click="visible = true">
      <el-icon><Document /></el-icon>
      格式说明
    </el-button>
  </el-tooltip>
</template>

<script setup lang="ts">
/**
 * 技能包格式规范弹窗 + 触发按钮（广场页头上传与详情页更新版本旁共用）。
 * 示例与字段说明须与后端 skill_parser.py 的解析规则保持一致。
 */

import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Download, Document } from '@element-plus/icons-vue'

const visible = ref(false)

// 格式示例：与后端 skill_parser.py 契约对齐
const FORMAT_EXAMPLES = {
  tree: `my-skill.zip
├── SKILL.md          # 必需：技能定义
├── scripts/          # 可选：可执行脚本
│   └── run.py
├── references/       # 可选：参考文档
│   └── api-docs.md
└── assets/           # 可选：静态资源
    └── banner.png`,
  md: `---
name: my-skill
description: 一句话说清这个技能做什么（不超过 1024 字符）
allowed-tools: Read Grep Bash
metadata:
  display_name: 我的技能
  category: 效率
  tags:
    - 示例
license: MIT
---

## 技能指令正文

这里是 Markdown 正文：frontmatter 之后的全部内容会作为技能指令
注入 Agent。写清楚触发时机、执行步骤与输出要求。`,
} as const

const formatFields = [
  {
    field: 'name',
    required: '是',
    desc: '技能唯一标识，须为 kebab-case（小写字母、数字、连字符，以字母开头）',
  },
  {
    field: 'description',
    required: '是',
    desc: '技能描述，不超过 1024 字符；广场搜索与 AI 智能匹配都依赖它',
  },
  { field: 'allowed-tools', required: '否', desc: '空格分隔的工具名列表，声明技能可引用的工具' },
  {
    field: 'metadata.display_name',
    required: '否',
    desc: '展示名；缺省时直接用 name 作为广场卡片标题',
  },
  { field: 'metadata.category', required: '否', desc: '分类，用于广场的分类筛选' },
  { field: 'metadata.tags', required: '否', desc: '标签列表（YAML 数组），用于广场的标签筛选' },
  { field: 'license', required: '否', desc: '许可证声明' },
  { field: '其他字段', required: '否', desc: '解析时忽略，可自行保留备注信息' },
]

/** 复制格式示例到剪贴板 */
async function copyExample(fmt: 'tree' | 'md') {
  try {
    await navigator.clipboard.writeText(FORMAT_EXAMPLES[fmt])
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择文本复制')
  }
}

/** 把格式示例下载为模板文件 */
function downloadTemplate(fmt: 'tree' | 'md') {
  const content = fmt === 'md' ? FORMAT_EXAMPLES.md : FORMAT_EXAMPLES.tree
  const blob = new Blob([content], {
    type: fmt === 'md' ? 'text/markdown;charset=utf-8' : 'text/plain;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fmt === 'md' ? 'SKILL-template.md' : 'structure-template.txt'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.format-doc h4 {
  margin: var(--space-4) 0 var(--space-2);
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.format-doc h4:first-child {
  margin-top: 0;
}

.format-rules {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.9;
  color: var(--color-text-secondary);
}

.format-rules code {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 1px 4px;
  background: var(--color-bg-hover);
  border-radius: var(--radius-sm);
}

.format-tip {
  margin-top: var(--space-3);
}

.format-block-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.format-pre {
  margin: 0 0 var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--color-bg-hover);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow-x: auto;
  font-size: 12px;
  line-height: 1.7;
  font-family: var(--font-mono, Menlo, Consolas, monospace);
  color: var(--color-text);
  white-space: pre;
}
</style>

<style>
/* el-dialog 经 teleport 到 body，弹窗体高度约束需全局类收敛作用范围（与测评页同款） */
.skill-format-dialog .el-dialog {
  height: 86vh;
}

.skill-format-dialog .el-dialog__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
</style>
