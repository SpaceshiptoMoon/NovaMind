<template>
  <div class="kb-evaluation-view">
    <!-- 页面导航 -->
    <div class="page-nav">
      <div class="nav-tabs">
        <router-link
          :to="`/home/spaces/${spaceId}/knowledge-bases/${kbId}/documents`"
          class="nav-tab"
        >
          文档管理
        </router-link>
        <router-link
          :to="`/home/spaces/${spaceId}/search?kbId=${kbId}`"
          class="nav-tab"
        >
          检索
        </router-link>
        <router-link
          :to="`/home/spaces/${spaceId}/knowledge-bases/${kbId}/evaluation`"
          class="nav-tab active"
        >
          评测
        </router-link>
      </div>
      <BreadcrumbNav />
    </div>

    <!-- Tab 切换 -->
    <el-tabs v-model="activeTab" class="eval-tabs">
      <!-- ============ 测试集管理 ============ -->
      <el-tab-pane label="测试集" name="test-sets">
        <div class="tab-toolbar">
          <el-button type="primary" @click="showUploadDialog">
            <el-icon><Upload /></el-icon>
            上传测试集
          </el-button>
        </div>

        <el-table :data="testSets" v-loading="tsLoading" stripe>
          <el-table-column prop="name" label="名称" min-width="160" />
          <el-table-column prop="filename" label="文件名" min-width="140" />
          <el-table-column prop="file_type" label="类型" width="80" align="center">
            <template #default="{ row }">
              <el-tag size="small">{{ row.file_type.toUpperCase() }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="total_cases" label="用例数" width="90" align="center" />
          <el-table-column prop="created_at" label="创建时间" width="160">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="showCreateTaskDialog(row)">
                开始测评
              </el-button>
              <el-button link size="small" @click="handlePreviewTestSet(row)">
                预览
              </el-button>
              <el-button link size="small" @click="handleRenameTestSet(row)">
                重命名
              </el-button>
              <el-button type="danger" link size="small" @click="handleDeleteTestSet(row)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============ 测评任务 ============ -->
      <el-tab-pane label="测评任务" name="tasks">
        <el-table :data="tasks" v-loading="taskLoading" stripe>
          <el-table-column prop="name" label="任务名称" min-width="160" />
          <el-table-column prop="test_set_id" label="测试集ID" width="100" align="center" />
          <el-table-column prop="status" label="状态" width="140" align="center">
            <template #default="{ row }">
              <el-tag :type="taskStatusMap[row.status]?.type || 'info'" size="small">
                {{ taskStatusMap[row.status]?.text || '未知' }}
              </el-tag>
              <template v-if="taskProgress[row.id] && (row.status === 'running' || row.status === 'pending')">
                <div class="progress-mini">
                  <el-progress :percentage="getProgressPercent(row.id)" :stroke-width="4" />
                </div>
              </template>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" width="160">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="viewReport(row)">
                查看报告
              </el-button>
              <el-button v-if="row.status === 'completed'" type="success" link size="small" @click="handleExport(row, 'csv')">
                导出CSV
              </el-button>
              <el-button v-if="row.status === 'pending' || row.status === 'running'" type="warning" link size="small" @click="handleCancelTask(row)">
                取消
              </el-button>
              <el-button v-if="row.status !== 'pending' && row.status !== 'running'" type="danger" link size="small" @click="handleDeleteTask(row)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- ============ 上传测试集弹窗 ============ -->
    <el-dialog v-model="uploadDialogVisible" title="上传测试集" width="480px" destroy-on-close>
      <el-form ref="uploadFormRef" :model="uploadForm" :rules="uploadRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="uploadForm.name" placeholder="请输入测试集名称" maxlength="100" />
        </el-form-item>
        <el-form-item label="文件" prop="file">
          <el-upload
            :auto-upload="false"
            :limit="1"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            accept=".json,.csv"
          >
            <el-button>选择文件</el-button>
            <template #tip>
              <div class="el-upload__tip">支持 JSON / CSV 格式</div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploadLoading" @click="handleUpload">上传</el-button>
      </template>
    </el-dialog>

    <!-- ============ 测试集预览弹窗 ============ -->
    <el-dialog v-model="previewDialogVisible" title="测试集用例预览" width="700px" destroy-on-close>
      <div v-if="previewLoading" style="text-align: center; padding: 40px">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      </div>
      <div v-else-if="previewCases.length">
        <p class="preview-meta">共 {{ previewCases.length }} 条用例</p>
        <el-collapse>
          <el-collapse-item
            v-for="(tc, idx) in previewCases"
            :key="idx"
            :name="idx"
          >
            <template #title>
              <span class="preview-case-title">{{ idx + 1 }}. {{ tc.question }}</span>
            </template>
            <div class="preview-case-body">
              <div class="preview-case-field">
                <span class="preview-case-label">期望答案</span>
                <div class="preview-case-value">{{ tc.expected_answer }}</div>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
      <el-empty v-else description="暂无用例数据" />
    </el-dialog>

    <!-- ============ 创建测评任务弹窗 ============ -->
    <el-dialog v-model="createTaskDialogVisible" title="创建测评任务" width="680px" destroy-on-close>
      <el-form ref="taskFormRef" :model="taskForm" :rules="taskRules" label-width="90px">
        <el-form-item label="任务名称" prop="name">
          <el-input v-model="taskForm.name" placeholder="请输入任务名称" maxlength="200" />
        </el-form-item>
        <el-form-item label="测试集">
          <span>{{ selectedTestSet?.name }} ({{ selectedTestSet?.total_cases }} 条用例)</span>
        </el-form-item>

        <el-divider content-position="left">模型与检索</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="LLM 模型">
              <el-select v-model="taskForm.llm_model" placeholder="系统默认" clearable style="width: 100%">
                <el-option v-for="m in availableLlmModels" :key="m" :label="m" :value="m" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="Embedding">
              <el-select v-model="taskForm.embedding_model" placeholder="系统默认" clearable style="width: 100%">
                <el-option v-for="m in availableEmbeddingModels" :key="m" :label="m" :value="m" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="检索模式">
              <el-input v-model="taskForm.search_mode" placeholder="content_hybrid" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="Top K">
              <el-input-number v-model="taskForm.top_k" :min="1" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="分数阈值">
              <el-input-number v-model="taskForm.score_threshold" :min="0" :max="1" :step="0.1" :precision="1" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">评估策略</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="正确性">
              <el-select v-model="taskForm.correctness_strategy" style="width: 100%">
                <el-option label="LLM 打分" value="llm" />
                <el-option label="Embedding 相似度" value="embedding" />
                <el-option label="混合策略" value="hybrid" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="忠实度">
              <el-select v-model="taskForm.faithfulness_strategy" style="width: 100%">
                <el-option label="Claim 拆解法" value="decompose" />
                <el-option label="LLM 打分" value="llm" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="相关性">
              <el-select v-model="taskForm.relevance_strategy" style="width: 100%">
                <el-option label="反向问题法" value="reverse_question" />
                <el-option label="LLM 打分" value="llm" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="检索判断">
              <el-select v-model="taskForm.retrieval_relevance_strategy" style="width: 100%">
                <el-option label="LLM 判断" value="llm" />
                <el-option label="Embedding 相似度" value="embedding" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">启用的指标</el-divider>
        <div class="switch-group">
          <label class="switch-group-label">基础</label>
          <el-checkbox v-model="taskForm.enable_generation">生成评估</el-checkbox>
          <el-checkbox v-model="taskForm.enable_mrr">MRR</el-checkbox>
          <el-checkbox v-model="taskForm.enable_recall_at_k">Recall@K</el-checkbox>
        </div>
        <div class="switch-group">
          <label class="switch-group-label">端到端</label>
          <el-checkbox v-model="taskForm.enable_context_precision">Context Precision</el-checkbox>
          <el-checkbox v-model="taskForm.enable_context_recall">Context Recall</el-checkbox>
          <el-checkbox v-model="taskForm.enable_answer_similarity">Answer Similarity</el-checkbox>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="createTaskDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="createTaskLoading" @click="handleCreateTask">
          创建并执行
        </el-button>
      </template>
    </el-dialog>

    <!-- ============ 测评报告弹窗 ============ -->
    <el-dialog
      v-model="reportDialogVisible"
      :title="`测评报告 - ${reportData?.name || ''}`"
      width="900px"
      top="4vh"
      destroy-on-close
    >
      <div v-if="reportLoading" style="text-align: center; padding: 40px">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <p style="margin-top: 12px; color: #8C8C8C">加载报告中...</p>
      </div>

      <div v-else-if="reportData">
        <!-- 任务未完成 -->
        <el-alert
          v-if="reportData.status === 'pending' || reportData.status === 'running'"
          type="warning"
          :closable="false"
          show-icon
          title="任务执行中，请稍后刷新查看"
        />

        <!-- 任务已取消 -->
        <el-alert
          v-else-if="reportData.status === 'cancelled'"
          type="info"
          :closable="false"
          show-icon
          title="任务已取消"
        />

        <!-- 任务失败 -->
        <el-alert
          v-else-if="reportData.status === 'failed'"
          type="error"
          :closable="false"
          show-icon
          title="任务执行失败"
        />

        <!-- 任务完成 -->
        <template v-else-if="reportData.status === 'completed'">
          <!-- 汇总卡片 -->
          <div class="report-summary">
            <div class="summary-header">
              <span class="summary-title">汇总指标</span>
              <span class="summary-meta">
                {{ reportData.completed_cases }}/{{ reportData.total_cases }} 用例
                <template v-if="reportData.summary?.elapsed_seconds">
                  · 耗时 {{ reportData.summary.elapsed_seconds.toFixed(1) }}s
                </template>
              </span>
            </div>

            <div class="score-grid">
              <!-- 检索 -->
              <div v-if="reportData.summary?.retrieval" class="score-section">
                <h4>检索阶段</h4>
                <div class="score-items">
                  <div v-if="reportData.summary.retrieval.precision_at_k != null" class="score-item">
                    <span class="score-label">Precision@K</span>
                    <span class="score-value">{{ (reportData.summary.retrieval.precision_at_k * 100).toFixed(1) }}%</span>
                  </div>
                  <div v-if="reportData.summary.retrieval.hit_rate != null" class="score-item">
                    <span class="score-label">Hit Rate</span>
                    <span class="score-value">{{ (reportData.summary.retrieval.hit_rate * 100).toFixed(1) }}%</span>
                  </div>
                  <div v-if="reportData.summary.retrieval.mrr != null" class="score-item">
                    <span class="score-label">MRR</span>
                    <span class="score-value">{{ reportData.summary.retrieval.mrr.toFixed(3) }}</span>
                  </div>
                  <div v-if="reportData.summary.retrieval.recall_at_k != null" class="score-item">
                    <span class="score-label">Recall@K</span>
                    <span class="score-value">{{ (reportData.summary.retrieval.recall_at_k * 100).toFixed(1) }}%</span>
                  </div>
                </div>
              </div>

              <!-- 生成 -->
              <div v-if="reportData.summary?.generation" class="score-section">
                <h4>生成阶段</h4>
                <div class="score-items">
                  <div v-if="reportData.summary.generation.correctness != null" class="score-item">
                    <span class="score-label">正确性</span>
                    <span class="score-value" :class="getScoreClass(reportData.summary.generation.correctness)">
                      {{ reportData.summary.generation.correctness.toFixed(1) }}
                    </span>
                  </div>
                  <div v-if="reportData.summary.generation.faithfulness != null" class="score-item">
                    <span class="score-label">忠实度</span>
                    <span class="score-value" :class="getScoreClass(reportData.summary.generation.faithfulness)">
                      {{ reportData.summary.generation.faithfulness.toFixed(1) }}
                    </span>
                  </div>
                  <div v-if="reportData.summary.generation.answer_relevance != null" class="score-item">
                    <span class="score-label">相关性</span>
                    <span class="score-value" :class="getScoreClass(reportData.summary.generation.answer_relevance)">
                      {{ reportData.summary.generation.answer_relevance.toFixed(1) }}
                    </span>
                  </div>
                  <div v-if="reportData.summary.generation.quality != null" class="score-item">
                    <span class="score-label">质量</span>
                    <span class="score-value" :class="getScoreClass(reportData.summary.generation.quality)">
                      {{ reportData.summary.generation.quality.toFixed(1) }}
                    </span>
                  </div>
                  <div v-if="reportData.summary.generation.overall != null" class="score-item score-item-highlight">
                    <span class="score-label">综合</span>
                    <span class="score-value" :class="getScoreClass(reportData.summary.generation.overall)">
                      {{ reportData.summary.generation.overall.toFixed(1) }}
                    </span>
                  </div>
                </div>
              </div>

              <!-- 端到端 -->
              <div v-if="reportData.summary?.end_to_end" class="score-section">
                <h4>端到端</h4>
                <div class="score-items">
                  <div v-if="reportData.summary.end_to_end.context_precision != null" class="score-item">
                    <span class="score-label">Context Precision</span>
                    <span class="score-value">{{ (reportData.summary.end_to_end.context_precision * 100).toFixed(1) }}%</span>
                  </div>
                  <div v-if="reportData.summary.end_to_end.context_recall != null" class="score-item">
                    <span class="score-label">Context Recall</span>
                    <span class="score-value">{{ (reportData.summary.end_to_end.context_recall * 100).toFixed(1) }}%</span>
                  </div>
                  <div v-if="reportData.summary.end_to_end.answer_similarity != null" class="score-item">
                    <span class="score-label">Answer Similarity</span>
                    <span class="score-value">{{ (reportData.summary.end_to_end.answer_similarity * 100).toFixed(1) }}%</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 逐条详情 -->
          <div class="report-details">
            <div class="details-header">
              <span class="details-title">逐条详情</span>
              <el-button size="small" @click="handleExport({ id: reportData.task_id } as EvaluationTask, 'csv')">
                <el-icon><Download /></el-icon>
                导出CSV
              </el-button>
            </div>

            <el-collapse>
              <el-collapse-item
                v-for="detail in reportData.details"
                :key="detail.index"
                :name="detail.index"
              >
                <template #title>
                  <div class="detail-title">
                    <span class="detail-index">{{ detail.index + 1 }}.</span>
                    <span class="detail-question">{{ detail.question }}</span>
                    <div class="detail-scores-inline">
                      <el-tag v-if="detail.generation_scores?.correctness != null" size="small" :type="getScoreTagType(detail.generation_scores.correctness)">
                        正确: {{ detail.generation_scores.correctness }}
                      </el-tag>
                      <el-tag v-if="detail.human_score != null" size="small" type="success">
                        人工: {{ detail.human_score }}
                      </el-tag>
                    </div>
                  </div>
                </template>

                <div class="detail-body">
                  <!-- 召回结果 -->
                  <div v-if="detail.retrieved_chunks?.length" class="recall-block">
                    <span class="recall-label">召回结果 ({{ detail.retrieved_chunks.length }} 条)</span>
                    <div
                      v-for="(chunk, ci) in detail.retrieved_chunks"
                      :key="chunk.chunk_id || ci"
                      class="recall-chunk"
                    >
                      <div class="recall-chunk-header">
                        <span class="recall-chunk-id">{{ chunk.chunk_id }}</span>
                        <el-tag v-if="chunk.score != null" size="small" type="info">
                          Score: {{ chunk.score.toFixed(4) }}
                        </el-tag>
                      </div>
                      <div class="recall-chunk-content">{{ chunk.content }}</div>
                    </div>
                  </div>

                  <el-row :gutter="16">
                    <el-col :span="12">
                      <div class="answer-block">
                        <span class="answer-label">期望答案</span>
                        <div class="answer-text expected">{{ detail.expected_answer }}</div>
                      </div>
                    </el-col>
                    <el-col :span="12">
                      <div class="answer-block">
                        <span class="answer-label">生成答案</span>
                        <div class="answer-text generated">{{ detail.generated_answer || '未生成' }}</div>
                      </div>
                    </el-col>
                  </el-row>

                  <!-- 分数详情 -->
                  <div v-if="detail.generation_scores || detail.retrieval || detail.end_to_end" class="detail-scores">
                    <el-descriptions :column="4" size="small" border>
                      <el-descriptions-item v-if="detail.retrieval?.precision_at_k != null" label="Precision@K">
                        {{ (detail.retrieval.precision_at_k * 100).toFixed(1) }}%
                      </el-descriptions-item>
                      <el-descriptions-item v-if="detail.generation_scores?.faithfulness != null" label="忠实度">
                        {{ detail.generation_scores.faithfulness }}
                      </el-descriptions-item>
                      <el-descriptions-item v-if="detail.generation_scores?.answer_relevance != null" label="相关性">
                        {{ detail.generation_scores.answer_relevance }}
                      </el-descriptions-item>
                      <el-descriptions-item v-if="detail.generation_scores?.correctness != null" label="正确性">
                        {{ detail.generation_scores.correctness }}
                      </el-descriptions-item>
                      <el-descriptions-item v-if="detail.generation_scores?.quality != null" label="质量">
                        {{ detail.generation_scores.quality }}
                      </el-descriptions-item>
                      <el-descriptions-item v-if="detail.end_to_end?.context_precision != null" label="Ctx Precision">
                        {{ (detail.end_to_end.context_precision * 100).toFixed(1) }}%
                      </el-descriptions-item>
                      <el-descriptions-item v-if="detail.end_to_end?.context_recall != null" label="Ctx Recall">
                        {{ (detail.end_to_end.context_recall * 100).toFixed(1) }}%
                      </el-descriptions-item>
                      <el-descriptions-item v-if="detail.end_to_end?.answer_similarity != null" label="Ans Similarity">
                        {{ (detail.end_to_end.answer_similarity * 100).toFixed(1) }}%
                      </el-descriptions-item>
                    </el-descriptions>
                  </div>

                  <!-- 人工评分 -->
                  <div class="human-score-row">
                    <span class="human-score-label">人工评分:</span>
                    <el-rate
                      v-model="humanScores[detail.index]!.score"
                      :max="10"
                      show-score
                      :score-template="'{value}'"
                    />
                    <el-input
                      v-model="humanScores[detail.index]!.comment"
                      placeholder="评语（可选）"
                      size="small"
                      style="width: 200px; margin-left: 12px"
                    />
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>

            <!-- 提交人工评分 -->
            <div class="submit-scores-bar">
              <el-button type="primary" :loading="scoreLoading" @click="handleSubmitScores">
                提交人工评分
              </el-button>
            </div>
          </div>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Download, Loading } from '@element-plus/icons-vue'
