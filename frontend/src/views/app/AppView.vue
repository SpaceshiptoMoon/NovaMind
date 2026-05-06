<template>
  <div class="app-view">
    <div class="page-header">
      <h2>应用中心</h2>
      <el-button type="primary" @click="handleCreate">
        <el-icon><Plus /></el-icon>
        创建应用
      </el-button>
    </div>

    <el-empty description="应用功能开发中，敬请期待">
      <template #image>
        <el-icon :size="64" color="var(--color-text-faint)"><Grid /></el-icon>
      </template>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { Plus, Grid } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

function handleCreate() {
  ElMessage.info('应用创建功能开发中')
}
</script>

<style scoped>
.app-view {
  padding: 20px;
  max-width: 1100px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #F0EDEA;
}

.page-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #1A1A1A;
}
</style>
