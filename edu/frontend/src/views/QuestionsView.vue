<script setup lang="ts">
// 题库练习：统计概览、题型/练习类型筛选、一次一题、错题与重练。
import { CircleCheck, CircleClose, Collection, EditPen, List, RefreshRight } from '@element-plus/icons-vue'
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import CountUp from '@/components/count-up.vue'
import EmptyState from '@/components/empty-state.vue'
import {
  getPracticeStatistics,
  getQuestionCategories,
  getRandomQuestion,
  getWrongDetail,
  getWrongQuestions,
  restartPractice,
  startWrongRetry,
  submitPracticeAnswer,
  submitWrongRetry,
} from '@/api/portal'
import { errorMessage } from '@/lib/api'

const QUESTION_TYPES = [
  { value: 'single', label: '单选题' },
  { value: 'multiple', label: '多选题' },
  { value: 'true_false', label: '判断题' },
  { value: 'fill', label: '填空题' },
  { value: 'qa', label: '问答题' },
  { value: 'group', label: '综合答题' },
]

const categories = ref<{ id: number; name: string }[]>([])
const stats = ref<Record<string, number>>({})
const selectedTypes = ref<string[]>(['single'])
const selectedCategories = ref<number[]>([])

const question = ref<Record<string, any> | null>(null)
const children = ref<Record<string, any>[]>([])
const answer = ref('')
const result = ref<Record<string, any> | null>(null)
const loading = ref(false)
const history = ref<Record<string, any>[]>([])
const historyIndex = ref(-1)

const wrongVisible = ref(false)
const wrongItems = ref<Record<string, any>[]>([])
const wrongDetail = ref<Record<string, any> | null>(null)
const wrongDetailVisible = ref(false)

const retryVisible = ref(false)
const retryAttemptId = ref(0)
const retryQuestions = ref<Record<string, any>[]>([])
const retryIndex = ref(0)
const retryAnswer = ref('')
const retryResult = ref<Record<string, any> | null>(null)

const currentType = computed(() => selectedTypes.value[0] || 'single')
const isAnswered = computed(() => result.value !== null)

function optionList(options: string): { key: string; text: string }[] {
  try {
    const parsed = JSON.parse(options)
    if (Array.isArray(parsed)) {
      return parsed.map((item, index) => ({
        key: item.key || String.fromCharCode(65 + index),
        text: item.text || item.value || String(item),
      }))
    }
    if (parsed && typeof parsed === 'object') {
      return Object.entries(parsed).map(([key, value]) => ({ key, text: String(value) }))
    }
  } catch {
    /* ignore */
  }
  return []
}

async function loadStats() {
  stats.value = (await getPracticeStatistics()) ?? {}
}