import BreadcrumbNav from '@/components/common/BreadcrumbNav.vue'
import { evaluationApi } from '@/api/evaluation'
import { userApi } from '@/api/user'
import type {
  TestSet,
  TestSetCasesResponse,
  EvaluationTask,
  EvaluationReport,
  EvaluationDetail,
  HumanScoreItem,
} from '@/api/types'
import type { FormInstance, FormRules, UploadFile } from 'element-plus'

const route = useRoute()
const router = useRouter()
const spaceId = computed(() => Number(route.params.id))

const kbId = computed(() => {
  if (route.params.kbId) return Number(route.params.kbId)
  if (route.query.kbId) return Number(route.query.kbId)
  return 0
})

const activeTab = ref('test-sets')

// ===================== 状态映射 =====================

const taskStatusMap: Record<string, { text: string; type: string }> = {
  pending: { text: '待执行', type: 'warning' },
  running: { text: '执行中', type: '' },
  completed: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  deleted: { text: '已删除', type: 'info' },
  cancelled: { text: '已取消', type: 'info' },
}

// ===================== 测试集 =====================

const tsLoading = ref(false)
const testSets = ref<TestSet[]>([])

async function fetchTestSets() {
  tsLoading.value = true
  try {
    const data = await evaluationApi.getTestSets(spaceId.value, kbId.value)
    testSets.value = data.items || []
  } catch {
    // handled by interceptor
  } finally {
    tsLoading.value = false
  }
}

