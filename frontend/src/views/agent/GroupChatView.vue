<template>
  <div class="group-chat-view">
    <!-- 聊天区（群会话列表已收编布局侧栏单栏） -->
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
          <div class="header-actions">
            <button class="header-config" title="协作设置" @click="settingsVisible = true">
              <el-icon :size="14"><Setting /></el-icon>
            </button>
            <button class="header-dissolve" title="解散群聊" @click="handleDissolve">
              <el-icon :size="14"><Delete /></el-icon>
            </button>
          </div>
        </header>

        <!-- 时间线 -->
        <GroupTimeline ref="timelineRef" :entries="store.timeline" />

        <!-- run 进行中状态条（吸在输入区上方） -->
        <GroupRunStatus :speaker="store.currentSpeaker" @stop="store.stopRun()" />

        <!-- 输入区（与单聊共用 InputCard 精简模式：只读模式徽标 + 文本 + 发送/停止） -->
        <InputCard
          :streaming="store.running"
          :mode-badge="modeLabel"
          :placeholder="store.running ? '成员讨论中…' : '向群聊发送消息…'"
          @send="(p) => handleSend(p.content)"
          @stop="store.stopRun()"
        />
      </template>
    </div>
    <!-- 协作设置（后置配置：模式/主持人/轮数/名称/成员），编辑保存后刷新头部展示 -->
    <GroupFormDialog
      v-model="settingsVisible"
      :group-id="store.currentGroup?.id ?? null"
      @updated="refreshCurrentGroup"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 群聊主视图（/home/workspace/groups/:groupId）
 *
 * 对应路由 WorkspaceGroupChat：时间线 + run 状态条 + 输入区。一群多会话：
 * 会话切换即重放时间线（数据加载与 WS 生命周期收编在 agentGroup store，
 * 会话子列表在 WorkspaceLayout 侧栏），view 层只做路由参数接线与动作转发。
 * 输入区与单聊共用 InputCard 精简模式。
 */
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Setting } from '@element-plus/icons-vue'
import { useAgentGroupStore } from '@/stores/agentGroup'
import InputCard from '@/components/agent/chat/InputCard.vue'
import GroupAvatar from '@/components/agent/group/GroupAvatar.vue'
import GroupTimeline from '@/components/agent/group/GroupTimeline.vue'
import GroupRunStatus from '@/components/agent/group/GroupRunStatus.vue'
import GroupFormDialog from '@/components/agent/manage/GroupFormDialog.vue'
import { agentGroupApi } from '@/api/agentGroup'

const route = useRoute()
const router = useRouter()
const store = useAgentGroupStore()
const timelineRef = ref<InstanceType<typeof GroupTimeline>>()

// 布局层提供的会话中心刷新钩子（解散/改群后同步侧栏；测试环境或他处挂载时缺省为空）
const refreshSessionCenter = inject<(() => void) | null>('refreshSessionCenter', null)

const groupId = computed(() => Number(route.params.groupId))

const modeLabel = computed(() =>
  store.currentGroup?.mode === 'consult' ? '专家咨询' : '头脑风暴',
)
const memberNames = computed(() =>
  (store.currentGroup?.members || []).map((m) => m.agent_name),
)
const memberCount = computed(() => store.currentGroup?.member_count ?? 0)

async function init() {
  if (!groupId.value) return
  // 会话直达路由（/chat/:sessionId 判为群会话后转跳）以 query.sessionId 指定初始会话；
  // initForGroup 默认回放最新会话，目标即最新（或已不在会话列表，如刚被删除）时跳过
  const target = typeof route.query.sessionId === 'string' ? route.query.sessionId : ''
  await store.initForGroup(groupId.value)
  const targetExists = store.sessions.some((s) => s.session_id === target)
  if (target && store.currentSessionId !== target && targetExists) {
    await store.selectSession(target)
  }
}

async function handleSend(content: string) {
  await store.sendGroupMessage(content)
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
    // 后端解散群有意保留时间线会话，会话中心靠「群名查不到则跳过」过滤
    // 悬空条目——不刷新就会残留点不开的死条目
    refreshSessionCenter?.()
    // 群列表占位页已删，回对话入口
    router.push('/home/workspace/chat')
  } catch {
    // cancelled
  }
}

// 协作设置：编辑保存后重拉详情刷新头部（群名/模式/成员数即时反映）
const settingsVisible = ref(false)

async function refreshCurrentGroup() {
  if (!store.currentGroup) return
  try {
    store.currentGroup = await agentGroupApi.getGroup(store.currentGroup.id)
    // 群名/成员变化会改变会话中心条目的副标题与归属名，同步刷新
    refreshSessionCenter?.()
  } catch {
    // 拉取失败保持旧展示；错误 toast 由拦截器统一弹
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

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

/* 头部图标钮：中性底色，hover 反馈跟随语义——设置用中性色，解散才用危险色 */
.header-config,
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

.header-config:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
}

.header-dissolve:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}
</style>
