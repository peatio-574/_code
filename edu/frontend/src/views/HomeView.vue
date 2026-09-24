<script setup lang="ts">
// 首页：Hero 背景轮询、通知公告弹窗与最新课程。
import { BellFilled, Calendar, ArrowRight } from '@element-plus/icons-vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getCourses, getPublicAnnouncements, getSystemConfig, markAnnouncementsRead } from '@/api/portal'
import CourseCard from '@/components/course-card.vue'
import { formatDate } from '@/lib/labels'
import { parseBackgrounds } from '@/lib/system-config'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const config = ref<Record<string, string>>({})
const latest = ref<Record<string, any>[]>([])
const announcements = ref<Record<string, any>[]>([])
const announcementVisible = ref(false)
const bannerIndex = ref(0)
const loading = ref(true)

// 已阅读公告的本地记录，避免重复弹出
const READ_STORAGE_KEY = 'edu:announcements:read'

const backgrounds = computed<string[]>(() =>
  parseBackgrounds(config.value.homeBackgrounds ?? config.value.home_backgrounds),
)

let timer: number | undefined

function loadReadIds(): number[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(READ_STORAGE_KEY) || '[]')
    return Array.isArray(parsed) ? parsed.map((id) => Number(id)) : []
  } catch {
    return []
  }
}

function persistReadIds(ids: number[]) {
  try {
    localStorage.setItem(READ_STORAGE_KEY, JSON.stringify(Array.from(new Set(ids)).slice(-200)))
  } catch {
    // 本地存储不可用时忽略，不影响页面
  }
}

/** 点击「知道了」：把当前公告标记为已读，之后不再弹出。 */
function acknowledgeAnnouncements() {
  persistReadIds([...loadReadIds(), ...announcements.value.map((item) => Number(item.id))])
  announcementVisible.value = false
}

