<template>
  <el-dialog
    :model-value="modelValue"
    title="选择工作目录"
    width="560px"
    :close-on-click-modal="false"
    append-to-body
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div class="ws-dialog-body">
      <p class="ws-dialog-hint">
        进入工作模式后，智能体将以该文件夹为工作目录，自动获得 read / glob / grep / write / edit /
        bash 六个工具，可读写文件、检索内容、运行命令。
      </p>
      <WorkspaceBrowser ref="browserRef" @change="selectedPath = $event" />
      <div class="ws-selected-row">
        <span class="ws-selected-label">已选目录：</span>
        <code class="ws-selected-path">{{ selectedPath || '（请选择）' }}</code>
      </div>
      <div v-if="isWorkspaceBound" class="ws-dialog-current">
        当前绑定：<code :title="workspaceRoot">{{ workspaceRoot }}</code>
      </div>
    </div>
    <template #footer>
      <el-button
        v-if="isWorkspaceBound"
        type="danger"
        plain
        :loading="binding"
        @click="handleUnbind"
      >
        退出工作模式
      </el-button>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button
        type="primary"
        :loading="binding"
        :disabled="!selectedPath"
        @click="handleBind"
      >
        进入工作模式
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * 工作目录绑定弹窗（唯一实现）：目录浏览器 + 绑定/解绑动作。
 *
 * 绑定动作收口在 useWorkspaceBinding（与右面板目录视图共用），
 * 本组件只负责弹窗壳与「选定即绑定」的接线；浏览起点=已绑定目录或根。
 */
import { ref, watch } from 'vue'
import WorkspaceBrowser from './WorkspaceBrowser.vue'
import { useWorkspaceBinding } from '@/composables/useWorkspaceBinding'

const modelValue = defineModel<boolean>({ required: true })
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const browserRef = ref<InstanceType<typeof WorkspaceBrowser>>()
const selectedPath = ref('')

const { isWorkspaceBound, workspaceRoot, binding, bindWorkspace, unbindWorkspace } =
  useWorkspaceBinding()

// 打开即从已绑定目录（或根）开始浏览
watch(modelValue, (visible) => {
  if (visible) {
    selectedPath.value = ''
    browserRef.value?.resetTo(workspaceRoot.value)
  }
})

async function handleBind() {
  if (await bindWorkspace(selectedPath.value)) {
    modelValue.value = false
  }
}

async function handleUnbind() {
  if (await unbindWorkspace()) {
    modelValue.value = false
  }
}
</script>

<style scoped>
.ws-dialog-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ws-dialog-hint {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-muted);
  line-height: 1.6;
}

.ws-selected-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}

.ws-selected-label {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.ws-selected-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-muted, rgba(0, 0, 0, 0.04));
  font-size: 12px;
}

.ws-dialog-current {
  font-size: 12px;
  color: var(--color-text-muted);
}

.ws-dialog-current code {
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-muted, rgba(0, 0, 0, 0.04));
  font-size: 12px;
}
</style>
