<script setup lang="ts">
// 课程卡片：首页与课程中心复用，统一的封面、标题、教师与章节信息。
import { Clock, User } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { formatDuration } from '@/lib/labels'

const props = withDefaults(
  defineProps<{
    course: Record<string, any>
    /** 是否显示 NEW 标签（按发布时间判断，默认 30 天内） */
    showNew?: boolean
    newDays?: number
  }>(),
  {
    showNew: true,
    newDays: 30,
  },
)

const router = useRouter()

const coverUrl = computed(() => (props.course.cover ? `/api/image/${props.course.cover}` : ''))

const coverStyle = computed(() =>
  coverUrl.value
    ? { backgroundImage: `url(${coverUrl.value}), linear-gradient(135deg, var(--brand-100), var(--brand-200))` }
    : {},
)

const isNew = computed(() => {
  if (!props.showNew || !props.course.published_at) return false
  const seconds = Date.now() / 1000 - props.course.published_at
  return seconds >= 0 && seconds < props.newDays * 86400
})

// 总时长优先取章节时长合计，兜底课程时长字段
const totalDuration = computed(() =>
  Number(props.course.total_duration || props.course.duration || 0),
)

function open() {
  router.push(`/courses/${props.course.id}`)
}
</script>

<template>
  <article class="course-card" role="button" tabindex="0" @click="open" @keydown.enter="open">
    <div class="course-card__cover" :style="coverStyle">
      <span v-if="!coverUrl" class="course-card__cover-fallback">课程</span>
      <span v-if="isNew" class="course-card__badge">NEW</span>
    </div>
    <div class="course-card__body">
      <h3 class="course-card__title">{{ course.name }}</h3>
      <div class="course-card__meta">
        <span class="course-card__teacher">
          <el-avatar
            :size="20"
            :src="course.teacher_avatar ? `/api/image/${course.teacher_avatar}` : undefined"
          >
            <el-icon :size="12"><User /></el-icon>
          </el-avatar>
          <span>{{ course.teacher_name || '未设置教师' }}</span>
        </span>
        <span class="course-card__stats">
          <span class="course-card__duration">
            <el-icon><Clock /></el-icon>{{ formatDuration(totalDuration) }}
          </span>
          <span class="course-card__chapters">{{ course.chapter_count ?? 0 }} 章节</span>
        </span>
      </div>
    </div>
  </article>
</template>

<style scoped>
.course-card {
  position: relative;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
  overflow: hidden;
  cursor: pointer;
  transition: transform var(--duration-base) var(--ease-out),
    box-shadow var(--duration-base) var(--ease-out),
    border-color var(--duration-base) var(--ease-out);
}
/* 悬停光泽扫过 */
.course-card::after {
  content: '';
  position: absolute;
  top: 0;
  left: -70%;
  width: 55%;
  height: 100%;
  background: linear-gradient(
    100deg,
    transparent,
    rgba(255, 255, 255, 0.55),
    transparent
  );
  transform: skewX(-18deg);
  opacity: 0;
  pointer-events: none;
}
.course-card:hover {
  transform: translateY(-4px);
  border-color: var(--brand-200);
  box-shadow: 0 18px 38px -18px rgba(36, 87, 214, 0.5), var(--shadow-lg);
}
.course-card:hover::after {
  animation: card-shine 900ms var(--ease-out);
}
.course-card:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}
.course-card__cover {
  transition: transform var(--duration-slow) var(--ease-out);
}
.course-card:hover .course-card__cover {
  transform: scale(1.05);
}

@keyframes card-shine {
  0% {
    left: -70%;
    opacity: 0;
  }
  20% {
    opacity: 1;
  }
  100% {
    left: 130%;
    opacity: 0;
  }
}
.course-card__cover {
  position: relative;
  height: 148px;
  background: linear-gradient(135deg, var(--brand-100), var(--brand-200)) center/cover no-repeat;
  display: flex;
  align-items: center;
  justify-content: center;
}
.course-card__cover-fallback {
  color: var(--brand-500);
  font-size: var(--text-sm);
  font-weight: 600;
  letter-spacing: 0.2em;
}
.course-card__badge {
  position: absolute;
  top: var(--space-3);
  right: var(--space-3);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: #ef4444;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
}
.course-card__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
}
.course-card__title {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: var(--text-md);
  font-weight: 600;
  line-height: 1.4;
  color: var(--text-strong);
  min-height: 2.8em;
}
.course-card__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-top: auto;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.course-card__teacher {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}
.course-card__teacher span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.course-card__stats {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  text-align: right;
}
.course-card__duration {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--brand-600);
  font-size: var(--text-xs);
  font-weight: 600;
}
.course-card__chapters {
  color: var(--text-tertiary);
  font-size: var(--text-xs);
}
</style>