onMounted(async () => {
  try {
    config.value = await getSystemConfig()
    const [page, notices] = await Promise.all([getCourses({ p: 1, page_size: 6 }), getPublicAnnouncements(6)])
    // 最新课程最多展示 6 条
    latest.value = (page?.items ?? []).slice(0, 6)
    const readIds = new Set(loadReadIds())
    announcements.value = notices.filter((item) => !readIds.has(Number(item.id)))
    if (announcements.value.length) {
      announcementVisible.value = true
      // 弹窗展示即视为已阅读，上报服务端用于统计已读/待读人数
      if (auth.isAuthenticated) {
        void markAnnouncementsRead(announcements.value.map((item) => Number(item.id))).catch(() => {
          /* 上报失败不影响展示 */
        })
      }
    }
    if (backgrounds.value.length > 1) {
      timer = window.setInterval(() => {
        bannerIndex.value = (bannerIndex.value + 1) % backgrounds.value.length
      }, 6000)
    }
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="home">
    <!-- Hero -->
    <section class="hero reveal">
      <div
        v-for="(url, index) in backgrounds"
        :key="url"
        class="hero__bg"
        :class="{ active: index === bannerIndex }"
        :style="{ backgroundImage: `url(${url})` }"
      />
      <div v-if="!backgrounds.length" class="hero__bg active hero__bg--fallback" />
      <div class="hero__overlay">
        <h1 class="hero__title">专注每一次学习，记录每一步进展</h1>
        <p class="hero__subtitle">视频课程 · 题库练习 · 仿真冲刺考试</p>
        <div class="hero__actions">
          <el-button type="primary" size="large" @click="router.push('/courses')">开始学习</el-button>
          <el-button
            v-if="auth.isAuthenticated"
            size="large"
            class="hero__ghost"
            @click="router.push(auth.isAdmin ? '/admin' : '/profile')"
          >
            {{ auth.isAdmin ? '进入控制台' : '个人中心' }}
          </el-button>
        </div>
      </div>
      <div v-if="backgrounds.length > 1" class="hero__dots">
        <span
          v-for="(_, index) in backgrounds"
          :key="index"
          class="hero__dot"
          :class="{ active: index === bannerIndex }"
          @click="bannerIndex = index"
        />
      </div>
    </section>

    <!-- 最新课程 -->
    <section class="panel reveal reveal-delay-2">
      <div class="panel__head">
        <h2 class="panel__title">最新课程</h2>
        <router-link to="/courses" class="panel__more">更多<el-icon><ArrowRight /></el-icon></router-link>
      </div>
      <div v-if="latest.length" class="course-grid">
        <CourseCard
          v-for="(course, index) in latest"
          :key="course.id"
          :course="course"
          class="reveal"
          :style="{ animationDelay: `${160 + index * 70}ms` }"
        />
      </div>
      <el-empty v-else-if="!loading" description="暂无课程" />
    </section>

    <!-- 通知公告弹窗 -->
    <el-dialog
      v-model="announcementVisible"
      :lock-scroll="false"
      :close-on-click-modal="false"
      width="760px"
      top="6vh"
      append-to-body
      class="notice-dialog"
    >
      <template #header>
        <div class="notice-head">
          <span class="notice-head__icon"><el-icon :size="22"><BellFilled /></el-icon></span>
          <div class="notice-head__text">
            <h2 class="notice-head__title">通知公告</h2>
            <p class="notice-head__desc">共 {{ announcements.length }} 条公告 · 请及时查阅</p>
          </div>
        </div>
      </template>

      <div class="notice-scroll">
        <article v-for="item in announcements" :key="item.id" class="notice-item">
          <div class="notice-item__head">
            <h3 class="notice-item__title">
              <span class="notice-item__badge">公告</span>
              <span class="notice-item__text">{{ item.title }}</span>
            </h3>
            <span class="notice-item__time">
              <el-icon><Calendar /></el-icon>{{ formatDate(item.published_at || item.created_at) }}
            </span>
          </div>
          <div class="notice-item__content" v-html="item.content" />
        </article>
      </div>

      <template #footer>
        <span class="notice-foot__hint">阅后请点击右侧按钮关闭</span>
        <el-button type="primary" size="large" @click="acknowledgeAnnouncements">知道了</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  height: 100%;
  min-height: 0;
}

/* ============ Hero ============ */
.hero {
  position: relative;
  flex: 1 1 auto;
  min-height: 200px;
  border-radius: var(--radius-xl);
  overflow: hidden;
  color: #fff;
  box-shadow: var(--shadow-lg);
}
.hero__bg {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
  opacity: 0;
  transition: opacity 1s ease-in-out;
}
.hero__bg.active {
  opacity: 1;
}
.hero__bg--fallback {
  background:
    radial-gradient(700px 360px at 78% 12%, rgba(79, 127, 240, 0.55), transparent 62%),
    linear-gradient(135deg, #101b2e 0%, #1f2c45 55%, #29417d 100%);
}
.hero__overlay {
  position: relative;
  z-index: 1;
  display: flex;
  height: 100%;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-8) var(--space-6);
  background: linear-gradient(180deg, rgba(16, 27, 46, 0.5), rgba(22, 35, 59, 0.78));
  text-align: center;
}
.hero__title {
  font-size: var(--text-3xl);
  font-weight: 800;
  letter-spacing: 0.02em;
  color: #fff;
  text-shadow: 0 2px 18px rgba(0, 0, 0, 0.35);
}
.hero__subtitle {
  font-size: var(--text-md);
  color: rgba(255, 255, 255, 0.86);
  letter-spacing: 0.1em;
}
.hero__actions {
  display: flex;
  gap: var(--space-3);
  margin-top: var(--space-3);
}
.hero__ghost {
  background: rgba(255, 255, 255, 0.16);
  border-color: rgba(255, 255, 255, 0.35);
  color: #fff;
}
.hero__ghost:hover {
  background: rgba(255, 255, 255, 0.26);
  border-color: rgba(255, 255, 255, 0.6);
  color: #fff;
}
.hero__dots {
  position: absolute;
  left: 0;
  right: 0;
  bottom: var(--space-5);
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
}
.hero__dot {
  width: 10px;
  height: 10px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.4);
  cursor: pointer;
  transition: all var(--duration-base) var(--ease-out);
}
.hero__dot:hover {
  background: rgba(255, 255, 255, 0.75);
}
.hero__dot.active {
  width: 26px;
  background: linear-gradient(90deg, var(--brand-400), var(--brand-600));
  box-shadow: 0 0 12px rgba(91, 141, 239, 0.8);
}

/* ============ 面板 ============ */
.home .panel.panel {
  position: relative;
  flex: 0 0 auto;
  padding: var(--space-5) var(--space-6);
  border-radius: var(--radius-xl);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.home .panel.panel::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  background: linear-gradient(90deg, var(--brand-500), var(--brand-700) 55%, transparent);
}
.panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-5);
}
.panel__title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--text-strong);
}
.panel__title::before {
  content: '';
  width: 4px;
  height: 18px;
  border-radius: var(--radius-pill);
  background: linear-gradient(180deg, var(--brand-400), var(--brand-600));
}
.panel__more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px var(--space-3);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-pill);
  background: var(--bg-surface);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  transition: color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    background-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-base) var(--ease-out),
    transform var(--duration-fast) var(--ease-out);
}
.panel__more .el-icon {
  transition: transform var(--duration-base) var(--ease-out);
}
.panel__more:hover {
  color: var(--brand-600);
  border-color: var(--brand-200);
  background: var(--brand-50);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}
