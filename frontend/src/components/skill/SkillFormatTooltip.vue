<template>
  <el-tooltip placement="bottom-end" :show-after="200" popper-class="skill-format-popper">
    <template #content>
      <div class="skill-format-tip">
        <p class="tip-title">ZIP 包结构（SKILL.md 须在根目录或一级子目录）</p>
        <pre class="tip-tree">
skill-name.zip
├── SKILL.md
├── scripts/      可选：脚本
├── references/   可选：参考文档
└── assets/       可选：静态资源</pre
        >
        <p class="tip-title">SKILL.md 开头必填字段</p>
        <pre class="tip-tree">
---
name: my-skill
description: 技能描述（≤1024 字符）
---
（Markdown 技能指令正文）</pre
        >
        <p class="tip-note">
          name 须为 kebab-case（小写字母、数字、连字符）；单文件 ≤10MB、解压总量 ≤100MB
        </p>
      </div>
    </template>
    <slot />
  </el-tooltip>
</template>

<script setup lang="ts">
/** 上传技能按钮的 ZIP / SKILL.md 格式说明 tooltip（广场页头上传与详情页更新版本共用） */
</script>

<style>
/* 内容经 popper teleport 到 body，scoped 不生效，用全局类名收敛作用范围 */
/* EP effect=dark 的底色取 --el-text-color-primary（项目 dark 下为白）会成白底亮块——
   显式走 tooltip token：恒定深墨底骨白字，两主题一致 */
.skill-format-popper.el-popper {
  background: var(--color-tooltip-bg);
  border-color: var(--color-tooltip-bg);
  color: var(--color-tooltip-text);
}

.skill-format-popper .el-popper__arrow::before {
  background: var(--color-tooltip-bg);
  border-color: var(--color-tooltip-bg);
}

.skill-format-tip {
  max-width: 340px;
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
  color: var(--color-tooltip-text);
}

.skill-format-tip .tip-title {
  margin: 0 0 var(--space-1);
  font-weight: var(--weight-medium);
}

.skill-format-tip .tip-title + .tip-tree {
  margin-top: 0;
}

.skill-format-tip .tip-tree {
  margin: 0 0 var(--space-2);
  padding: var(--space-2) var(--space-3);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
  background: rgba(255, 255, 255, 0.12);
  border-radius: var(--radius-sm);
  white-space: pre;
  overflow-x: auto;
}

.skill-format-tip .tip-note {
  margin: 0;
  opacity: 0.75;
}
</style>
