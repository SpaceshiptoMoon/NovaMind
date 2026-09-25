<template>
  <el-dialog
    v-model="visible"
    title="加入评测集"
    width="560px"
    destroy-on-close
    @closed="reset"
  >
    <el-form label-position="top">
      <el-form-item label="问题（question）">
        <el-input
          v-model="question"
          type="textarea"
          :rows="2"
          maxlength="2000"
          show-word-limit
          placeholder="测试问题"
        />
      </el-form-item>
      <el-form-item label="期望答案（expected_answer）">
        <el-input
          v-model="expectedAnswer"
          type="textarea"
          :rows="4"
          maxlength="10000"
          show-word-limit
          placeholder="期望的标准答案（可基于当前 AI 回答编辑）"
        />
      </el-form-item>
      <el-form-item label="目标知识库">
        <el-select
          v-model="kbId"
          placeholder="选择知识库"
          style="width: 100%"
          @change="onKbChange"
        >
          <el-option
            v-for="kb in kbOptions"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="加入方式">
        <el-radio-group v-model="mode">
          <el-radio value="new">新建测试集</el-radio>
          <el-radio value="append" :disabled="!testSets.length">追加到已有</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="mode === 'new'" label="测试集名称">
        <el-input v-model="name" maxlength="200" placeholder="如：知识库回归测试 v1" />
      </el-form-item>
      <el-form-item v-else label="选择测试集">
        <el-select v-model="targetTestSetId" style="width: 100%">
          <el-option
            v-for="ts in testSets"
            :key="ts.id"
            :label="`${ts.name}（${ts.total_cases} 题）`"
            :value="ts.id"
          />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确认加入</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * QA 消息 → 评测集桥接弹窗（批次 3a）。
 * 预填 question/AI 回答（可编辑），选知识库后可新建测试集或追加已有集；
 * 成功后可跳转 KbEvaluationView 查看预览/跑测评。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { evaluationApi, knowledgeBaseApi } from '@/api/knowledge'
import type { TestSet } from '@/api/types'

const props = defineProps<{
  spaceId: number
}>()

const router = useRouter()

const visible = ref(false)
const submitting = ref(false)
const question = ref('')
const expectedAnswer = ref('')
const kbId = ref<number | undefined>(undefined)
const mode = ref<'new' | 'append'>('new')
const name = ref('')
const targetTestSetId = ref<number | undefined>(undefined)
const kbOptions = ref<Array<{ id: number; name: string }>>([])
const testSets = ref<TestSet[]>([])

async function open(payload: { question: string; answer: string }) {
  question.value = payload.question
  expectedAnswer.value = payload.answer
  visible.value = true
  reset2()
  try {
    const data = await knowledgeBaseApi.getKnowledgeBases(props.spaceId)
    kbOptions.value = (data.items ?? []).map((k) => ({ id: k.id, name: k.name }))
  } catch {
    kbOptions.value = []
  }
}

function reset2() {
  kbId.value = undefined
  mode.value = 'new'
  name.value = ''
  targetTestSetId.value = undefined
  testSets.value = []
}

function reset() {
  question.value = ''
  expectedAnswer.value = ''
  reset2()
}

async function onKbChange() {
  testSets.value = []
  targetTestSetId.value = undefined
  if (!kbId.value) return
  try {
    const data = await evaluationApi.getTestSets(props.spaceId, kbId.value, { limit: 100 })
    testSets.value = (data.items ?? []) as unknown as TestSet[]
    if (!testSets.value.length) mode.value = 'new'
  } catch {
    testSets.value = []
  }
}

async function submit() {
  if (!question.value.trim() || !expectedAnswer.value.trim()) {
    ElMessage.warning('问题与期望答案均不能为空')
    return
  }
  if (!kbId.value) {
    ElMessage.warning('请选择目标知识库')
    return
  }
  if (mode.value === 'new' && !name.value.trim()) {
    ElMessage.warning('请填写测试集名称')
    return
  }
  if (mode.value === 'append' && !targetTestSetId.value) {
    ElMessage.warning('请选择要追加的测试集')
    return
  }

  submitting.value = true
  try {
    const payload = {
      question: question.value.trim(),
      expected_answer: expectedAnswer.value.trim(),
    }
    if (mode.value === 'new') {
      await evaluationApi.createTestSetFromCases(props.spaceId, kbId.value, {
        name: name.value.trim(),
        cases: [payload],
      })
      ElMessage.success('已创建测试集')
    } else {
      await evaluationApi.appendCasesToTestSet(
        props.spaceId, kbId.value, targetTestSetId.value!, { cases: [payload] },
      )
      ElMessage.success('用例已追加')
    }
    visible.value = false
    // 跳到该 KB 的评测页（用户可继续添加或直接跑测评）
    void router.push(`/home/spaces/${props.spaceId}/knowledge-bases/${kbId.value}/evaluation`)
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { message?: string } } })?.response?.data?.message
    ElMessage.error(detail || '加入评测集失败')
  } finally {
    submitting.value = false
  }
}

defineExpose({ open })
</script>
