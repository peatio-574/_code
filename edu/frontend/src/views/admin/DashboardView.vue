<script setup lang="ts">
// 控制台总览：核心指标、近七天学习情况与待处理内容。
import { DataAnalysis, Reading, Tickets, TrendCharts } from '@element-plus/icons-vue'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getDashboard } from '@/api/admin'
import CountUp from '@/components/count-up.vue'
import EmptyState from '@/components/empty-state.vue'
import { formatDate } from '@/lib/labels'

const router = useRouter()
const data = ref<Record<string, any> | null>(null)
const loading = ref(false)

const metrics = computed(() => [
  {
    label: '活跃学员',
    value: data.value?.metrics?.active_students ?? 0,
    icon: DataAnalysis,
    tone: 'brand',
  },
  {
    label: '已发布课程',
    value: data.value?.metrics?.published_courses ?? 0,
    icon: Reading,
    tone: 'success',
  },
  {
    label: '已发布考试',
    value: data.value?.metrics?.published_exams ?? 0,
    icon: Tickets,
    tone: 'warning',
  },
])

const activity = computed<Record<string, any>[]>(() => data.value?.activity ?? [])
const tasks = computed<Record<string, any>[]>(() => data.value?.tasks ?? [])

const taskKindType: Record<string, 'primary' | 'warning' | 'info'> = {
  课程: 'primary',
  考试: 'warning',
  公告: 'info',
}

async function load() {
  loading.value = true
  try {
    data.value = await getDashboard()
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="dashboard">
    <div class="dashboard__metrics">
      <div v-for="item in metrics" :key="item.label" class="metric-card">
        <div class="metric-card__icon" :class="`metric-card__icon--${item.tone}`">
          <el-icon :size="24"><component :is="item.icon" /></el-icon>
        </div>
        <div class="metric-card__body">
          <div class="metric-card__value"><CountUp :value="Number(item.value)" /></div>
          <div class="metric-card__label">{{ item.label }}</div>
        </div>
      </div>
    </div>

    <div class="dashboard__grid">
      <el-card class="dashboard__card">
        <template #header>
          <div class="card-head">
            <span>近七天学习情况</span>
            <el-icon class="card-head__icon"><TrendCharts /></el-icon>
          </div>
        </template>
        <el-table v-if="activity.length" :data="activity" height="100%">
          <el-table-column label="日期">
            <template #default="{ row }"><span class="tabular">{{ row.day }}</span></template>
          </el-table-column>
          <el-table-column label="学习人数" min-width="140" align="right">
            <template #default="{ row }"><span class="tabular cell-strong">{{ row.active_students }}</span></template>
          </el-table-column>
        </el-table>
        <EmptyState v-else title="暂无学习数据" description="近七天还没有学员产生学习记录" />
      </el-card>

      <el-card class="dashboard__card">
        <template #header>
          <div class="card-head">
            <span>待处理内容</span>
            <el-tag v-if="tasks.length" type="warning" effect="light" size="small">{{ tasks.length }} 项</el-tag>
          </div>
        </template>
        <el-table v-if="tasks.length" :data="tasks" height="100%">
          <el-table-column label="类型" min-width="90">
            <template #default="{ row }">
              <el-tag :type="taskKindType[row.kind] ?? 'info'" effect="light" size="small">{{ row.kind }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" min-width="100" />
          <el-table-column label="更新时间" min-width="120">
            <template #default="{ row }"><span class="cell-muted tabular">{{ formatDate(row.updated_at) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" min-width="90" align="right">
            <template #default="{ row }">
              <el-button link type="primary" class="task-link" @click="router.push(row.url)">前往</el-button>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState v-else title="暂无待处理内容" description="课程、考试与公告均已处理完毕" />
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.card-head__icon {
  color: var(--text-tertiary);
}
</style>
