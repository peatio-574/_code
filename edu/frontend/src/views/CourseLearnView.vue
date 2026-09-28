<script setup lang="ts">
// 视频学习：断点续播、心跳上报、右侧章节切换。
import { ArrowLeft, CircleCheckFilled, DArrowLeft, DArrowRight, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import {
  getCourseDetail,
  getWatchProgress,
  startLearning,
  watchFinish,
  watchProgress,
  watchStart,
} from '@/api/portal'
import EmptyState from '@/components/empty-state.vue'
import { errorMessage } from '@/lib/api'

const route = useRoute()
const router = useRouter()

const detail = ref<Record<string, any> | null>(null)
const progress = ref<Record<string, any> | null>(null)
const currentChapterId = ref<number>(0)
const videoRef = ref<HTMLVideoElement | null>(null)
const sessionId = ref<number>(0)
const sequence = ref(0)
const lastPosition = ref(0)
const lastReportedAt = ref(0)
let heartbeat: number | undefined

// 播放控制：播放/暂停、进度、倍数
const isPlaying = ref(false)
const playbackRate = ref(1)
const currentSeconds = ref(0)
const durationSeconds = ref(0)
const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5, 2]

const courseId = computed(() => Number(route.params.courseId))
const chapters = computed<Record<string, any>[]>(() => detail.value?.chapters ?? [])
const currentChapter = computed(() => chapters.value.find((c: any) => c.id === currentChapterId.value) ?? null)

const completedSet = computed(() => {
  const set = new Set<number>()
  for (const item of progress.value?.chapters ?? []) if (item.completed) set.add(item.chapter_id)
  return set
})

// 各章节已学习时长（秒）
const watchedMap = computed(() => {
  const map = new Map<number, number>()
  for (const item of progress.value?.chapters ?? []) {
    map.set(item.chapter_id, item.watched_seconds || 0)
  }
  return map
})

// 当前章节已学习时长（秒）
const currentWatched = computed(() => watchedMap.value.get(currentChapterId.value) || 0)

const completedCount = computed(() => completedSet.value.size)

const progressPercent = computed(() => {
  const total = chapters.value.filter((chapter) => chapter.file).length || chapters.value.length
  if (!total) return 0
  return Math.round((completedCount.value / total) * 100)
})

function videoUrl(file: string) {
  return file ? `/api/video/${file}` : ''
}

