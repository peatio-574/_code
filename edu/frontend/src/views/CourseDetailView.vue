<script setup lang="ts">
// 课程详情：概述、教师、总时长/已学进度、章节列表与开始学习。
import { Clock, Reading, User } from '@element-plus/icons-vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getCourseDetail, getWatchProgress } from '@/api/portal'
import EmptyState from '@/components/empty-state.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const detail = ref<Record<string, any> | null>(null)
const progress = ref<Record<string, any> | null>(null)
const loading = ref(true)

const courseId = computed(() => Number(route.params.courseId))

const chapters = computed<Record<string, any>[]>(() => detail.value?.chapters ?? [])

const coverStyle = computed(() => {
  const cover = detail.value?.course?.cover
  return cover
    ? { backgroundImage: `url(/api/image/${cover}), linear-gradient(135deg, var(--brand-100), var(--brand-200))` }
    : {}
})

const completedSet = computed(() => {
  const set = new Set<number>()
  for (const item of progress.value?.chapters ?? []) if (item.completed) set.add(item.chapter_id)
  return set
})

const progressPercent = computed(() => {
  const total = chapters.value.filter((chapter) => chapter.file).length
  if (!total) return 0
  return Math.round(((progress.value?.completed_chapters ?? 0) / total) * 100)
})