async function loadQuestion() {
  loading.value = true
  answer.value = ''
  result.value = null
  try {
    const data = await getRandomQuestion({ type: currentType.value, category_id: selectedCategories.value })
    question.value = data?.question ?? null
    children.value = data?.children ?? []
    if (!question.value) ElMessage.info('暂无更多题目')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

function snapshot() {
  return {
    question: question.value,
    children: children.value,
    answer: answer.value,
    result: result.value,
  }
}

async function next() {
  if (!isAnswered.value && question.value) {
    try {
      await ElMessageBox.confirm('当前题目尚未作答，确定进入下一题吗？', '提示', { type: 'warning' })
    } catch {
      return
    }
  }
  if (historyIndex.value < history.value.length - 1) {
    historyIndex.value += 1
    const item = history.value[historyIndex.value]
    question.value = item.question
    children.value = item.children
    answer.value = item.answer
    result.value = item.result
    return
  }
  history.value.push(snapshot())
  if (history.value.length > 20) history.value.shift()
  historyIndex.value = history.value.length - 1
  await loadQuestion()
}

async function prev() {
  if (historyIndex.value > 0) {
    historyIndex.value -= 1
    const item = history.value[historyIndex.value]
    question.value = item.question
    children.value = item.children
    answer.value = item.answer
    result.value = item.result
  } else {
    ElMessage.info('已经是第一题')
  }
}

async function submit() {
  if (!question.value || !answer.value.trim()) {
    ElMessage.warning('请先作答')
    return
  }
  try {
    const response = await submitPracticeAnswer({
      question_id: question.value.id,
      answer: answer.value,
      category_id: selectedCategories.value[0],
    })
    result.value = response.data as any
    history.value[historyIndex.value] = snapshot()
    await loadStats()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function openWrong() {
  wrongVisible.value = true
  const page = await getWrongQuestions({ p: 1, page_size: 100 })
  wrongItems.value = page?.items ?? []
}

async function showWrongDetail(id: number) {
  wrongDetail.value = await getWrongDetail(id)
  wrongDetailVisible.value = true
}

async function beginRetry() {
  try {
    const response = await startWrongRetry()
    retryAttemptId.value = response.data?.attempt_id ?? 0
    retryQuestions.value = response.data?.questions ?? []
    retryIndex.value = 0
    retryAnswer.value = ''
    retryResult.value = null
    retryVisible.value = true
    wrongVisible.value = false
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

async function submitRetry() {
  if (!retryAnswer.value.trim()) {
    ElMessage.warning('请先作答')
    return
  }
  const current = retryQuestions.value[retryIndex.value]
  try {
    const response = await submitWrongRetry({
      attempt_id: retryAttemptId.value,
      question_id: current.id,
      answer: retryAnswer.value,
    })
    retryResult.value = response.data as any
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

function nextRetry() {
  if (retryIndex.value < retryQuestions.value.length - 1) {
    retryIndex.value += 1
    retryAnswer.value = ''
    retryResult.value = null
  } else {
    ElMessage.success('重练已完成')
    retryVisible.value = false
  }
}

async function restart() {
  await restartPractice()
  await loadStats()
  await loadQuestion()
  ElMessage.success('练习进度已重置')
}

onMounted(async () => {
  categories.value = await getQuestionCategories()
  await loadStats()
  await loadQuestion()
})
</script>

<template>
  <div class="practice">
    <header class="data-page__header">
      <div>
        <h1 class="data-page__title">题库练习</h1>
        <p class="data-page__desc">按题型与练习类型随机抽题，答完即得解析。</p>
      </div>
      <div class="practice__actions">
        <el-button :icon="List" @click="openWrong">错题列表</el-button>
        <el-button type="warning" :icon="RefreshRight" @click="beginRetry">错题重练</el-button>
        <el-button text @click="restart">重置练习</el-button>
      </div>
    </header>

    <section class="practice__stats">
      <div class="metric-card">
        <div class="metric-card__icon metric-card__icon--brand"><el-icon :size="22"><Collection /></el-icon></div>
        <div class="metric-card__body">
          <div class="metric-card__value"><CountUp :value="Number(stats.total_count ?? 0)" /></div>
          <div class="metric-card__label">总题目数</div>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-card__icon metric-card__icon--brand"><el-icon :size="22"><EditPen /></el-icon></div>
        <div class="metric-card__body">
          <div class="metric-card__value"><CountUp :value="Number(stats.answered_count ?? 0)" /></div>
          <div class="metric-card__label">已练习</div>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-card__icon metric-card__icon--success"><el-icon :size="22"><CircleCheck /></el-icon></div>
        <div class="metric-card__body">
          <div class="metric-card__value"><CountUp :value="Number(stats.correct_count ?? 0)" /></div>
          <div class="metric-card__label">正确</div>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-card__icon metric-card__icon--warning"><el-icon :size="22"><CircleClose /></el-icon></div>
        <div class="metric-card__body">
          <div class="metric-card__value"><CountUp :value="Number(stats.wrong_count ?? 0)" /></div>
          <div class="metric-card__label">错误</div>
        </div>
      </div>
    </section>

    <section class="practice__filters">
      <el-select v-model="selectedTypes" multiple placeholder="题型" class="practice__select">
        <el-option v-for="type in QUESTION_TYPES" :key="type.value" :label="type.label" :value="type.value" />
      </el-select>
      <el-select v-model="selectedCategories" multiple placeholder="练习类型" class="practice__select">
        <el-option v-for="category in categories" :key="category.id" :label="category.name" :value="category.id" />
      </el-select>
      <el-button type="primary" @click="() => { history = []; historyIndex = -1; loadQuestion() }">开始练习</el-button>
    </section>

    <section v-loading="loading" class="question-card">
      <template v-if="question">
        <div class="question-type">
          {{ QUESTION_TYPES.find((t) => t.value === question?.type)?.label }}
        </div>
        <div class="question-title">{{ question.title }}</div>

        <div v-if="question.type === 'single' || question.type === 'true_false'" class="options">
          <el-radio-group v-model="answer" :disabled="isAnswered" class="options__group">
            <el-radio
              v-for="option in question.type === 'true_false' ? [{ key: 'A', text: '正确' }, { key: 'B', text: '错误' }] : optionList(question.options)"
              :key="option.key"
              :value="option.key"
              class="option"
            >
              {{ option.key }}. {{ option.text }}
            </el-radio>
          </el-radio-group>
        </div>
        <div v-else-if="question.type === 'multiple'" class="options">
          <el-checkbox-group v-model="answer" :disabled="isAnswered" class="options__group">
            <el-checkbox v-for="option in optionList(question.options)" :key="option.key" :value="option.key" class="option">
              {{ option.key }}. {{ option.text }}
            </el-checkbox>
          </el-checkbox-group>
        </div>
        <div v-else-if="question.type === 'qa'" class="options">
          <el-input v-model="answer" type="textarea" :rows="4" :disabled="isAnswered" placeholder="请输入答案" />
        </div>
        <div v-else-if="question.type === 'group'" class="group-children">
          <div v-for="(child, index) in children" :key="child.id" class="child">
            <div class="child-title">{{ index + 1 }}. {{ child.title }}</div>
            <div v-if="child.type === 'multiple'">
              <el-checkbox-group v-model="answer" :disabled="isAnswered">
                <el-checkbox v-for="option in optionList(child.options)" :key="option.key" :value="option.key">
                  {{ option.key }}. {{ option.text }}
                </el-checkbox>
              </el-checkbox-group>
            </div>
            <div v-else>
              <el-radio-group v-model="answer" :disabled="isAnswered">
                <el-radio v-for="option in optionList(child.options)" :key="option.key" :value="option.key">
                  {{ option.key }}. {{ option.text }}
                </el-radio>
              </el-radio-group>
            </div>
          </div>
        </div>
        <el-input v-else v-model="answer" :disabled="isAnswered" placeholder="请输入答案" />

        <div class="answer-actions">
          <el-button :disabled="historyIndex <= 0" @click="prev">上一题</el-button>
          <el-button v-if="!isAnswered" type="primary" @click="submit">提交答案</el-button>
          <el-button v-else type="primary" @click="next">下一题</el-button>
        </div>

        <div v-if="result" class="result" :class="result.correct ? 'result--ok' : 'result--bad'">
          <div class="result__title">{{ result.correct ? '回答正确' : '回答错误' }}</div>
          <div>正确答案：<strong>{{ result.correct_answer }}</strong></div>
          <div v-if="result.explanation" class="result__explain">解析：{{ result.explanation }}</div>
        </div>
      </template>
      <EmptyState v-else-if="!loading" title="暂无更多题目" description="调整筛选条件后重新开始练习" />
    </section>

    <el-dialog v-model="wrongVisible" :lock-scroll="false" title="错题列表" width="720px">
      <el-table v-if="wrongItems.length" :data="wrongItems" max-height="420">
        <el-table-column prop="title" label="题目" show-overflow-tooltip />
        <el-table-column label="操作" width="100" align="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="showWrongDetail(row.id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <EmptyState v-else title="暂无错题" description="继续练习后会在这里积累错题" />
    </el-dialog>

    <el-dialog v-model="wrongDetailVisible" :lock-scroll="false" title="错题详情" width="640px">
      <template v-if="wrongDetail">
        <p class="detail__title">{{ wrongDetail.title }}</p>
        <p>你的答案：<span class="text-bad">{{ wrongDetail.user_answer || '未作答' }}</span></p>
        <p>正确答案：<span class="text-ok">{{ wrongDetail.correct_answer }}</span></p>
        <p v-if="wrongDetail.explanation" class="detail__explain">解析：{{ wrongDetail.explanation }}</p>
      </template>
    </el-dialog>

    <el-dialog v-model="retryVisible" :lock-scroll="false" title="错题重练" width="640px">
      <template v-if="retryQuestions.length">
        <div class="question-type">第 {{ retryIndex + 1 }} / {{ retryQuestions.length }} 题</div>
        <p class="detail__title">{{ retryQuestions[retryIndex].title }}</p>
        <el-input v-model="retryAnswer" :disabled="retryResult !== null" placeholder="请输入答案" />
        <div v-if="retryResult" class="result" :class="retryResult.correct ? 'result--ok' : 'result--bad'">
          <div class="result__title">{{ retryResult.correct ? '回答正确' : '回答错误' }}</div>
          <div>正确答案：<strong>{{ retryResult.correct_answer }}</strong></div>
          <div class="result__explain">重练不计入正确率统计</div>
        </div>
      </template>
      <template #footer>
        <el-button v-if="retryResult === null" type="primary" @click="submitRetry">提交</el-button>
        <el-button v-else type="primary" @click="nextRetry">下一题</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.practice {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.practice__actions {
  display: flex;
  gap: var(--space-3);
}
.practice__stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
}
.practice__filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
}
.practice__select {
  width: 260px;
}

.question-card {
  padding: var(--space-6);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  min-height: 220px;
}
.question-type {
  margin-bottom: var(--space-2);
  color: var(--brand-500);
  font-size: var(--text-sm);
  font-weight: 600;
}
.question-title {
  margin-bottom: var(--space-4);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-strong);
  line-height: 1.6;
}
.options {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.options__group {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: var(--space-2);
}
.options :deep(.el-radio.option),
.options :deep(.el-checkbox.option) {
  display: flex;
  width: 100%;
  height: auto;
  margin: 0;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  transition: all var(--duration-fast) var(--ease-out);
}
.options :deep(.el-radio.option:hover),
.options :deep(.el-checkbox.option:hover) {
  border-color: var(--brand-300);
  background: var(--brand-50);
}
.group-children .child {
  margin-bottom: var(--space-4);
  padding: var(--space-4);
  background: var(--slate-50);
  border-radius: var(--radius-md);
}
.child-title {
  margin-bottom: var(--space-3);
  font-weight: 500;
  color: var(--text-strong);
}
.answer-actions {
  display: flex;
  gap: var(--space-3);
  margin-top: var(--space-5);
}
.result {
  margin-top: var(--space-4);
  padding: var(--space-4);
  border-radius: var(--radius-md);
  line-height: 1.9;
}
.result__title {
  margin-bottom: var(--space-1);
  font-weight: 700;
}
.result--ok {
  background: var(--success-bg);
  color: var(--success);
}
.result--bad {
  background: var(--danger-bg);
  color: var(--danger);
}
.result__explain {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
}
.text-ok {
  color: var(--success);
  font-weight: 600;
}
.text-bad {
  color: var(--danger);
  font-weight: 600;
}
.detail__title {
  margin-bottom: var(--space-3);
  font-weight: 600;
  color: var(--text-strong);
  line-height: 1.6;
}
.detail__explain {
  color: var(--text-secondary);
}

@media (max-width: 860px) {
  .practice__stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .practice__select {
    width: 100%;
  }
}
</style>