// 上传测试集
const uploadDialogVisible = ref(false)
const uploadLoading = ref(false)
const uploadFormRef = ref<FormInstance>()
const selectedFile = ref<File | null>(null)
const uploadForm = reactive({ name: '', file: '' as string })
const uploadRules: FormRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  file: [{ required: true, message: '请选择文件', trigger: 'change' }],
}

function showUploadDialog() {
  uploadForm.name = ''
  uploadForm.file = ''
  selectedFile.value = null
  uploadDialogVisible.value = true
}

function handleFileChange(file: UploadFile) {
  if (file.raw) {
    selectedFile.value = file.raw
    uploadForm.file = file.name
  }
}

function handleFileRemove() {
  selectedFile.value = null
  uploadForm.file = ''
}

async function handleUpload() {
  if (!uploadFormRef.value || !selectedFile.value) return

  await uploadFormRef.value.validate(async (valid) => {
    if (!valid) return

    uploadLoading.value = true
    try {
      await evaluationApi.uploadTestSet(spaceId.value, kbId.value, selectedFile.value!, uploadForm.name)
      ElMessage.success('测试集上传成功')
      uploadDialogVisible.value = false
      fetchTestSets()
    } catch {
      // handled by interceptor
    } finally {
      uploadLoading.value = false
    }
  })
}

