<script setup lang="ts">
// 冲刺考试：模拟考试、可参加考试、自动保存倒计时、成绩记录。
import { EditPen, Tickets, Timer, TrendCharts, Trophy } from '@element-plus/icons-vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import CountUp from '@/components/count-up.vue'
import EmptyState from '@/components/empty-state.vue'
import {
  getAvailableExams,
  getExamHistory,
  getExamResult,
  getExamStatistics,
  saveExamAnswers,
  startExamAttempt,
  startMockExam,
  submitExam,
} from '@/api/portal'
import { errorMessage } from '@/lib/api'

const stats = ref<Record<string, number>>({})
const available = ref<Record<string, any>[]>([])
const history = ref<Record<string, any>[]>([])

const examActive = ref(false)
const attempt = ref<Record<string, any> | null>(null)
const answers = ref<Record<number, string>>({})
const remaining = ref(0)
const saving = ref(false)
let ticker: number | undefined
let autosave: number | undefined

const resultVisible = ref(false)
const result = ref<Record<string, any> | null>(null)

const questions = computed<Record<string, any>[]>(() => attempt.value?.questions ?? [])
const answeredCount = computed(() => Object.values(answers.value).filter((value) => value && value.trim()).length)

async function load() {
  stats.value = (await getExamStatistics()) ?? {}
  available.value = await getAvailableExams()
  history.value = await getExamHistory()
}

function answerPayload() {
  return questions.value.map((question) => ({ question_id: question.id, answer: answers.value[question.id] ?? '' }))
}

