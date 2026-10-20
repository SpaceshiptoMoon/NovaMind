<template>
  <div class="group-chat-view">
    <!-- 左侧：群会话列表（一群多会话，与单聊会话栏同款交互） -->
    <aside class="session-sidebar">
      <div class="sidebar-top">
        <button class="new-session-btn" @click="handleNewSession">
          <el-icon :size="16"><Plus /></el-icon>
          <span>新会话</span>
        </button>
      </div>
      <div class="session-list">
        <div
          v-for="(conv, idx) in store.sessions"
          :key="conv.session_id"
          class="conv-item"
          :class="{ active: store.currentSessionId === conv.session_id }"
          @click="handleSelectSession(conv.session_id)"
        >
          <span class="conv-title">{{ sessionTitle(conv, idx) }}</span>
          <button
            class="conv-delete"
            title="删除会话"
            @click.stop="handleDeleteSession(conv.session_id)"
          >
            <el-icon :size="12"><Delete /></el-icon>
          </button>
        </div>
        <div
          v-if="store.sessions.length === 0 && !store.sessionsLoading"
          class="sidebar-empty"
        >
          <span>暂无会话</span>
        </div>
      </div>
    </aside>

    <!-- 右侧：聊天区 -->
    <div class="chat-main">
      <!-- 加载/错误态 -->
      <div v-if="store.error && !store.currentGroup" class="group-state">
        <p class="state-text">{{ store.error }}</p>
        <button class="state-btn" @click="init">重试</button>
      </div>

      <template v-else-if="store.currentGroup">
        <!-- 浮动头部：群头像 + 群名 + 模式 -->
        <header class="chat-header">
          <div class="header-left">
            <GroupAvatar :members="memberNames" :title="store.currentGroup.name" />
            <div class="header-info">
              <span class="header-title">{{ store.currentGroup.name }}</span>
              <span class="header-sub">{{ modeLabel }} · {{ memberCount }} 位成员</span>
            </div>
          </div>
          <button
            class="header-dissolve"
            title="解散群聊"
            @click="handleDissolve"
          >
            <el-icon :size="14"><Delete /></el-icon>
          </button>
        </header>

        <!-- 时间线 -->
        <GroupTimeline ref="timelineRef" :entries="store.timeline" />

        <!-- run 进行中状态条（吸在输入区上方） -->
        <GroupRunStatus :speaker="store.currentSpeaker" @stop="store.stopRun()" />

        <!-- 输入区 -->
        <GroupComposer
          :running="store.running"
          :mode="store.currentGroup.mode"
          @send="handleSend"
          @stop="store.stopRun()"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 群聊主视图（/home/workspace/groups/:groupId）
 *
 * 对应路由 WorkspaceGroupChat：左侧群会话列表 + 右侧时间线/run 状态条/输入区。
 * 一群多会话：会话切换即重放时间线（数据加载与 WS 生命周期收编在
 * agentGroup store），view 层只做路由参数接线与动作转发。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { formatDate } from '@/utils/format'
import type { GroupSession } from '@/api/types'
import GroupAvatar from '@/components/agent/group/GroupAvatar.vue'
import GroupTimeline from '@/components/agent/group/GroupTimeline.vue'
import GroupRunStatus from '@/components/agent/group/GroupRunStatus.vue'
import GroupComposer from '@/components/agent/group/GroupComposer.vue'

const route = useRoute()
const router = useRouter()
const store = useAgentGroupStore()
const timelineRef = ref<InstanceType<typeof GroupTimeline>>()

const groupId = computed(() => Number(route.params.groupId))

const modeLabel = computed(() =>
  store.currentGroup?.mode === 'consult' ? '专家咨询' : '头脑风暴',
)
const memberNames = computed(() =>
  (store.currentGroup?.members || []).map((m) => m.agent_name),
)
const memberCount = computed(() => store.currentGroup?.member_count ?? 0)

// 会话标题：列表按时间倒序，用创建时间区分（后端暂无首条消息摘要）
function sessionTitle(conv: GroupSession, idx: number): string {
  const created = conv.created_at ? formatDate(conv.created_at) : ''
  return created || `会话 ${store.sessions.length - idx}`
}

function init() {
  if (groupId.value) store.initForGroup(groupId.value)
}

async function handleSend(content: string) {
  await store.sendGroupMessage(content)
}

async function handleSelectSession(sessionId: string) {
  if (sessionId !== store.currentSessionId) await store.selectSession(sessionId)
}

async function handleNewSession() {
  try {
    await store.newSession()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '新建会话失败')
  }
}

async function handleDeleteSession(sessionId: string) {
  try {
    await ElMessageBox.confirm('删除后该会话的时间线与成员讨论上下文将一并清除，确定删除？', '删除会话', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await store.deleteSession(sessionId)
  } catch (e) {
    if (e instanceof Error) ElMessage.error(e.message)
    // 取消则静默
  }
}

async function handleDissolve() {
  const group = store.currentGroup
  if (!group) return
  try {
    await ElMessageBox.confirm(`确定解散群聊 "${group.name}" 吗？`, '解散群聊', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await store.deleteGroup(group.id)
    ElMessage.success('群已解散')
    router.push({ name: 'WorkspaceGroups' })
  } catch {
    // cancelled
  }
}

onMounted(init)
watch(groupId, (v, old) => {
  if (v && v !== old) init()
})
</script>

<style scoped>
.group-chat-view {
  position: absolute;
  inset: 0;
  display: flex;
  overflow: hidden;
  background: var(--color-bg-elevated);
  z-index: 1;
}

/* 会话侧栏（单聊 chat-sidebar 同款制度） */
.session-sidebar {
  width: 220px;
  border-right: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: var(--color-bg-sidebar);
}

.sidebar-top {
  padding: var(--space-3);
  border-bottom: 1px solid var(--color-border-light);
}

.new-session-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  color: var(--color-text);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition: all var(--transition-base);
}

.new-session-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
  min-height: 0;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  margin-bottom: 2px;
  position: relative;
}

.conv-item:hover {
  background: var(--color-bg-hover);
}

.conv-item.active {
  background: var(--color-bg-hover);
}

.conv-item.active .conv-title {
  color: var(--color-text);
  font-weight: var(--weight-medium);
}

.conv-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 2px;
  background: var(--color-text);
}

.conv-title {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: var(--leading-normal);
}

.conv-delete {
  opacity: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.conv-item:hover .conv-delete {
  opacity: 1;
}

.conv-delete:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.sidebar-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-faint);
}

/* 聊天主区：纵向 flex 链（时间线 flex:1 滚动，状态条/输入区固定） */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  min-width: 0;
  overflow: hidden;
}

.group-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
}

.state-text {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin: 0;
}

.state-btn {
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  color: var(--color-text);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
}

.state-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* 浮动头部（单聊同款制度）：48px，blur 底 */
.chat-header {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  z-index: 3;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-5);
  background: var(--color-bg-header);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: var(--shadow-xs);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.header-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.header-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-sub {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-dissolve {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.header-dissolve:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

/* 窄屏降级：会话栏改绝对定位悬浮（单聊同款断点制度） */
@media (max-width: 768px) {
  .session-sidebar {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 4;
    box-shadow: var(--shadow-lg);
  }
}
</style>