async function handleDeleteTestSet(ts: TestSet) {
  try {
    await ElMessageBox.confirm(`确定删除测试集 "${ts.name}" 吗？`, '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await evaluationApi.deleteTestSet(spaceId.value, kbId.value, ts.id)
    ElMessage.success('已删除')
    fetchTestSets()
  } catch {
    // cancelled
  }
}

// 预览测试集
const previewDialogVisible = ref(false)
const previewLoading = ref(false)
const previewCases = ref<TestSetCasesResponse['test_cases']>([])

async function handlePreviewTestSet(ts: TestSet) {
  previewDialogVisible.value = true
  previewLoading.value = true
  previewCases.value = []
  try {
    const data = await evaluationApi.getTestSetCases(spaceId.value, kbId.value, ts.id)
    previewCases.value = data.test_cases || []
  } catch {
    // handled by interceptor
  } finally {
    previewLoading.value = false
  }
}

// 重命名测试集
async function handleRenameTestSet(ts: TestSet) {
  try {
    const { value } = await ElMessageBox.prompt('请输入新名称', '重命名测试集', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: ts.name,
      inputPattern: /^.{1,100}$/,
      inputErrorMessage: '名称长度为 1-100 字符',
    })
    await evaluationApi.updateTestSetName(spaceId.value, kbId.value, ts.id, { name: value })
    ElMessage.success('已重命名')
    fetchTestSets()
  } catch {
    // cancelled
  }
}