async function beginExam(loader: () => Promise<any>) {
  try {
    const response = await loader()
    if (!response?.success) {
      ElMessage.error(response?.message || '无法开始考试')
      return
    }
    attempt.value = response.data
    answers.value = {}
    remaining.value = response.data?.remaining_seconds ?? 0
    examActive.value = true
    startTimers()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

function startTimers() {
  stopTimers()
  ticker = window.setInterval(() => {
    remaining.value = Math.max(remaining.value - 1, 0)
    if (remaining.value <= 0) {
      void autoSubmit()
    }
  }, 1000)
  autosave = window.setInterval(() => void saveNow(), 30000)
}

function stopTimers() {
  if (ticker) window.clearInterval(ticker)
  if (autosave) window.clearInterval(autosave)
  ticker = undefined
  autosave = undefined
}

async function saveNow() {
  if (!attempt.value) return
  saving.value = true
  try {
    const response = await saveExamAnswers({ attempt_id: attempt.value.attempt_id, answers: answerPayload() })
    if (response.data?.ended) {
      await finishWithResult(response.data)
    }
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

async function autoSubmit() {
  if (!attempt.value) return
  try {
    await submitExam({ attempt_id: attempt.value.attempt_id, answers: answerPayload() })
  } catch {
    /* ignore */
  }
  ElMessage.info('考试时间已到，已自动交卷')
  await load()
  examActive.value = false
  stopTimers()
}

async function finishWithResult(payload: Record<string, any>) {
  examActive.value = false
  stopTimers()
  ElMessage.success(`已交卷，得分 ${payload.total_score ?? 0}`)
  await load()
}

async function confirmSubmit() {
  const unanswered = questions.value.length - answeredCount.value
  try {
    await ElMessageBox.confirm(`还有 ${unanswered} 道未作答，确定交卷吗？`, '交卷确认', { type: 'warning' })
  } catch {
    return
  }
  const response = await submitExam({ attempt_id: attempt.value!.attempt_id, answers: answerPayload() })
  await finishWithResult(response.data ?? {})
}

async function viewResult(attemptId: number) {
  result.value = await getExamResult(attemptId)
  resultVisible.value = true
}

function formatTime(seconds: number) {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

onMounted(load)
onBeforeUnmount(stopTimers)
</script>

<template>
  <div class="exams">
    <header class="data-page__header">
      <div>
        <h1 class="data-page__title">冲刺考试</h1>
        <p class="data-page__desc">参加模拟与正式考试，检验学习成果。</p>
      </div>
      <el-button type="primary" :icon="EditPen" @click="beginExam(startMockExam)">模拟考试</el-button>
    </header>

    <section class="exams__stats">
      <div class="metric-card">
        <div class="metric-card__icon metric-card__icon--brand"><el-icon :size="22"><Tickets /></el-icon></div>
        <div class="metric-card__body">
          <div class="metric-card__value"><CountUp :value="Number(stats.attempt_count ?? 0)" /></div>
          <div class="metric-card__label">已参加考试</div>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-card__icon metric-card__icon--warning"><el-icon :size="22"><TrendCharts /></el-icon></div>
        <div class="metric-card__body">
          <div class="metric-card__value"><CountUp :value="Number(stats.average_score ?? 0)" :decimals="1" /></div>
          <div class="metric-card__label">平均得分</div>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-card__icon metric-card__icon--success"><el-icon :size="22"><Trophy /></el-icon></div>
        <div class="metric-card__body">
          <div class="metric-card__value"><CountUp :value="Number(stats.pass_count ?? 0)" /></div>
          <div class="metric-card__label">合格次数</div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel__head">
        <h2 class="panel__title">可参加考试</h2>
        <span class="cell-muted">共 {{ available.length }} 场</span>
      </div>
      <el-table v-if="available.length" :data="available">
        <el-table-column prop="title" label="试卷名称" min-width="200" />
        <el-table-column prop="total_questions" label="题目数" min-width="100" align="center" />
        <el-table-column prop="duration" label="时长(分钟)" min-width="120" align="center" />
        <el-table-column label="操作" width="110" align="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="beginExam(() => startExamAttempt(row.exam_id))">
              {{ row.attempt_id ? '继续' : '开始' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <EmptyState v-else title="暂无可参加的考试" description="请等待教师发布新的考试" />
    </section>

    <section class="panel">
      <div class="panel__head">
        <h2 class="panel__title">成绩记录</h2>
        <span class="cell-muted">共 {{ history.length }} 条</span>
      </div>
      <el-table v-if="history.length" :data="history">
        <el-table-column prop="title" label="试卷" min-width="200" />
        <el-table-column label="开始时间" min-width="200">
          <template #default="{ row }">
            <span class="cell-muted tabular">{{ new Date(row.start_time * 1000).toLocaleString('zh-CN') }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="total_score" label="得分" min-width="90" align="center" />
        <el-table-column prop="pass_score" label="合格线" min-width="90" align="center" />
        <el-table-column label="状态" min-width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="row.passed ? 'success' : 'info'" effect="light">
              {{ row.status === 1 ? (row.passed ? '合格' : '未合格') : '进行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 1" link type="primary" @click="viewResult(row.attempt_id)">查看详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <EmptyState v-else title="暂无考试记录" description="参加考试后成绩会显示在这里" />
    </section>

    <el-dialog v-model="examActive" :lock-scroll="false" :title="attempt?.title" width="900px" top="4vh" :close-on-click-modal="false" :show-close="false">
      <div class="exam-toolbar">
        <span class="exam-toolbar__timer"><el-icon><Timer /></el-icon>剩余时间 {{ formatTime(remaining) }}</span>
        <span class="cell-muted">{{ saving ? '保存中…' : '已自动保存' }}</span>
      </div>
      <div class="exam-body">
        <div class="exam-questions">
          <div v-for="(question, index) in questions" :key="question.id" class="exam-question">
            <div class="exam-question__title">{{ index + 1 }}. {{ question.title }}</div>
            <div v-if="question.children" class="children">
              <div v-for="child in question.children" :key="child.id" class="child">
                <div class="child__title">{{ child.title }}</div>
                <el-input v-model="answers[child.id]" placeholder="请输入答案" />
              </div>
            </div>
            <el-radio-group v-else-if="question.type === 'single' || question.type === 'true_false'" v-model="answers[question.id]">
              <el-radio value="A">A</el-radio>
              <el-radio value="B">B</el-radio>
              <el-radio value="C">C</el-radio>
              <el-radio value="D">D</el-radio>
            </el-radio-group>
            <el-checkbox-group v-else-if="question.type === 'multiple'" v-model="answers[question.id]">
              <el-checkbox value="A">A</el-checkbox>
              <el-checkbox value="B">B</el-checkbox>
              <el-checkbox value="C">C</el-checkbox>
              <el-checkbox value="D">D</el-checkbox>
            </el-checkbox-group>
            <el-input v-else v-model="answers[question.id]" type="textarea" :rows="3" placeholder="请输入答案" />
          </div>
        </div>
        <aside class="navigator">
          <div class="navigator__title">答题卡（{{ answeredCount }}/{{ questions.length }}）</div>
          <div class="navigator__grid">
            <span
              v-for="(question, index) in questions"
              :key="question.id"
              class="nav-item"
              :class="{ 'nav-item--answered': answers[question.id] && answers[question.id].trim() }"
            >
              {{ index + 1 }}
            </span>
          </div>
        </aside>
      </div>
      <template #footer>
        <el-button @click="saveNow">保存</el-button>
        <el-button type="primary" @click="confirmSubmit">交卷</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resultVisible" :lock-scroll="false" title="考试详情" width="720px">
      <template v-if="result">
        <div class="result-summary" :class="result.passed ? 'result-summary--ok' : 'result-summary--bad'">
          <span class="result-summary__score">{{ result.total_score }}</span>
          <span>合格线 {{ result.pass_score }} · {{ result.passed ? '合格' : '未合格' }}</span>
        </div>
        <div v-for="(question, index) in result.questions" :key="question.id" class="result-item">
          <div class="result-item__title">{{ index + 1 }}. {{ question.title }}</div>
          <div class="result-item__line">
            你的答案：<span :class="question.is_correct ? 'text-ok' : 'text-bad'">{{ question.user_answer || '未作答' }}</span>
            · 正确答案：<span class="text-ok">{{ question.correct_answer }}</span>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.exams {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.exams__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}

.panel {
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
.panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}
.panel__title {
  font-size: var(--text-lg);
  font-weight: 700;
}

.exam-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--slate-50);
  border-radius: var(--radius-md);
}
.exam-toolbar__timer {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 700;
  color: var(--danger);
  font-variant-numeric: tabular-nums;
}
.exam-body {
  display: flex;
  gap: var(--space-4);
}
.exam-questions {
  flex: 1;
  min-width: 0;
  max-height: 60vh;
  overflow-y: auto;
  padding-right: var(--space-2);
}
.exam-question {
  padding: var(--space-4) 0;
  border-bottom: 1px solid var(--border-color);
}
.exam-question:last-child {
  border-bottom: none;
}
.exam-question__title {
  margin-bottom: var(--space-3);
  font-weight: 500;
  color: var(--text-strong);
  line-height: 1.6;
}
.children .child {
  margin-bottom: var(--space-3);
}
.child__title {
  margin-bottom: var(--space-2);
  color: var(--text-secondary);
}

.navigator {
  width: 200px;
  flex-shrink: 0;
  padding-left: var(--space-4);
  border-left: 1px solid var(--border-color);
}
.navigator__title {
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.navigator__grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-2);
}
.nav-item {
  display: grid;
  height: 30px;
  place-items: center;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.nav-item--answered {
  background: var(--brand-500);
  border-color: var(--brand-500);
  color: #fff;
}

.result-summary {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding: var(--space-4);
  border-radius: var(--radius-md);
}
.result-summary--ok {
  background: var(--success-bg);
  color: var(--success);
}
.result-summary--bad {
  background: var(--danger-bg);
  color: var(--danger);
}
.result-summary__score {
  font-size: var(--text-2xl);
  font-weight: 800;
}
.result-item {
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--border-color);
}
.result-item__title {
  margin-bottom: var(--space-1);
  color: var(--text-strong);
}
.result-item__line {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.text-ok {
  color: var(--success);
  font-weight: 600;
}
.text-bad {
  color: var(--danger);
  font-weight: 600;
}

@media (max-width: 860px) {
  .exams__stats {
    grid-template-columns: 1fr;
  }
  .exam-body {
    flex-direction: column;
  }
  .navigator {
    width: 100%;
    padding-left: 0;
    border-left: none;
    border-top: 1px solid var(--border-color);
    padding-top: var(--space-4);
  }
}
</style>