function formatDuration(seconds: number) {
  const total = Math.round(seconds || 0)
  if (total <= 0) return '0 秒'
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h} 小时 ${m} 分`
  return `${m} 分 ${String(s).padStart(2, '0')} 秒`
}

const watchMap = computed(() => {
  const map = new Map<number, number>()
  for (const item of progress.value?.chapters ?? []) map.set(item.chapter_id, item.watched_seconds)
  return map
})

async function learn(chapterId?: number) {
  if (!auth.isAuthenticated) {
    router.push({ path: '/login', query: { redirect: route.fullPath } })
    return
  }
  router.push({ path: `/courses/${courseId.value}/learn`, query: chapterId ? { chapter_id: String(chapterId) } : {} })
}

async function load() {
  loading.value = true
  try {
    detail.value = await getCourseDetail(courseId.value)
    if (auth.isAuthenticated) {
      progress.value = await getWatchProgress(courseId.value)
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)

// 组件在同类路由间复用时不会重新挂载，需监听参数变化重新加载
watch(courseId, () => {
  if (Number.isFinite(courseId.value)) void load()
})
</script>

<template>
  <div v-loading="loading" class="detail">
    <template v-if="detail">
      <el-breadcrumb separator="/">
        <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
        <el-breadcrumb-item :to="{ path: '/courses' }">课程中心</el-breadcrumb-item>
        <el-breadcrumb-item>{{ detail.course.name }}</el-breadcrumb-item>
      </el-breadcrumb>

      <!-- 课程头图 -->
      <section class="hero">
        <div class="hero__cover" :style="coverStyle">
          <span v-if="!detail.course.cover">课程</span>
        </div>
        <div class="hero__info">
          <h1 class="hero__title">{{ detail.course.name }}</h1>
          <p class="hero__summary">{{ detail.course.short_description || '暂无课程概述' }}</p>

          <div class="hero__teachers" v-if="detail.teachers.length">
            <span v-for="teacher in detail.teachers" :key="teacher.id" class="hero__teacher">
              <el-avatar :size="28" :src="teacher.avatar ? `/api/image/${teacher.avatar}` : undefined">
                <el-icon :size="14"><User /></el-icon>
              </el-avatar>
              {{ teacher.name }}
            </span>
          </div>

          <div class="hero__stats">
            <div class="stat">
              <el-icon class="stat__icon"><Reading /></el-icon>
              <div>
                <div class="stat__value tabular">{{ chapters.length }}</div>
                <div class="stat__label">章节数</div>
              </div>
            </div>
            <div class="stat">
              <el-icon class="stat__icon"><Clock /></el-icon>
              <div>
                <div class="stat__value tabular">{{ formatDuration(detail.total_duration) }}</div>
                <div class="stat__label">课程总时长</div>
              </div>
            </div>
            <div class="stat" v-if="auth.isAuthenticated">
              <div class="stat__value tabular">{{ progressPercent }}%</div>
              <div class="stat__label">已完成</div>
            </div>
          </div>

          <div class="hero__actions">
            <el-button type="primary" size="large" @click="learn()">
              {{ progressPercent > 0 ? '继续学习' : '开始学习' }}
            </el-button>
          </div>
        </div>
      </section>

      <!-- 课程介绍 -->
      <section v-if="detail.course.description" class="panel">
        <h2 class="panel__title">课程介绍</h2>
        <div class="richtext" v-html="detail.course.description" />
      </section>

      <!-- 章节列表 -->
      <section class="panel">
        <div class="panel__head">
          <h2 class="panel__title">章节列表</h2>
          <span class="panel__hint">共 {{ chapters.length }} 个章节</span>
        </div>
        <el-table v-if="chapters.length" :data="chapters" row-key="id">
          <el-table-column label="章节" min-width="80">
            <template #default="{ $index }">
              <span class="chapter-index">{{ String($index + 1).padStart(2, '0') }}</span>
            </template>
          </el-table-column>
          <el-table-column label="标题" min-width="220">
            <template #default="{ row }">
              <div class="chapter-title">
                <span>{{ row.title }}</span>
                <el-tag v-if="completedSet.has(row.id)" type="success" size="small" effect="light">已完成</el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="时长 / 已学" min-width="220">
            <template #default="{ row }">
              <span class="cell-muted tabular">
                {{ formatDuration(row.duration) }} / {{ formatDuration(watchMap.get(row.id) || 0) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" align="right">
            <template #default="{ row }">
              <el-button type="primary" link @click="learn(row.id)">学习</el-button>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState v-else title="暂无章节" description="课程尚未添加章节内容" />
      </section>
    </template>

    <EmptyState v-else-if="!loading" title="课程不存在" description="该课程可能已下架">
      <el-button type="primary" @click="router.push('/courses')">返回课程中心</el-button>
    </EmptyState>
  </div>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

/* ============ 头图 ============ */
.hero {
  display: flex;
  gap: var(--space-6);
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
.hero__cover {
  display: grid;
  width: 360px;
  height: 210px;
  flex-shrink: 0;
  place-items: center;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--brand-100), var(--brand-200)) center/cover no-repeat;
  color: var(--brand-500);
  font-weight: 600;
}
.hero__info {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: var(--space-3);
}
.hero__title {
  font-size: var(--text-2xl);
  font-weight: 700;
}
.hero__summary {
  font-size: var(--text-base);
  color: var(--text-secondary);
}
.hero__teachers {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
}
.hero__teacher {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.hero__stats {
  display: flex;
  gap: var(--space-8);
  padding: var(--space-4) 0;
  border-top: 1px solid var(--border-color);
  border-bottom: 1px solid var(--border-color);
}
.stat {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.stat__icon {
  font-size: 20px;
  color: var(--brand-500);
}
.stat__value {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-strong);
}
.stat__label {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}
.hero__actions {
  margin-top: auto;
}

/* ============ 面板 ============ */
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
  margin-bottom: var(--space-4);
  font-size: var(--text-lg);
  font-weight: 700;
}
.panel__head .panel__title {
  margin-bottom: 0;
}
.panel__hint {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}
.richtext {
  line-height: 1.8;
  color: var(--text-primary);
}
.richtext :deep(img) {
  max-width: 100%;
  border-radius: var(--radius-md);
}
.chapter-index {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: var(--radius-sm);
  background: var(--slate-100);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: 600;
}
.chapter-title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-weight: 500;
  color: var(--text-strong);
}

@media (max-width: 860px) {
  .hero {
    flex-direction: column;
  }
  .hero__cover {
    width: 100%;
    height: 180px;
  }
  .hero__stats {
    gap: var(--space-5);
  }
}
</style>
