<script setup lang="ts">
// 登录页：左右分栏，整页铺满不滚动。
// 左侧背景图读取「首页背景」配置并每 3 秒轮询；鼠标移动/点击时在指针位置生成水波纹交互。
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, Refresh, Service } from '@element-plus/icons-vue'

import { getSystemConfig } from '@/api/portal'
import { errorMessage } from '@/lib/api'
import { parseBackgrounds, useSystemConfig } from '@/lib/system-config'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const { systemName, logo } = useSystemConfig()

const form = ref({ username: '', password: '' })
const loading = ref(false)

// 左侧背景轮询图来自「首页背景」系统配置，每 3 秒切换一次
const backgrounds = ref<string[]>([])
const ROTATE_INTERVAL = 3000
const activeIndex = ref(0)

// 左侧品牌说明项
const assurances = [
  { icon: Lock, title: '统一身份管理', detail: '账号由内部管理员创建并维护' },
  { icon: Refresh, title: '学习数据同步', detail: '课程、练习和考试进度自动保存' },
  { icon: Service, title: '遇到问题？', detail: '请联系所属机构管理员处理' },
]

// ---------- 水波纹交互 ----------
interface Ripple {
  id: number
  x: number
  y: number
  size: number
}

const ripples = ref<Ripple[]>([])
let rippleSeq = 0
let lastSpawnAt = 0
const MOVE_THROTTLE_MS = 70
const RIPPLE_LIFETIME_MS = 1100

/** 在指定坐标生成一个扩散水波纹，动画结束后自动移除。 */
function spawnRipple(x: number, y: number, size: number) {
  const id = rippleSeq++
  ripples.value.push({ id, x, y, size })
  window.setTimeout(() => {
    ripples.value = ripples.value.filter((item) => item.id !== id)
  }, RIPPLE_LIFETIME_MS)
}

/** 鼠标/手指移动：节流生成波纹，形成清晰的流动涟漪轨迹。 */
function handlePointerMove(event: PointerEvent) {
  const now = performance.now()
  if (now - lastSpawnAt < MOVE_THROTTLE_MS) return
  lastSpawnAt = now
  spawnRipple(event.clientX, event.clientY, 150)
}

/** 按下：生成更大的波纹，反馈更明显。 */
function handlePointerDown(event: PointerEvent) {
  spawnRipple(event.clientX, event.clientY, 340)
}

/** 点击：叠加一圈延迟扩散的外环，强化水波层叠感。 */
function handlePointerClick(event: PointerEvent) {
  const x = event.clientX
  const y = event.clientY
  window.setTimeout(() => spawnRipple(x, y, 260), 120)
}

let timer: number | undefined

function startRotation() {
  stopRotation()
  if (backgrounds.value.length <= 1) return
  timer = window.setInterval(() => {
    activeIndex.value = (activeIndex.value + 1) % backgrounds.value.length
  }, ROTATE_INTERVAL)
}

function stopRotation() {
  if (timer) window.clearInterval(timer)
  timer = undefined
}

onMounted(async () => {
  try {
    const config = await getSystemConfig()
    backgrounds.value = parseBackgrounds(config?.homeBackgrounds ?? config?.home_backgrounds)
  } catch {
    /* 读取失败则不展示轮播背景 */
  }
  startRotation()
})
onBeforeUnmount(stopRotation)

