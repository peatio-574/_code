<script setup lang="ts">
// 门户动态背景：星光闪烁 + 缓慢漂浮的光晕球 + 轻网格，随鼠标视差轻微移动，营造学习氛围。
// 仅作装饰，无交互；视差变量由外层 PortalLayout 写入 --px / --py。
interface Star {
  left: string
  top: string
  size: string
  delay: string
  duration: string
  depth: string
  opacity: string
}

// 使用固定种子生成，保证每次渲染一致、避免布局抖动
function createStars(count: number): Star[] {
  let seed = 20260924
  const rand = () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296
    return seed / 4294967296
  }
  const stars: Star[] = []
  for (let i = 0; i < count; i += 1) {
    const size = 1 + Math.round(rand() * 2.2)
    stars.push({
      left: `${(rand() * 100).toFixed(2)}%`,
      top: `${(rand() * 100).toFixed(2)}%`,
      size: `${size}px`,
      delay: `${(rand() * 6).toFixed(2)}s`,
      duration: `${(2.4 + rand() * 4).toFixed(2)}s`,
      depth: `${(8 + rand() * 26).toFixed(0)}px`,
      opacity: (0.35 + rand() * 0.5).toFixed(2),
    })
  }
  return stars
}

const stars = createStars(72)
</script>

<template>
  <div class="backdrop" aria-hidden="true">
    <span class="backdrop__orb backdrop__orb--a" />
    <span class="backdrop__orb backdrop__orb--b" />
    <span class="backdrop__orb backdrop__orb--c" />
    <span class="backdrop__orb backdrop__orb--d" />
    <span class="backdrop__grid" />
    <span class="backdrop__stars">
      <span
        v-for="(star, index) in stars"
        :key="index"
        class="backdrop__star"
        :style="{
          left: star.left,
          top: star.top,
          width: star.size,
          height: star.size,
          animationDelay: star.delay,
          animationDuration: star.duration,
          '--depth': star.depth,
          '--star-opacity': star.opacity,
        }"
      />
    </span>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.backdrop__orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.55;
  will-change: transform, translate;
  /* 视差：随鼠标偏移，系数由层级决定；滚动时整体轻移 */
  translate: calc(var(--px, 0) * var(--depth, 30px))
    calc(var(--py, 0) * var(--depth, 30px) + var(--sy, 0px));
  transition: translate 200ms var(--ease-out);
}

.backdrop__orb--a {
  --depth: 46px;
  top: -140px;
  left: -80px;
  width: 460px;
  height: 460px;
  background: radial-gradient(circle, rgba(36, 87, 214, 0.45), transparent 66%);
  animation: backdrop-float-a 22s var(--ease-out) infinite;
}
.backdrop__orb--b {
  --depth: 64px;
  top: -100px;
  right: -120px;
  width: 420px;
  height: 420px;
  background: radial-gradient(circle, rgba(14, 165, 233, 0.4), transparent 66%);
  animation: backdrop-float-b 26s var(--ease-out) infinite;
}
.backdrop__orb--c {
  --depth: 38px;
  bottom: -160px;
  left: 24%;
  width: 520px;
  height: 520px;
  background: radial-gradient(circle, rgba(2, 132, 199, 0.32), transparent 68%);
  animation: backdrop-float-c 30s var(--ease-out) infinite;
}
.backdrop__orb--d {
  --depth: 54px;
  bottom: -120px;
  right: 12%;
  width: 360px;
  height: 360px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.26), transparent 68%);
  animation: backdrop-float-a 24s var(--ease-out) infinite reverse;
}

.backdrop__grid {
  position: absolute;
  inset: -40px;
  background-image:
    linear-gradient(rgba(36, 87, 214, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(36, 87, 214, 0.07) 1px, transparent 1px);
  background-size: 46px 46px;
  -webkit-mask-image: radial-gradient(circle at 50% 26%, #000 0%, transparent 72%);
  mask-image: radial-gradient(circle at 50% 26%, #000 0%, transparent 72%);
  animation: backdrop-grid-pan 26s linear infinite;
}

/* 星光层：细小白点缓慢闪烁，随鼠标/滚动视差轻移 */
.backdrop__stars {
  position: absolute;
  inset: 0;
}
.backdrop__star {
  position: absolute;
  border-radius: 50%;
  background: radial-gradient(circle, #ffffff 0%, var(--brand-500, #4f7ff0) 45%, transparent 100%);
  box-shadow: 0 0 6px rgba(79, 127, 240, 0.8), 0 0 2px rgba(255, 255, 255, 0.9);
  opacity: 0;
  will-change: transform, opacity;
  translate: calc(var(--px, 0) * var(--depth, 16px))
    calc(var(--py, 0) * var(--depth, 16px) + var(--sy, 0px) * 0.4);
  animation-name: backdrop-twinkle;
  animation-timing-function: ease-in-out;
  animation-iteration-count: infinite;
}

@keyframes backdrop-twinkle {
  0%, 100% {
    opacity: 0;
    transform: scale(0.6);
  }
  50% {
    opacity: var(--star-opacity, 0.5);
    transform: scale(1.15);
  }
}

@keyframes backdrop-float-a {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
  50% { transform: translate3d(24px, 34px, 0) scale(1.06); }
}
@keyframes backdrop-float-b {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
  50% { transform: translate3d(-30px, 26px, 0) scale(1.08); }
}
@keyframes backdrop-float-c {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
  50% { transform: translate3d(20px, -28px, 0) scale(1.05); }
}
@keyframes backdrop-grid-pan {
  0% { background-position: 0 0, 0 0; }
  100% { background-position: 46px 46px, 46px 46px; }
}

@media (prefers-reduced-motion: reduce) {
  .backdrop__orb,
  .backdrop__grid,
  .backdrop__star {
    animation: none;
  }
  .backdrop__star {
    opacity: 0.5;
  }
}
</style>