.panel__more:hover .el-icon {
  transform: translateX(3px);
}

/* ============ 公告弹窗 ============ */
/* 顶部品牌渐变头 */
.notice-dialog :deep(.el-dialog__header) {
  padding: 0;
  margin: 0;
}
.notice-head {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  background: linear-gradient(135deg, #3f6fd0 0%, #5b8def 55%, #7ba0ef 100%);
  color: #fff;
}
.notice-head__icon {
  display: grid;
  width: 46px;
  height: 46px;
  flex-shrink: 0;
  place-items: center;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.28);
}
.notice-head__title {
  font-size: var(--text-xl);
  font-weight: 700;
  color: #fff;
}
.notice-head__desc {
  margin-top: 2px;
  font-size: var(--text-sm);
  color: rgba(255, 255, 255, 0.85);
}
.notice-dialog :deep(.el-dialog__headerbtn) {
  top: var(--space-4);
  right: var(--space-4);
}
.notice-dialog :deep(.el-dialog__headerbtn .el-dialog__close) {
  color: #fff;
}
.notice-dialog :deep(.el-dialog__headerbtn:hover .el-dialog__close) {
  color: #fff;
}
/* 内容区浅灰底，衬托白色卡片 */
.notice-dialog :deep(.el-dialog__body) {
  padding: var(--space-5) var(--space-6);
  background: var(--slate-50);
}
.notice-dialog :deep(.el-dialog__footer) {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.notice-foot__hint {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}

.notice-scroll {
  display: flex;
  max-height: 56vh;
  flex-direction: column;
  gap: var(--space-4);
  overflow-y: auto;
  padding-right: var(--space-2);
}
.notice-item {
  position: relative;
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-left: 4px solid var(--brand-500);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
  transition: box-shadow var(--duration-base) var(--ease-out);
}
.notice-item:hover {
  box-shadow: var(--shadow-sm);
}
.notice-item__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding-bottom: var(--space-3);
  margin-bottom: var(--space-4);
  border-bottom: 1px dashed var(--border-color);
}
.notice-item__title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--text-strong);
}
.notice-item__badge {
  flex-shrink: 0;
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  background: var(--brand-50);
  color: var(--brand-500);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
}
.notice-item__text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.notice-item__time {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-1);
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  background: var(--slate-100);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}
.notice-item__content {
  font-size: var(--text-base);
  line-height: var(--leading-relaxed, 1.7);
  color: var(--text-primary);
  word-break: break-word;
  white-space: pre-wrap;
}
.notice-item__content :deep(img),
.notice-item__content img {
  max-width: 100%;
  border-radius: var(--radius-md);
}
.notice-item__content :deep(p) {
  margin: 0 0 var(--space-3);
}
.notice-item__content :deep(p:last-child) {
  margin-bottom: 0;
}
.notice-item__content :deep(a) {
  color: var(--brand-500);
  word-break: break-all;
}

/* ============ 课程 ============ */
/* 首页固定 6 列单行展示，保证整屏不滚动 */
.course-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--space-4);
}
.home :deep(.course-card__cover) {
  height: 140px;
}
.home :deep(.course-card__body) {
  gap: var(--space-2);
  padding: var(--space-5) var(--space-4) var(--space-4);
}
.home :deep(.course-card__title) {
  font-size: var(--text-base);
}

/* ============ 课程卡片（首页） ============ */
.home :deep(.course-card.course-card) {
  background: var(--bg-surface);
  border-color: var(--border-color);
  box-shadow: var(--shadow-xs);
}
.home :deep(.course-card.course-card:hover) {
  border-color: var(--brand-300);
  box-shadow: 0 18px 40px -18px rgba(79, 127, 240, 0.45), var(--shadow-lg);
}
.home :deep(.course-card__title) {
  color: var(--text-strong);
}
.home :deep(.course-card__meta) {
  color: var(--text-secondary);
}
.home :deep(.course-card__duration) {
  color: var(--brand-600);
}
.home :deep(.course-card__chapters) {
  color: var(--text-tertiary);
}
.home :deep(.course-card__cover) {
  background: linear-gradient(135deg, var(--brand-100), var(--brand-200)) center/cover no-repeat;
}
.home :deep(.course-card__cover-fallback) {
  color: var(--brand-500);
}
.home :deep(.course-card__badge) {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-700));
  box-shadow: 0 4px 12px -4px rgba(79, 127, 240, 0.8);
}

</style>