async function submit() {
  if (!form.value.username || !form.value.password) {
    ElMessage.error('请输入账号和密码')
    return
  }
  loading.value = true
  try {
    const result = await auth.login(form.value.username, form.value.password)
    if (!result.success) {
      ElMessage.error(result.message || '用户名或密码错误')
      return
    }
    const redirect = (route.query.redirect as string) || (auth.isAdmin ? '/admin' : '/')
    await router.push(redirect)
    ElMessage.success('欢迎回来')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main
    class="auth-page"
    @pointermove="handlePointerMove"
    @pointerdown="handlePointerDown"
    @click="handlePointerClick"
  >
    <!-- 左侧品牌区（桌面端显示）：背景轮询 + 说明 -->
    <section class="auth-hero">
      <div class="hero-bg" aria-hidden="true">
        <div
          v-for="(url, index) in backgrounds"
          :key="url"
          class="hero-bg-layer"
          :class="{ active: index === activeIndex }"
          :style="{ backgroundImage: `url(${url})` }"
        />
        <div class="hero-bg-mask" />
      </div>
      <div class="hero-ring hero-ring-top" aria-hidden="true" />
      <div class="hero-ring hero-ring-bottom" aria-hidden="true" />

      <div class="hero-inner">
        <h1 class="hero-title">专注每一次学习，记录每一步进展</h1>
        <div class="hero-assurances">
          <div v-for="item in assurances" :key="item.title" class="hero-assurance">
            <el-icon class="hero-assurance-icon"><component :is="item.icon" /></el-icon>
            <h2>{{ item.title }}</h2>
            <p>{{ item.detail }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- 右侧登录区：装饰圆 + 居中卡片 -->
    <section class="auth-panel">
      <div class="paper-circle paper-circle-top" aria-hidden="true" />
      <div class="paper-circle paper-circle-bottom" aria-hidden="true" />

      <div class="auth-card">
        <router-link to="/" class="auth-logo">
          <span class="auth-logo-mark">
            <img v-if="logo" :src="`/api/image/${logo}`" :alt="systemName" />
            <span v-else>{{ systemName.slice(0, 1) }}</span>
          </span>
          <span class="auth-logo-text">{{ systemName }}</span>
        </router-link>

        <p class="auth-eyebrow">账号登录</p>
        <h2 class="auth-heading">欢迎回来</h2>

        <el-form label-position="top" class="auth-form" @submit.prevent="submit">
          <el-form-item label="账号">
            <el-input
              v-model="form.username"
              size="large"
              placeholder="请输入账号"
              autocomplete="username"
              autofocus
            />
          </el-form-item>
          <el-form-item>
            <template #label>
              <div class="auth-label-row">
                <span>密码</span>
                <span class="auth-hint">忘记密码请联系管理员</span>
              </div>
            </template>
            <el-input
              v-model="form.password"
              type="password"
              size="large"
              placeholder="请输入密码"
              show-password
              autocomplete="current-password"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button
            type="primary"
            class="auth-submit"
            :loading="loading"
            @click="submit"
          >
            {{ loading ? '正在登录' : '登录' }}
          </el-button>
        </el-form>

        <div class="auth-terms">
          登录即表示你同意
          <a href="/user-agreement" target="_blank" rel="noopener noreferrer">用户协议</a>
          和
          <a href="/privacy-policy" target="_blank" rel="noopener noreferrer">隐私政策</a>
        </div>
      </div>
    </section>

    <!-- 水波纹层：不拦截鼠标事件，覆盖整页 -->
    <div class="ripple-layer" aria-hidden="true">
      <span
        v-for="item in ripples"
        :key="item.id"
        class="ripple"
        :style="{ left: `${item.x}px`, top: `${item.y}px`, width: `${item.size}px`, height: `${item.size}px` }"
      />
    </div>
  </main>
</template>

<style scoped>
/* 整页铺满，禁止滚动 */
:global(html),
:global(body) {
  height: 100%;
  margin: 0;
  overflow: hidden;
}

.auth-page {
  position: relative;
  display: grid;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--bg-app);
  color: var(--text-primary);
}
/* 统一盒模型，避免 padding 撑出视口导致 1~2px 溢出 */
.auth-page,
.auth-page * {
  box-sizing: border-box;
}

/* ================= 左侧品牌区 ================= */
.auth-hero {
  position: relative;
  display: none;
  overflow: hidden;
  border-right: 1px solid var(--border-color);
  background: linear-gradient(160deg, #1f2c45, #101b2e);
  color: #fff;
}
.hero-bg {
  position: absolute;
  inset: 0;
}
.hero-bg-layer {
  position: absolute;
  inset: 0;
  background-position: center;
  background-size: cover;
  opacity: 0;
  transition: opacity 1s ease-in-out;
}
.hero-bg-layer.active {
  opacity: 1;
}
.hero-bg-mask {
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(8, 13, 22, 0.95), rgba(22, 38, 63, 0.88), rgba(10, 15, 24, 0.96));
}
.hero-ring {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
}
.hero-ring-top {
  top: -6rem;
  left: -5rem;
  width: 20rem;
  height: 20rem;
  border: 52px solid rgba(255, 255, 255, 0.04);
}
.hero-ring-bottom {
  right: -7rem;
  bottom: -9rem;
  width: 30rem;
  height: 30rem;
  border: 72px solid rgba(91, 141, 239, 0.14);
}
.hero-inner {
  position: relative;
  z-index: 1;
  display: flex;
  width: 100%;
  max-width: 46rem;
  height: 100%;
  margin: 0 auto;
  flex-direction: column;
  padding: 2.5rem 3rem 3.5rem;
}
/* 标题占满剩余空间并垂直居中，说明区固定在底部 */
.hero-title {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  max-width: 40rem;
  margin: 0 auto;
  font-size: 2.25rem;
  line-height: 1.2;
  font-weight: 700;
  letter-spacing: -0.035em;
  text-align: center;
  color: #ffffff;
  text-shadow: 0 2px 18px rgba(0, 0, 0, 0.45);
}
.hero-assurances {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
}
.hero-assurance {
  border-top: 1px solid rgba(255, 255, 255, 0.28);
  padding-top: 1rem;
  text-align: center;
}
.hero-assurance-icon {
  font-size: 1.25rem;
  color: #7ba0ef;
}
.hero-assurance h2 {
  margin: 0.75rem 0 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: #ffffff;
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.4);
}
.hero-assurance p {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  line-height: 1.25rem;
  color: rgba(255, 255, 255, 0.82);
}

/* ================= 右侧登录区 ================= */
.auth-panel {
  position: relative;
  display: flex;
  height: 100%;
  align-items: center;
  overflow: hidden;
  padding: 1.5rem 1rem;
}
.paper-circle {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
}
.paper-circle-top {
  top: 8%;
  right: -6rem;
  width: 16rem;
  height: 16rem;
  background: radial-gradient(circle, rgba(79, 127, 240, 0.14), transparent 70%);
}
.paper-circle-bottom {
  bottom: 6%;
  left: -5rem;
  width: 11rem;
  height: 11rem;
  border: 28px solid rgba(79, 127, 240, 0.1);
}
.auth-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 460px;
  margin: 0 auto;
  padding: 1.5rem;
  border: 1px solid var(--border-color);
  border-radius: 1rem;
  background: var(--bg-surface);
  box-shadow: 0 24px 60px -30px rgba(31, 44, 69, 0.28);
}

