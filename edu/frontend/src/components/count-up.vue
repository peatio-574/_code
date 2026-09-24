<script setup lang="ts">
// 数字滚动动效：数值变化时从当前值缓动到目标值，用于统计类指标。
import { onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    value: number
    /** 动画时长（毫秒） */
    duration?: number
    /** 小数位数 */
    decimals?: number
  }>(),
  {
    duration: 900,
    decimals: 0,
  },
)

const display = ref(0)
let raf = 0
let startedAt = 0
let from = 0

// 尊重「减少动态效果」系统偏好，直接显示终值
const reduced =
  typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false

function easeOutCubic(t: number) {
  return 1 - Math.pow(1 - t, 3)
}

function run(target: number) {
  const to = Number.isFinite(target) ? target : 0
  if (reduced) {
    display.value = to
    return
  }
  cancelAnimationFrame(raf)
  from = display.value
  startedAt = performance.now()
  const step = (now: number) => {
    const progress = Math.min((now - startedAt) / props.duration, 1)
    display.value = from + (to - from) * easeOutCubic(progress)
    if (progress < 1) raf = requestAnimationFrame(step)
    else display.value = to
  }
  raf = requestAnimationFrame(step)
}

watch(
  () => props.value,
  (value) => run(Number(value)),
  { immediate: true },
)

onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <span class="count-up tabular">{{ display.toFixed(decimals) }}</span>
</template>