// ===================== 测评任务 =====================

const taskLoading = ref(false)
const tasks = ref<EvaluationTask[]>([])

async function fetchTasks() {
  taskLoading.value = true
  try {
    const data = await evaluationApi.getTasks(spaceId.value, kbId.value)
    tasks.value = data.items || []
    // Start progress polling if there are active tasks
    const hasActive = tasks.value.some((t) => t.status === 'pending' || t.status === 'running')
    if (hasActive) startProgressPolling()
  } catch {
    // handled by interceptor
  } finally {
    taskLoading.value = false
  }
}

// 创建任务
const createTaskDialogVisible = ref(false)
const createTaskLoading = ref(false)
const taskFormRef = ref<FormInstance>()
const selectedTestSet = ref<TestSet | null>(null)
const taskForm = reactive({
  name: '',
  llm_model: '' as string,
  embedding_model: '' as string,
  search_mode: '',
  top_k: 5,
  score_threshold: 0,
  enable_generation: true,
  enable_mrr: true,
  enable_recall_at_k: false,
  enable_context_precision: true,
  enable_context_recall: true,
  enable_answer_similarity: true,
  correctness_strategy: 'llm',
  faithfulness_strategy: 'decompose',
  relevance_strategy: 'reverse_question',
  retrieval_relevance_strategy: 'llm',
})