function formatDuration(seconds: number) {
  const total = Math.round(seconds || 0)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

async function loadProgress() {
  progress.value = await getWatchProgress(courseId.value)
}

async function beginSession() {
  const chapter = currentChapter.value
  const video = videoRef.value
  if (!chapter || !video) return
  try {
    const result = await watchStart({
      course_id: courseId.value,
      chapter_id: chapter.id,
      client_session_id: `web-${chapter.id}-${Date.now()}`,
    })
    sessionId.value = result?.watch_session_id ?? 0
    sequence.value = 0
    if (result?.resume_seconds && result.resume_seconds > 0 && !result.completed) {
      video.currentTime = result.resume_seconds
    }
    startHeartbeat()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

function startHeartbeat() {
  stopHeartbeat()
  heartbeat = window.setInterval(reportNow, 15000)
}

function stopHeartbeat() {
  if (heartbeat) window.clearInterval(heartbeat)
  heartbeat = undefined
}

async function reportNow(event = 'heartbeat') {
  const video = videoRef.value
  if (!video || !sessionId.value) return
  sequence.value += 1
  lastPosition.value = video.currentTime
  lastReportedAt.value = Date.now()
  try {
    await watchProgress({
      watch_session_id: sessionId.value,
      position_seconds: Math.floor(video.currentTime),
      video_duration_seconds: Math.floor(video.duration || 0),
      sequence: sequence.value,
      event,
    })
  } catch {
    /* 心跳失败不打断播放 */
  }
}

async function finishSession() {
  if (!sessionId.value) return
  const video = videoRef.value
  try {
    await watchFinish({ watch_session_id: sessionId.value, position_seconds: video ? Math.floor(video.currentTime) : undefined })
  } catch {
    /* ignore */
  }
  sessionId.value = 0
  stopHeartbeat()
  await loadProgress()
}

async function switchChapter(chapterId: number) {
  if (chapterId === currentChapterId.value) return
  await finishSession()
  currentChapterId.value = chapterId
  const video = videoRef.value
  if (video) {
    video.load()
  }
}

/** 章节列表「学习」按钮：切到该章节并自动播放。 */
async function playChapter(chapterId: number) {
  if (chapterId !== currentChapterId.value) {
    await switchChapter(chapterId)
  }
  const video = videoRef.value
  if (video) {
    try {
      await video.play()
    } catch {
      /* 浏览器可能因自动播放策略拒绝，忽略 */
    }
  }
}

async function onLoadedMetadata() {
  const video = videoRef.value
  if (!video) return
  video.playbackRate = playbackRate.value
  durationSeconds.value = Math.floor(video.duration || 0)
  const recorded = progress.value?.chapters?.find((c: any) => c.chapter_id === currentChapterId.value)
  if (recorded && !recorded.completed && recorded.last_position_seconds > 0) {
    video.currentTime = recorded.last_position_seconds
  }
}

function onPlay() {
  isPlaying.value = true
  if (!sessionId.value) beginSession()
}

function onPause() {
  isPlaying.value = false
  reportNow('pause')
}

function onTimeUpdate() {
  const video = videoRef.value
  if (!video) return
  currentSeconds.value = Math.floor(video.currentTime)
  if (video.duration) durationSeconds.value = Math.floor(video.duration)
}

/** 播放/暂停。 */
async function togglePlay() {
  const video = videoRef.value
  if (!video) return
  if (video.paused) {
    try {
      await video.play()
    } catch {
      /* 自动播放被拒绝时忽略 */
    }
  } else {
    video.pause()
  }
}

/** 快进/快退（秒）。 */
function seekBy(seconds: number) {
  const video = videoRef.value
  if (!video) return
  const duration = video.duration || 0
  video.currentTime = Math.min(Math.max(video.currentTime + seconds, 0), duration || Infinity)
  void reportNow('seek')
}

/** 设置播放倍数。 */
function setRate(rate: number) {
  playbackRate.value = rate
  const video = videoRef.value
  if (video) video.playbackRate = rate
}

function handleBeforeUnload() {
  if (sessionId.value) {
    const video = videoRef.value
    navigator.sendBeacon?.(
      '/api/learning/watch/finish',
      new Blob([JSON.stringify({ watch_session_id: sessionId.value, position_seconds: video ? Math.floor(video.currentTime) : 0 })], {
        type: 'application/json',
      }),
    )
  }
}

/**
 * 选择进入学习的章节：
 * 1. 指定 chapter_id（章节列表点进来）；
 * 2. 上次学习的章节未完成 → 续播该章节；
 * 3. 上次章节已完成 → 定位到第一个未完成章节；
 * 4. 兜底第一个章节。
 */
function pickInitialChapter(): number {
  const queryChapter = Number(route.query.chapter_id)
  if (queryChapter) return queryChapter
  if (!chapters.value.length) return 0
  const lastId = Number(progress.value?.last_chapter_id || 0)
  if (lastId && !completedSet.value.has(lastId)) return lastId
  const firstUnfinished = chapters.value.find((c) => !completedSet.value.has(c.id))
  return firstUnfinished?.id ?? lastId ?? chapters.value[0].id
}

onMounted(async () => {
  detail.value = await getCourseDetail(courseId.value)
  try {
    await loadProgress()
  } catch {
    /* 进度读取失败不阻断学习 */
  }
  currentChapterId.value = pickInitialChapter()
  await startLearning(courseId.value)
  window.addEventListener('beforeunload', handleBeforeUnload)
})

onBeforeUnmount(async () => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  await finishSession()
})
</script>

<template>
  <div v-if="detail" class="learn">
    <header class="learn-header">
      <div class="learn-header__left">
        <el-button text :icon="ArrowLeft" @click="router.push(`/courses/${courseId}`)">返回课程</el-button>
        <span class="learn-header__divider" />
        <span class="learn-header__title">{{ detail.course.name }}</span>
      </div>
      <div class="learn-header__progress">
        <span class="cell-muted">已完成 {{ progressPercent }}%</span>
        <el-progress :percentage="progressPercent" :show-text="false" :stroke-width="6" class="learn-header__bar" />
      </div>
    </header>

    <div class="learn-body">
      <section class="player">
        <div class="player__stage">
          <video
            v-if="currentChapter"
            ref="videoRef"
            class="video"
            controls
            :src="videoUrl(currentChapter.file)"
            @loadedmetadata="onLoadedMetadata"
            @play="onPlay"
            @pause="onPause"
            @timeupdate="onTimeUpdate"
            @seeking="() => reportNow('seek')"
            @ended="() => { reportNow('ended'); finishSession() }"
          />
          <EmptyState v-else title="暂无视频" description="该课程尚未上传视频章节" />
        </div>
        <div v-if="currentChapter" class="player__controls">
          <div class="player__control-group">
            <el-button
              circle
              :icon="isPlaying ? VideoPause : VideoPlay"
              class="control-btn control-btn--primary"
              @click="togglePlay"
            />
            <el-button circle :icon="DArrowLeft" class="control-btn" title="快退 10 秒" @click="seekBy(-10)" />
            <el-button circle :icon="DArrowRight" class="control-btn" title="快进 10 秒" @click="seekBy(10)" />
          </div>
          <span class="player__time tabular">
            {{ formatDuration(currentSeconds) }} / {{ formatDuration(durationSeconds || currentChapter.duration) }}
          </span>
          <div class="player__rate">
            <span class="player__rate-label">倍数</span>
            <el-select
              :model-value="playbackRate"
              size="small"
              class="player__rate-select"
              @change="setRate"
            >
              <el-option v-for="rate in PLAYBACK_RATES" :key="rate" :label="`${rate}x`" :value="rate" />
            </el-select>
          </div>
        </div>
        <div class="player__info">
          <h3 class="player__title">{{ currentChapter?.title || '—' }}</h3>
          <span v-if="currentChapter" class="player__meta tabular">
            <span class="player__meta-item">
              已学习 <b>{{ formatDuration(currentWatched) }}</b> / {{ formatDuration(currentChapter.duration) }}
            </span>
          </span>
        </div>
      </section>

      <aside class="chapters">
        <div class="chapters__head">
          <h3>章节列表</h3>
          <span class="cell-muted">{{ completedCount }} / {{ chapters.length }}</span>
        </div>
        <ul class="chapters__list">
          <li
            v-for="(chapter, index) in chapters"
            :key="chapter.id"
            :class="{ active: chapter.id === currentChapterId }"
            @click="switchChapter(chapter.id)"
          >
            <span class="chapter-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <div class="chapter-main">
              <span class="chapter-name">{{ chapter.title }}</span>
              <span class="chapter-time tabular">
                <el-icon v-if="completedSet.has(chapter.id)" class="chapter-check"><CircleCheckFilled /></el-icon>
                <template v-else>
                  已学习 {{ formatDuration(watchedMap.get(chapter.id) || 0) }} / {{ formatDuration(chapter.duration) }}
                </template>
              </span>
            </div>
            <el-button
              link
              type="primary"
              class="chapter-learn"
              @click.stop="playChapter(chapter.id)"
            >
              学习
            </el-button>
          </li>
        </ul>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.learn {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.learn-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
}
.learn-header__left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.learn-header__divider {
  width: 1px;
  height: 18px;
  background: var(--border-color);
}
.learn-header__title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.learn-header__progress {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 220px;
}
.learn-header__bar {
  flex: 1;
}

.learn-body {
  display: flex;
  gap: var(--space-4);
  align-items: flex-start;
}
.player {
  flex: 1;
  min-width: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
/* 视频区上下加大：更宽阔的播放舞台 */
.player__stage {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 520px;
  background: #0b1220;
}
.video {
  width: 100%;
  max-height: 78vh;
  display: block;
  background: #000;
}
/* 自定义播放控制栏 */
.player__controls {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--border-color);
  background: var(--slate-25);
}
.player__control-group {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.control-btn {
  font-size: 18px;
}
.control-btn--primary {
  font-size: 22px;
}
.player__time {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.player__rate {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-left: auto;
}
.player__rate-label {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
}
.player__rate-select {
  width: 92px;
}
.player__info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-top: 1px solid var(--border-color);
}
.player__title {
  font-size: var(--text-md);
  font-weight: 600;
}
.player__meta {
  flex-shrink: 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.player__meta-item b {
  color: var(--brand-600);
  font-weight: 700;
}

.chapters {
  display: flex;
  width: 340px;
  flex-shrink: 0;
  flex-direction: column;
  max-height: calc(78vh + 88px);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.chapters__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border-color);
}
.chapters__head h3 {
  font-size: var(--text-base);
  font-weight: 700;
}
.chapters__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  list-style: none;
  margin: 0;
  padding: var(--space-2);
}
.chapters__list li {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: var(--text-sm);
  transition: background-color var(--duration-fast) var(--ease-out);
}
.chapters__list li:hover {
  background: var(--slate-50);
}
.chapters__list li.active {
  background: var(--brand-50);
  color: var(--brand-500);
  font-weight: 600;
}
.chapter-index {
  width: 24px;
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}
.chapters__list li.active .chapter-index {
  color: var(--brand-500);
}
.chapter-main {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.chapter-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chapter-time {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
.chapter-check {
  color: var(--success);
  font-size: 15px;
}
.chapter-learn {
  flex-shrink: 0;
  font-weight: 600;
}

@media (max-width: 1024px) {
  .learn-body {
    flex-direction: column;
  }
  .chapters {
    width: 100%;
    max-height: 420px;
  }
}
</style>

