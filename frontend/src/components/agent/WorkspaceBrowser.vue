<template>
  <div class="ws-browser">
    <div class="ws-browser-toolbar">
      <button
        class="ws-browser-up"
        :disabled="browseParent === null || browseLoading"
        title="上级目录"
        @click="browseParent && browseEnter(browseParent)"
      >
        <el-icon :size="12"><ArrowLeft /></el-icon>
      </button>
      <span class="ws-browser-path" :title="browsePath || '此电脑'">
        {{ browsePath || '此电脑' }}
      </span>
    </div>
    <div v-loading="browseLoading" class="ws-browser-list">
      <div v-for="d in browseDirs" :key="d.path" class="ws-browser-item" @click="browseEnter(d.path)">
        <el-icon :size="14"><FolderOpened /></el-icon>
        <span class="ws-browser-name">{{ d.name }}</span>
      </div>
      <div v-if="!browseLoading && browseDirs.length === 0" class="ws-browser-empty">
        此层级无子目录
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 本地目录浏览器（纯 UI 件）：逐层点选，当前浏览层即「选中目录」。
 *
 * 浏览状态（路径栈/子目录列表/加载态）内部自持，宿主（绑定弹窗 / 右面板目录视图）
 * 打开时调 resetTo(startPath) 定位起点，监听 change 拿当前层作为绑定目标。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, FolderOpened } from '@element-plus/icons-vue'
import { agentApi } from '@/api/agent'

const emit = defineEmits<{ (e: 'change', path: string): void }>()

// 浏览态：path 空=此电脑（盘符列表），当前层即绑定目标
const browsePath = ref('')
const browseParent = ref<string | null>(null)
const browseDirs = ref<{ name: string; path: string }[]>([])
const browseLoading = ref(false)

/** 进入某层目录（列表项点击/上级按钮）；空串=回到根 */
async function browseEnter(path: string) {
  browseLoading.value = true
  try {
    const data = await agentApi.browseWorkspaceDirs(path || undefined)
    browsePath.value = data.path
    browseParent.value = data.is_root ? null : (data.parent ?? null)
    browseDirs.value = data.dirs || []
    emit('change', data.path)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '目录读取失败')
  } finally {
    browseLoading.value = false
  }
}

/** 宿主打开时定位起点：已绑定目录或根（'' = 盘符列表） */
function resetTo(path: string) {
  browseEnter(path)
}

defineExpose({ resetTo })
</script>

<style scoped>
.ws-browser {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.ws-browser-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 10px;
  border-bottom: 1px solid var(--color-border-light);
  background: var(--color-bg-elevated);
}

.ws-browser-up {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.ws-browser-up:hover:not(:disabled) {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.ws-browser-up:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ws-browser-path {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--color-text-muted);
  direction: rtl; /* 长路径从左截断，保尾部可见 */
  text-align: left;
}

.ws-browser-list {
  max-height: 320px;
  overflow-y: auto;
  min-height: 120px;
}

.ws-browser-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 7px 12px;
  cursor: pointer;
  font-size: 13px;
  color: var(--color-text);
  transition: background var(--transition-fast);
}

.ws-browser-item:hover {
  background: var(--color-bg-hover);
}

.ws-browser-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ws-browser-empty {
  padding: 24px 0;
  text-align: center;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