const availableLlmModels = ref<string[]>([])
const availableEmbeddingModels = ref<string[]>([])

async function fetchAvailableModels() {
  try {
    const data = await userApi.getAvailableModels()
    availableLlmModels.value = data.llm || []
    availableEmbeddingModels.value = data.embedding || []
  } catch {
    // ignore
  }
}
const taskRules: FormRules = {
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
}

function showCreateTaskDialog(ts: TestSet) {
  selectedTestSet.value = ts
  taskForm.name = `${ts.name} - 测评`
  taskForm.llm_model = ''
  taskForm.embedding_model = ''
  taskForm.search_mode = ''
  createTaskDialogVisible.value = true
  fetchAvailableModels()
}

async function handleCreateTask() {
  if (!taskFormRef.value || !selectedTestSet.value) return

  await taskFormRef.value.validate(async (valid) => {
    if (!valid) return

    createTaskLoading.value = true
    try {
      await evaluationApi.createTask(spaceId.value, kbId.value, {
        test_set_id: selectedTestSet.value!.id,
        name: taskForm.name,
        config: {
          search_mode: taskForm.search_mode || undefined,
          top_k: taskForm.top_k,
          score_threshold: taskForm.score_threshold,
          enable_generation: taskForm.enable_generation,
          llm_model: taskForm.llm_model || null,
          embedding_model: taskForm.embedding_model || null,
          retrieval_relevance_strategy: taskForm.retrieval_relevance_strategy,
          enable_mrr: taskForm.enable_mrr,
          enable_recall_at_k: taskForm.enable_recall_at_k,
          correctness_strategy: taskForm.correctness_strategy,
          faithfulness_strategy: taskForm.faithfulness_strategy,
          relevance_strategy: taskForm.relevance_strategy,
          enable_context_precision: taskForm.enable_context_precision,
          enable_context_recall: taskForm.enable_context_recall,
          enable_answer_similarity: taskForm.enable_answer_similarity,
        },
      })
      ElMessage.success('测评任务已创建')
      createTaskDialogVisible.value = false
      activeTab.value = 'tasks'
      fetchTasks()
    } catch {
      // handled by interceptor
    } finally {
      createTaskLoading.value = false
    }
  })
}

