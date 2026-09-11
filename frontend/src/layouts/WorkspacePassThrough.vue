<script setup lang="ts">
// 工作台路由透传层：WorkspaceLayout 已提升为 /home 顶层布局（侧栏 + 顶栏全站常驻），
// 本组件仅承载 /home/workspace 的 children 嵌套与 redirect，无任何结构。
</script>

<template>
  <router-view />
</template>
