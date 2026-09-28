<script setup lang="ts">
// 考试作答页：独立整页作答，支持倒计时、暂停、自动保存与交卷。
import { ArrowLeft, Timer, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { getExamAttempt, saveExamAnswers, submitExam } from '@/api/portal'
import EmptyState from '@/components/empty-state.vue'
import { errorMessage } from '@/lib/api'

const route = useRoute()
const router = useRouter()

const attempt = ref<Record<string, any> | null>(null)
const answers = ref<Record<number, string | string[]>>({})
const remaining = ref(0)
const saving = ref(false)
const loading = ref(true)
const paused = ref(false)
const questionRefs = ref<HTMLElement[]>([])
let ticker: number | undefined
let autosave: number | undefined

const attemptId = computed(() => Number(route.params.attemptId))
// 成绩回顾模式：只读查看已交卷试卷，不显示顶部操作按钮
const review = computed(() => String(route.query.review) === '1')
const questions = computed<Record<string, any>[]>(() => attempt.value?.questions ?? [])
/** 归一化作答值为字符串：多选题为数组，需合并为字母串提交。 */
function toAnswerText(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value.join('')
  return value ?? ''
}

const answeredCount = computed(
  () => Object.values(answers.value).filter((value) => toAnswerText(value).trim()).length,
)

/** 设置题目元素引用，用于答题卡跳转滚动。 */
function setQuestionRef(el: any, index: number) {
  if (el) questionRefs.value[index] = el as HTMLElement
}

/** 点击答题卡序号：平滑滚动到对应题目。 */
function jumpTo(index: number) {
  const target = questionRefs.value[index]
  if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** 组装提交载荷：包含综合题子题，并归一化为字符串。 */
function answerPayload() {
  const payload: { question_id: number; answer: string }[] = []
  for (const question of questions.value) {
    payload.push({ question_id: question.id, answer: toAnswerText(answers.value[question.id]).trim() })
    for (const child of question.children ?? []) {
      payload.push({ question_id: child.id, answer: toAnswerText(answers.value[child.id]).trim() })
    }
  }
  return payload
}

function formatTime(seconds: number) {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** 解析题目选项：支持 JSON 数组/对象与「；」分隔文本。 */
function parseOptions(options: string): { key: string; text: string }[] {
  const raw = (options || '').trim()
  if (!raw) return []
  if (raw.startsWith('{') || raw.startsWith('[')) {
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        return parsed.map((item: any, index: number) => ({
          key: item.key || String.fromCharCode(65 + index),
          text: item.text ?? item.value ?? String(item),
        }))
      }
      return Object.entries(parsed).map(([key, value]) => ({ key, text: String(value) }))
    } catch {
      return []
    }
  }
  return raw
    .split(/[；;]/)
    .map((text) => text.trim())
    .filter(Boolean)
    .map((text, index) => ({ key: String.fromCharCode(65 + index), text }))
}

/** 取题目的选项列表；综合题无选项时回退为 A/B/C/D。 */
function questionOptions(question: Record<string, any>) {
  return parseOptions(question.options)
}

/** 抽取答案中的字母集合（用于判断选项是否正确/误选）。 */
function answerLetters(value: unknown): string {
  const text = Array.isArray(value) ? value.join('') : String(value ?? '')
  return text.toUpperCase().replace(/[^A-Z]/g, '')
}

function isCorrectOption(question: Record<string, any>, key: string): boolean {
  return answerLetters(question.correct_answer).includes(key.toUpperCase())
}

function isWrongOption(question: Record<string, any>, key: string): boolean {
  return (
    answerLetters(answers.value[question.id]).includes(key.toUpperCase()) &&
    !isCorrectOption(question, key)
  )
}

function startTimers() {
  stopTimers()
  ticker = window.setInterval(() => {
    remaining.value = Math.max(remaining.value - 1, 0)
    if (remaining.value <= 0) void autoSubmit()
  }, 1000)
  autosave = window.setInterval(() => void saveNow(), 30000)
}

function stopTimers() {
  if (ticker) window.clearInterval(ticker)
  if (autosave) window.clearInterval(autosave)
  ticker = undefined
  autosave = undefined
}

/** 暂停/继续答题：暂停停止倒计时与自动保存，并遮罩作答区。 */
function togglePause() {
  if (paused.value) {
    paused.value = false
    startTimers()
  } else {
    paused.value = true
    stopTimers()
    void saveNow()
  }
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
  stopTimers()
  router.push('/exams')
}

async function finishWithResult(payload: Record<string, any>) {
  stopTimers()
  ElMessage.success(`已交卷，得分 ${payload.total_score ?? 0}`)
  router.push('/exams')
}

async function confirmSubmit() {
  const unanswered = questions.value.length - answeredCount.value
  try {
    await ElMessageBox.confirm(`还有 ${unanswered} 道未作答，确定交卷吗？`, '交卷确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    const response = await submitExam({ attempt_id: attempt.value!.attempt_id, answers: answerPayload() })
    await finishWithResult(response.data ?? {})
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

function goBack() {
  router.push('/exams')
}

onMounted(async () => {
  loading.value = true
  try {
    const data = await getExamAttempt(attemptId.value)
    // 回顾已交卷试卷：只读展示作答与判分，不启动计时
    if (data?.submitted && review.value) {
      attempt.value = data
      const filled: Record<number, string> = {}
      for (const question of data.questions ?? []) filled[question.id] = question.user_answer ?? ''
      answers.value = filled
      return
    }
    if (!data || data.submitted) {
      ElMessage.info('该场考试已结束')
      router.push('/exams')
      return
    }
    attempt.value = data
    remaining.value = data.remaining_seconds ?? 0
    startTimers()
  } catch (error) {
    ElMessage.error(errorMessage(error))
    router.push('/exams')
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(stopTimers)
</script>

<template>
  <div v-loading="loading" class="attempt">
    <header class="attempt__header">
      <div class="attempt__left">
        <el-button :icon="ArrowLeft" @click="goBack">返回</el-button>
        <span class="attempt__title">{{ attempt?.title || '考试作答' }}</span>
        <el-tag v-if="review" type="info" effect="light">成绩回顾</el-tag>
      </div>
      <div class="attempt__right">
        <template v-if="!review">
          <el-tooltip content="保存当前作答进度" placement="bottom">
            <el-button @click="saveNow">保存</el-button>
          </el-tooltip>
          <el-tooltip content="暂停后倒计时与自动保存将停止" placement="bottom">
            <el-button :icon="paused ? VideoPlay : VideoPause" @click="togglePause">
              {{ paused ? '继续' : '暂停' }}
            </el-button>
          </el-tooltip>
          <el-tooltip content="提交试卷后不可再修改" placement="bottom">
            <el-button type="primary" @click="confirmSubmit">交卷</el-button>
          </el-tooltip>
          <div class="attempt__timer" :class="{ 'is-urgent': remaining <= 300 }">
            <el-icon><Timer /></el-icon>
            剩余时间 {{ formatTime(remaining) }}
            <span class="attempt__save">{{ saving ? '保存中…' : '已自动保存' }}</span>
          </div>
        </template>
      </div>
    </header>

    <div v-if="attempt" class="attempt__body">
      <section class="attempt__questions">
        <article
          v-for="(question, index) in questions"
          :key="question.id"
          :ref="(el) => setQuestionRef(el, index)"
          class="exam-question"
        >
          <div class="exam-question__head">
            <div class="exam-question__title">{{ index + 1 }}. {{ question.title }}</div>
            <el-tag
              v-if="review"
              :type="question.is_correct ? 'success' : 'danger'"
              effect="light"
              size="small"
            >
              {{ question.is_correct ? `正确 +${question.earned_score}` : `错误 +${question.earned_score}` }}
            </el-tag>
          </div>
          <div v-if="question.children" class="children">
            <div v-for="child in question.children" :key="child.id" class="child">
              <div class="child__title">{{ child.title }}</div>
              <el-radio-group
                v-if="child.type === 'single' || child.type === 'true_false'"
                v-model="answers[child.id]"
                :disabled="review"
                class="option-group"
              >
                <el-radio
                  v-for="option in (child.type === 'true_false' ? [{ key: 'A', text: '正确' }, { key: 'B', text: '错误' }] : (questionOptions(child).length ? questionOptions(child) : [{ key: 'A', text: 'A' }, { key: 'B', text: 'B' }, { key: 'C', text: 'C' }, { key: 'D', text: 'D' }]))"
                  :key="option.key"
                  :value="option.key"
                  class="option"
                >
                  {{ option.key }}. {{ option.text }}
                </el-radio>
              </el-radio-group>
              <el-checkbox-group
                v-else-if="child.type === 'multiple'"
                v-model="answers[child.id]"
                :disabled="review"
                class="option-group"
              >
                <el-checkbox
                  v-for="option in (questionOptions(child).length ? questionOptions(child) : [{ key: 'A', text: 'A' }, { key: 'B', text: 'B' }, { key: 'C', text: 'C' }, { key: 'D', text: 'D' }])"
                  :key="option.key"
                  :value="option.key"
                  class="option"
                >
                  {{ option.key }}. {{ option.text }}
                </el-checkbox>
              </el-checkbox-group>
              <el-input v-else v-model="answers[child.id]" :disabled="review" placeholder="请输入答案" />
            </div>
          </div>
          <el-radio-group
            v-else-if="question.type === 'single' || question.type === 'true_false'"
            v-model="answers[question.id]"
            :disabled="review"
            class="option-group"
          >
            <el-radio
              v-for="option in (question.type === 'true_false' ? [{ key: 'A', text: '正确' }, { key: 'B', text: '错误' }] : (questionOptions(question).length ? questionOptions(question) : [{ key: 'A', text: 'A' }, { key: 'B', text: 'B' }, { key: 'C', text: 'C' }, { key: 'D', text: 'D' }]))"
              :key="option.key"
              :value="option.key"
              class="option"
              :class="review ? (isCorrectOption(question, option.key) ? 'option--correct' : (isWrongOption(question, option.key) ? 'option--wrong' : '')) : ''"
            >
              {{ option.key }}. {{ option.text }}
            </el-radio>
          </el-radio-group>
          <el-checkbox-group
            v-else-if="question.type === 'multiple'"
            v-model="answers[question.id]"
            :disabled="review"
            class="option-group"
          >
            <el-checkbox
              v-for="option in (questionOptions(question).length ? questionOptions(question) : [{ key: 'A', text: 'A' }, { key: 'B', text: 'B' }, { key: 'C', text: 'C' }, { key: 'D', text: 'D' }])"
              :key="option.key"
              :value="option.key"
              class="option"
              :class="review ? (isCorrectOption(question, option.key) ? 'option--correct' : (isWrongOption(question, option.key) ? 'option--wrong' : '')) : ''"
            >
              {{ option.key }}. {{ option.text }}
            </el-checkbox>
          </el-checkbox-group>
          <el-input v-else v-model="answers[question.id]" type="textarea" :rows="3" :disabled="review" placeholder="请输入答案" />
          <div v-if="review" class="review-answer">
            你的答案：<span :class="question.is_correct ? 'text-ok' : 'text-bad'">{{ question.user_answer || '未作答' }}</span>
            · 正确答案：<span class="text-ok">{{ question.correct_answer || '—' }}</span>
            <template v-if="question.explanation">
              <div class="review-answer__explain">解析：{{ question.explanation }}</div>
            </template>
          </div>
        </article>
        <EmptyState v-if="!questions.length" title="暂无题目" description="该试卷未配置题目" />
      </section>

      <aside class="navigator">
        <div class="navigator__title">题目概览（{{ answeredCount }}/{{ questions.length }}）</div>
        <div class="navigator__grid">
          <span
            v-for="(question, index) in questions"
            :key="question.id"
            class="nav-item"
            :class="{
              'nav-item--correct': review && question.is_correct,
              'nav-item--wrong': review && !question.is_correct,
              'nav-item--answered': !review && answers[question.id] && String(answers[question.id]).trim(),
            }"
            @click="jumpTo(index)"
          >
            {{ index + 1 }}
          </span>
        </div>
      </aside>
    </div>

    <div v-if="paused" class="attempt__pause-mask">
      <div class="attempt__pause-card">
        <el-icon :size="42"><VideoPause /></el-icon>
        <p class="attempt__pause-title">已暂停</p>
        <p class="attempt__pause-desc">倒计时与自动保存已停止</p>
        <el-button type="primary" size="large" @click="togglePause">继续作答</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.attempt {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: var(--space-4);
}
.attempt__header {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
}
.attempt {
  position: relative;
}
.attempt__left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.attempt__right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
.attempt__title {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attempt__timer {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-pill);
  background: var(--slate-100);
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.attempt__timer.is-urgent {
  background: var(--danger-bg);
  color: var(--danger);
}
.attempt__save {
  margin-left: var(--space-2);
  font-weight: 500;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.attempt__body {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: var(--space-4);
}
.attempt__questions {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-5) var(--space-6);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
.exam-question {
  padding: var(--space-4) 0;
  border-bottom: 1px solid var(--border-color);
}
.exam-question:first-child {
  padding-top: 0;
}
.exam-question:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.exam-question__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.exam-question__title {
  font-weight: 500;
  color: var(--text-strong);
  line-height: 1.6;
}
.exam-question__head .exam-question__title {
  margin-bottom: 0;
}
/* 回顾模式：正确/误选选项高亮 */
.option--correct {
  border-color: var(--success-border);
  background: var(--success-bg);
  color: var(--success);
  font-weight: 600;
}
.option--wrong {
  border-color: var(--danger-border);
  background: var(--danger-bg);
  color: var(--danger);
  font-weight: 600;
}
.review-answer {
  margin-top: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--slate-50);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: var(--leading-normal);
}
.review-answer__explain {
  margin-top: var(--space-2);
  color: var(--text-secondary);
}

.children .child {
  margin-bottom: var(--space-3);
}
.child__title {
  margin-bottom: var(--space-2);
  color: var(--text-secondary);
}
.option-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.option {
  display: flex;
  width: 100%;
  height: auto;
  margin: 0;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  transition: all var(--duration-fast) var(--ease-out);
}
.option:hover {
  border-color: var(--brand-300);
  background: var(--brand-50);
}
.navigator {
  display: flex;
  width: 220px;
  flex-shrink: 0;
  flex-direction: column;
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
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
  height: 34px;
  place-items: center;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out),
    background-color var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out);
}
.nav-item:hover {
  border-color: var(--brand-300);
  background: var(--brand-50);
  color: var(--brand-600);
}
.nav-item--answered {
  background: var(--brand-500);
  border-color: var(--brand-500);
  color: #fff;
}
/* 回顾模式：正确绿色、错误红色 */
.nav-item--correct {
  background: var(--success);
  border-color: var(--success);
  color: #fff;
}
.nav-item--wrong {
  background: var(--danger);
  border-color: var(--danger);
  color: #fff;
}
.text-ok {
  color: var(--success);
  font-weight: 600;
}
.text-bad {
  color: var(--danger);
  font-weight: 600;
}
.navigator__grid {
  flex: 1;
  min-height: 0;
  align-content: start;
  overflow-y: auto;
}
.attempt__pause-mask {
  position: absolute;
  inset: 0;
  z-index: 30;
  display: grid;
  place-items: center;
  background: rgba(15, 26, 46, 0.55);
  backdrop-filter: blur(3px);
}
.attempt__pause-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-8) var(--space-10);
  background: var(--bg-surface);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  text-align: center;
}
.attempt__pause-title {
  margin: var(--space-2) 0 0;
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-strong);
}
.attempt__pause-desc {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

@media (max-width: 860px) {
  .attempt__body {
    flex-direction: column;
  }
  .navigator {
    width: 100%;
  }
}
</style>