async function handleDeleteTask(task: EvaluationTask) {
  try {
    await ElMessageBox.confirm(`确定删除任务 "${task.name}" 吗？`, '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await evaluationApi.deleteTask(spaceId.value, kbId.value, task.id)
    ElMessage.success('已删除')
    fetchTasks()
  } catch {
    // cancelled
  }
}

// 取消任务
async function handleCancelTask(task: EvaluationTask) {
  try {
    await ElMessageBox.confirm(`确定取消任务 "${task.name}" 吗？`, '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await evaluationApi.cancelTask(spaceId.value, kbId.value, task.id)
    ElMessage.success('任务已取消')
    fetchTasks()
  } catch {
    // cancelled
  }
}

// 任务进度追踪
const taskProgress = reactive<Record<number, { current: number; total: number }>>({})
let progressTimer: ReturnType<typeof setInterval> | null = null

async function pollProgress() {
  const activeTasks = tasks.value.filter((t) => t.status === 'pending' || t.status === 'running')
  if (activeTasks.length === 0) {
    stopProgressPolling()
    return
  }
  for (const task of activeTasks) {
    try {
      const p = await evaluationApi.getTaskProgress(spaceId.value, kbId.value, task.id)
      taskProgress[task.id] = { current: p.current, total: p.total }
      if (p.status === 'completed' || p.status === 'failed' || p.status === 'cancelled') {
        delete taskProgress[task.id]
        fetchTasks()
      }
    } catch {
      // ignore
    }
  }
}

function startProgressPolling() {
  stopProgressPolling()
  pollProgress()
  progressTimer = setInterval(pollProgress, 5000)
}

function stopProgressPolling() {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}

// ===================== 测评报告 =====================

const reportDialogVisible = ref(false)
const reportLoading = ref(false)
const reportData = ref<EvaluationReport | null>(null)
const humanScores = reactive<HumanScoreItem[]>([])
const scoreLoading = ref(false)

async function viewReport(task: EvaluationTask) {
  reportDialogVisible.value = true
  reportLoading.value = true
  reportData.value = null

  try {
    const data = await evaluationApi.getReport(spaceId.value, kbId.value, task.id)
    reportData.value = data

    // 初始化人工评分
    humanScores.length = 0
    for (const d of data.details) {
      humanScores.push({
        index: d.index,
        score: d.human_score || 0,
        comment: d.human_comment || '',
      })
    }
  } catch {
    // handled by interceptor
  } finally {
    reportLoading.value = false
  }
}

async function handleSubmitScores() {
  if (!reportData.value) return

  const validScores = humanScores.filter((s) => s.score > 0)
  if (validScores.length === 0) {
    ElMessage.warning('请至少为一条用例打分')
    return
  }

  scoreLoading.value = true
  try {
    await evaluationApi.submitHumanScores(
      spaceId.value,
      kbId.value,
      reportData.value.task_id,
      { scores: validScores },
    )
    ElMessage.success('评分提交成功')
    // 刷新报告
    const data = await evaluationApi.getReport(spaceId.value, kbId.value, reportData.value.task_id)
    reportData.value = data
    humanScores.length = 0
    for (const d of data.details) {
      humanScores.push({
        index: d.index,
        score: d.human_score || 0,
        comment: d.human_comment || '',
      })
    }
  } catch {
    // handled by interceptor
  } finally {
    scoreLoading.value = false
  }
}

// ===================== 导出 =====================

async function handleExport(task: EvaluationTask, format: 'json' | 'csv') {
  try {
    await evaluationApi.exportReport(spaceId.value, kbId.value, task.id, format)
    ElMessage.success('导出成功')
  } catch {
    // handled by interceptor
  }
}

// ===================== 工具函数 =====================

function getProgressPercent(taskId: number): number {
  const p = taskProgress[taskId]
  if (!p || p.total === 0) return 0
  return Math.round((p.current / p.total) * 100)
}

function formatDate(date: string): string {
  try {
    return new Date(date).toLocaleDateString('zh-CN') + ' ' +
      new Date(date).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '-'
  }
}

function getScoreClass(score: number): string {
  if (score >= 8) return 'score-good'
  if (score >= 5) return 'score-ok'
  return 'score-bad'
}

function getScoreTagType(score: number): string {
  if (score >= 8) return 'success'
  if (score >= 5) return 'warning'
  return 'danger'
}

// ===================== 初始化 =====================

watch(activeTab, (tab) => {
  if (tab === 'test-sets') fetchTestSets()
  if (tab === 'tasks') fetchTasks()
})

onMounted(() => {
  fetchTestSets()
  fetchTasks()
})

onUnmounted(() => {
  stopProgressPolling()
})
</script>

<style scoped>
.kb-evaluation-view {
  padding: var(--space-5);
}

.page-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.nav-tabs {
  display: flex;
  gap: var(--space-2);
}

.nav-tab {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  text-decoration: none;
  transition: all var(--transition-fast);
}

.nav-tab:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.nav-tab.active {
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  font-weight: var(--weight-medium);
}

.eval-tabs {
  margin-bottom: var(--space-4);
}

.tab-toolbar {
  margin-bottom: var(--space-4);
}

/* 汇总指标 */
.report-summary {
  background: var(--color-bg-hover);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  margin-bottom: var(--space-5);
  border: 1px solid var(--color-border-light);
}

.summary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}

.summary-title {
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.summary-meta {
  font-size: 13px;
  color: var(--color-text-muted);
}

.score-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-4);
}

