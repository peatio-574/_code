<script setup lang="ts">
// 冲刺考试：模拟考试、可参加考试与成绩记录；点击开始进入独立作答页。
import { EditPen, Tickets, TrendCharts, Trophy } from '@element-plus/icons-vue'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import CountUp from '@/components/count-up.vue'
import EmptyState from '@/components/empty-state.vue'
import {
  getAvailableExams,
  getExamHistory,
  getExamStatistics,
  startExamAttempt,
  startMockExam,
} from '@/api/portal'
import { errorMessage } from '@/lib/api'

const router = useRouter()

const stats = ref<Record<string, number>>({})
const available = ref<Record<string, any>[]>([])
const history = ref<Record<string, any>[]>([])
const starting = ref(false)

async function load() {
  stats.value = (await getExamStatistics()) ?? {}
  available.value = await getAvailableExams()
  history.value = await getExamHistory()
}

/** 开始/继续考试：创建或复用作答记录后进入作答页。 */
async function beginExam(loader: () => Promise<any>) {
  if (starting.value) return
  starting.value = true
  try {
    const response = await loader()
    if (!response?.success) {
      ElMessage.error(response?.message || '无法开始考试')
      return
    }
    const attemptId = response.data?.attempt_id
    if (!attemptId) {
      ElMessage.error('无法进入考试')
      return
    }
    await router.push(`/exams/attempt/${attemptId}`)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    starting.value = false
  }
}

/** 成绩详情：跳转到考试页面（只读回顾，不显示顶部操作按钮）。 */
function viewResult(attemptId: number) {
  router.push({ path: `/exams/attempt/${attemptId}`, query: { review: '1' } })
}

onMounted(load)
</script>

<template>
  <div class="exams">
    <header class="data-page__header page-hero">
      <div>
        <h1 class="data-page__title">冲刺考试</h1>
        <p class="data-page__desc">参加模拟与正式考试，检验学习成果。</p>
      </div>
      <el-button type="primary" :icon="EditPen" :loading="starting" @click="beginExam(startMockExam)">模拟考试</el-button>
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
        <el-table-column label="有效时间" min-width="300">
          <template #default="{ row }">
            <span class="cell-muted tabular">
              {{ new Date(row.exam_time * 1000).toLocaleString('zh-CN') }} ~ {{ new Date(row.end_time * 1000).toLocaleString('zh-CN') }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="total_questions" label="题目数" min-width="100" align="center" />
        <el-table-column prop="duration" label="时长(分钟)" min-width="120" align="center" />
        <el-table-column label="操作" width="140" align="right">
          <template #default="{ row }">
            <el-button
              type="primary"
              :loading="starting && !row.submitted"
              :disabled="row.submitted"
              @click="beginExam(() => startExamAttempt(row.exam_id))"
            >
              {{ row.submitted ? '已交卷' : row.attempt_id ? '继续考试' : '开始考试' }}
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
            <el-tag :type="row.passed ? 'success' : 'danger'" effect="dark">
              {{ row.status === 1 ? (row.passed ? '合格' : '未合格') : '进行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :disabled="row.status !== 1"
              @click="viewResult(row.attempt_id)"
            >
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <EmptyState v-else title="暂无考试记录" description="参加考试后成绩会显示在这里" />
    </section>
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

@media (max-width: 860px) {
  .exams__stats {
    grid-template-columns: 1fr;
  }
}
</style>