.auth-logo {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 2rem;
  width: fit-content;
  text-decoration: none;
  color: inherit;
}
.auth-logo-mark {
  display: grid;
  width: 2.5rem;
  height: 2.5rem;
  place-items: center;
  border-radius: 0.5rem;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-700));
  color: #fff;
  font-weight: 700;
  overflow: hidden;
}
.auth-logo-mark img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.auth-logo-text {
  font-size: 1.125rem;
  font-weight: 700;
}

.auth-eyebrow {
  margin: 0 0 0.5rem;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--brand-600);
}
.auth-heading {
  margin: 0 0 1.5rem;
  font-size: 1.875rem;
  font-weight: 700;
  letter-spacing: -0.025em;
}
.auth-form :deep(.el-form-item) {
  margin-bottom: 1.25rem;
}
.auth-form :deep(.el-input__wrapper) {
  height: 3rem;
  border-radius: 0.5rem;
}
.auth-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 1rem;
}
.auth-hint {
  font-size: 0.75rem;
  font-weight: 400;
  color: var(--text-tertiary);
}
.auth-submit {
  width: 100%;
  height: 3rem;
  border-radius: 0.5rem;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border-color: transparent;
  font-size: 1rem;
  font-weight: 600;
  box-shadow: 0 10px 24px -12px rgba(79, 127, 240, 0.8);
}
.auth-submit:hover {
  background: linear-gradient(135deg, var(--brand-400), var(--brand-500));
  border-color: transparent;
}
.auth-terms {
  margin-top: 1.5rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--border-color);
  text-align: center;
  font-size: 0.75rem;
  color: var(--text-tertiary);
}
.auth-terms a {
  color: var(--brand-600);
  text-decoration: underline;
  text-underline-offset: 4px;
}

/* ================= 水波纹 ================= */
.ripple-layer {
  position: fixed;
  inset: 0;
  z-index: 60;
  overflow: hidden;
  pointer-events: none;
}
.ripple {
  position: absolute;
  border-radius: 50%;
  border: 2px solid rgba(79, 127, 240, 0.45);
  background: radial-gradient(
    circle,
    rgba(79, 127, 240, 0.18) 0%,
    rgba(79, 127, 240, 0.08) 46%,
    rgba(79, 127, 240, 0.02) 64%,
    transparent 78%
  );
  box-shadow: 0 0 16px rgba(79, 127, 240, 0.22);
  transform: translate(-50%, -50%) scale(0.2);
  animation: ripple-expand 1100ms cubic-bezier(0.22, 0.61, 0.36, 1) forwards;
  will-change: transform, opacity;
}
@keyframes ripple-expand {
  0% {
    transform: translate(-50%, -50%) scale(0.2);
    opacity: 0.75;
  }
  60% {
    opacity: 0.4;
  }
  100% {
    transform: translate(-50%, -50%) scale(2.1);
    opacity: 0;
  }
}

/* ================= 响应式 ================= */
@media (min-width: 640px) {
  .auth-panel {
    padding: 2rem;
  }
  .auth-card {
    padding: 2.25rem;
  }
}
@media (min-width: 1024px) {
  .auth-page {
    grid-template-columns: minmax(0, 1fr) minmax(460px, 42%);
  }
  .auth-hero {
    display: flex;
  }
  .auth-panel {
    padding: 2.5rem 3rem;
  }
  .auth-logo {
    display: none;
  }
}

/* 低高度窗口压缩间距，保证不滚动 */
@media (max-height: 760px) {
  .hero-inner {
    padding: 1.75rem 2.5rem 2.25rem;
  }
  .hero-title {
    font-size: 1.75rem;
  }
  .auth-logo {
    margin-bottom: 1.25rem;
  }
  .auth-heading {
    margin-bottom: 1.25rem;
  }
  .auth-card {
    padding: 1.75rem;
  }
  .auth-terms {
    margin-top: 1.25rem;
    padding-top: 1rem;
  }
}
</style>