.score-section h4 {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: var(--weight-semibold);
  color: var(--color-text-secondary);
}

.score-items {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}

.score-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--space-2) 14px;
  background: var(--color-bg-card);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  min-width: 80px;
}

.score-item-highlight {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.score-label {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-bottom: var(--space-1);
}

.score-value {
  font-size: var(--text-xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
}

.score-good { color: var(--color-success); }
.score-ok { color: var(--color-warning); }
.score-bad { color: var(--color-danger); }

/* 逐条详情 */
.report-details {
  margin-top: var(--space-2);
}

.details-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-3);
}

.details-title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.detail-title {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.detail-index {
  font-weight: var(--weight-semibold);
  color: var(--color-primary);
  font-size: 13px;
  flex-shrink: 0;
}

.detail-question {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--color-text);
}

.detail-scores-inline {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.detail-body {
  padding-top: var(--space-1);
}

.recall-block {
  margin-bottom: 14px;
}

.recall-label {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  font-weight: var(--weight-medium);
  display: block;
  margin-bottom: var(--space-2);
}

.recall-chunk {
  background: var(--color-bg-hover);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: 10px var(--space-3);
  margin-bottom: 6px;
}

.recall-chunk-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.recall-chunk-id {
  font-size: 11px;
  color: var(--color-text-muted);
  font-family: monospace;
}

.recall-chunk-content {
  font-size: 13px;
  line-height: 1.5;
  color: var(--color-text);
  max-height: 100px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.answer-block {
  margin-bottom: var(--space-3);
}

.answer-label {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  font-weight: var(--weight-medium);
  display: block;
  margin-bottom: var(--space-1);
}

.answer-text {
  font-size: 13px;
  line-height: 1.6;
  padding: 10px var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-bg-hover);
  border: 1px solid var(--color-border-light);
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--color-text);
}

.detail-scores {
  margin: var(--space-3) 0;
}

.human-score-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-light);
}

.human-score-label {
  font-size: 13px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.switch-group {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: 10px;
  padding: 6px 0;
}

.switch-group-label {
  font-size: 13px;
  color: var(--color-text-muted);
  width: 56px;
  flex-shrink: 0;
}

.submit-scores-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-border-light);
}

/* 进度条 */
.progress-mini {
  margin-top: var(--space-1);
  width: 80px;
}

/* 预览弹窗 */
.preview-meta {
  font-size: 13px;
  color: var(--color-text-muted);
  margin: 0 0 var(--space-3);
}

.preview-case-title {
  font-size: 13px;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-case-label {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  font-weight: var(--weight-medium);
  display: block;
  margin-bottom: var(--space-1);
}

.preview-case-value {
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
