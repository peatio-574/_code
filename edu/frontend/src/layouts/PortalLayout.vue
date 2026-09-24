<script setup lang="ts">
// 门户壳层：顶部导航（首页/课程/题库/考试/个人中心/控制台）+ 页脚。
import {
  ArrowDown,
  EditPen,
  HomeFilled,
  Link,
  Monitor,
  Reading,
  SwitchButton,
  TopRight,
  Trophy,
  User,
} from '@element-plus/icons-vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import PortalBackdrop from '@/components/portal-backdrop.vue'
import { useSystemConfig } from '@/lib/system-config'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const { systemName, logo, friendLinks } = useSystemConfig()

// 鼠标视差：把归一化位移写入 --px / --py，仅供背景光晕使用（轮播图不参与）
const shellEl = ref<HTMLElement | null>(null)
let parallaxRaf = 0
let targetX = 0
let targetY = 0
let currentX = 0
let currentY = 0
const reducedMotion =
  typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false

function applyParallax() {
  currentX += (targetX - currentX) * 0.09
  currentY += (targetY - currentY) * 0.09
  const el = shellEl.value
  if (el) {
    el.style.setProperty('--px', currentX.toFixed(3))
    el.style.setProperty('--py', currentY.toFixed(3))
  }
  if (Math.abs(targetX - currentX) > 0.002 || Math.abs(targetY - currentY) > 0.002) {
    parallaxRaf = requestAnimationFrame(applyParallax)
  } else {
    parallaxRaf = 0
  }
}

function onPointerMove(event: MouseEvent) {
  if (reducedMotion) return
  const width = window.innerWidth || 1
  const height = window.innerHeight || 1
  targetX = (event.clientX / width - 0.5) * 2
  targetY = (event.clientY / height - 0.5) * 2
  if (!parallaxRaf) parallaxRaf = requestAnimationFrame(applyParallax)
}

// 滚动视差：滚动进度写入 --sy，背景光晕随之轻移
let scrollRaf = 0
function onScroll() {
  if (reducedMotion || scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    const el = shellEl.value
    if (el) {
      const progress = Math.min(window.scrollY / (window.innerHeight || 1), 2.5)
      el.style.setProperty('--sy', `${(progress * 26).toFixed(1)}px`)
    }
    scrollRaf = 0
  })
}

onMounted(() => {
  window.addEventListener('mousemove', onPointerMove, { passive: true })
  window.addEventListener('scroll', onScroll, { passive: true })
})
onBeforeUnmount(() => {
  window.removeEventListener('mousemove', onPointerMove)
  window.removeEventListener('scroll', onScroll)
  if (parallaxRaf) cancelAnimationFrame(parallaxRaf)
  if (scrollRaf) cancelAnimationFrame(scrollRaf)
})

const isAuthenticated = computed(() => auth.isAuthenticated)
const isAdmin = computed(() => auth.isAdmin)
const displayName = computed(() => auth.user?.display_name || auth.user?.username || '')
// 首页固定为整屏布局，不产生页面滚动
const isHome = computed(() => route.name === 'home')

const baseLinks = [
  { label: '首页', to: '/', icon: HomeFilled },
  { label: '课程中心', to: '/courses', icon: Reading },
  { label: '题库练习', to: '/question', icon: EditPen },
  { label: '冲刺考试', to: '/exams', icon: Trophy },
]

// 管理员/超管在「冲刺考试」后追加控制台入口
const portalLinks = computed(() =>
  isAdmin.value ? [...baseLinks, { label: '控制台', to: '/admin', icon: Monitor }] : baseLinks,
)

/**
 * 精确判断导航项激活状态。
 * 不用 router-link-active：首页 '/' 是所有路由的祖先，会导致首页永远高亮。
 */
function isActive(to: string) {
  if (to === '/') return route.path === '/'
  return route.path === to || route.path.startsWith(`${to}/`)
}

/** 补全协议，避免友情链接被当作站内相对地址。 */
function normalizeUrl(url: string) {
  return /^https?:\/\//i.test(url) ? url : `https://${url}`
}

async function handleLogout() {
  await auth.logout()
  await router.push('/login')
}

function handleCommand(command: string) {
  if (command === 'profile') void router.push('/profile')
  if (command === 'logout') void handleLogout()
}
</script>

<template>
  <div ref="shellEl" class="portal-shell" :class="{ 'is-home': isHome }">
    <PortalBackdrop />
    <header class="portal-header">
      <div class="portal-topbar">
        <router-link to="/" class="brand">
          <span class="brand__mark">
            <img v-if="logo" :src="`/api/image/${logo}`" :alt="systemName" />
            <span v-else>{{ systemName.slice(0, 1) }}</span>
          </span>
          <span class="brand__text">{{ systemName }}</span>
        </router-link>

        <nav class="portal-nav">
          <router-link
            v-for="link in portalLinks"
            :key="link.to"
            :to="link.to"
            class="nav-link"
            active-class="nav-link--ignore"
            exact-active-class="nav-link--ignore"
            :class="{ 'nav-link--active': isActive(link.to), 'nav-link--console': link.to === '/admin' }"
          >
            <el-icon class="nav-link__icon"><component :is="link.icon" /></el-icon>
            <span class="nav-link__label">{{ link.label }}</span>
          </router-link>
        </nav>

        <div class="portal-actions">
          <el-dropdown v-if="isAuthenticated" trigger="click" @command="handleCommand">
            <button type="button" class="account">
              <el-avatar :size="32" :src="auth.user?.avatar ? `/api/image/${auth.user.avatar}` : undefined">
                {{ displayName.slice(0, 1) }}
              </el-avatar>
              <span class="account__name">{{ displayName }}</span>
              <el-icon class="account__caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile" :icon="User">个人中心</el-dropdown-item>
                <el-dropdown-item command="logout" :icon="SwitchButton" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button v-else type="primary" @click="router.push('/login')">登录</el-button>
        </div>
      </div>
    </header>

    <main class="portal-main">
      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>

    <footer v-if="friendLinks.length" class="portal-footer">
      <div class="portal-footer__inner">
        <div class="portal-footer__links">
          <span class="portal-footer__links-label">友情链接</span>
          <span class="portal-footer__links-list">
            <el-tooltip
              v-for="link in friendLinks"
              :key="link.url"
              :content="link.url"
              placement="top"
              effect="dark"
              :show-after="150"
            >
              <a
                :href="normalizeUrl(link.url)"
                target="_blank"
                rel="noopener noreferrer"
                class="footer-link"
              >
                <el-icon class="footer-link__icon"><Link /></el-icon>
                <span class="footer-link__name">{{ link.name }}</span>
                <el-icon class="footer-link__arrow"><TopRight /></el-icon>
              </a>
            </el-tooltip>
          </span>
        </div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.portal-shell {
  position: relative;
  display: flex;
  min-height: 100vh;
  flex-direction: column;
  background-color: var(--bg-app);
  background-image: var(--bg-app-gradient);
  background-repeat: no-repeat;
  background-attachment: fixed;
}
/* 首页整屏固定：内容刚好占满可视区，不出现页面滚动条 */
.portal-shell.is-home {
  height: 100vh;
  min-height: 0;
  overflow: hidden;
}
.portal-shell.is-home .portal-main {
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  padding-top: var(--space-5);
  padding-bottom: var(--space-5);
}
.portal-shell.is-home .portal-main :deep(.home) {
  flex: 1;
  min-height: 0;
}

/* ============ 门户浅色主题（米白 + 青瓷蓝） ============ */
.portal-shell {
  background-image:
    radial-gradient(1100px 520px at 8% -10%, rgba(79, 127, 240, 0.1), transparent 60%),
    radial-gradient(900px 500px at 96% 0%, rgba(79, 127, 240, 0.07), transparent 58%),
    var(--bg-app-gradient);
}
.portal-shell :deep(.backdrop) {
  opacity: 0.75;
}
.portal-shell :deep(.backdrop__orb--a) {
  background: radial-gradient(circle, rgba(79, 127, 240, 0.26), transparent 66%);
}
.portal-shell :deep(.backdrop__orb--b) {
  background: radial-gradient(circle, rgba(111, 149, 235, 0.22), transparent 66%);
}
.portal-shell :deep(.backdrop__orb--c) {
  background: radial-gradient(circle, rgba(79, 127, 240, 0.18), transparent 68%);
}
.portal-shell :deep(.backdrop__orb--d) {
  background: radial-gradient(circle, rgba(41, 65, 125, 0.14), transparent 68%);
}
.portal-shell :deep(.backdrop__grid) {
  background-image:
    linear-gradient(rgba(79, 127, 240, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(79, 127, 240, 0.05) 1px, transparent 1px);
}
.portal-header {
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(14px) saturate(150%);
  border-bottom: 1px solid var(--border-color);
  box-shadow: 0 8px 24px -20px rgba(15, 26, 46, 0.65);
}
.portal-topbar {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  width: 100%;
  max-width: var(--portal-content-max);
  height: var(--header-height);
  margin: 0 auto;
  padding: 0 var(--space-6);
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  text-decoration: none;
  white-space: nowrap;
}
.brand__mark {
  display: grid;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  place-items: center;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-700));
  color: #fff;
  font-size: var(--text-md);
  font-weight: 700;
  overflow: hidden;
}
.brand__mark img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.brand__text {
  font-size: var(--text-xl);
  font-weight: 700;
  letter-spacing: 0.01em;
  color: var(--text-strong);
}
.portal-nav {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--space-2);
}
.nav-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-2) var(--space-4);
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: var(--text-md);
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  transition: color var(--duration-fast) var(--ease-out),
    background-color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-base) var(--ease-out),
    transform var(--duration-fast) var(--ease-out);
}
.nav-link__icon {
  font-size: 16px;
  transition: transform var(--duration-base) var(--ease-out);
}
.nav-link:hover {
  color: var(--brand-600);
  background: var(--brand-50);
  border-color: var(--brand-100);
  transform: translateY(-1px);
}
.nav-link:hover .nav-link__icon {
  transform: scale(1.12);
}
.nav-link:active {
  transform: translateY(0);
}
.nav-link:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}
.nav-link--active {
  color: var(--text-inverse);
  font-weight: 600;
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border-color: transparent;
  box-shadow: 0 4px 12px -2px rgba(36, 87, 214, 0.45);
}
.nav-link--active:hover {
  color: var(--text-inverse);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  border-color: transparent;
  box-shadow: 0 6px 16px -2px rgba(36, 87, 214, 0.5);
}
.nav-link--active .nav-link__icon {
  transform: none;
}
.nav-link--console {
  color: var(--brand-600);
  background: var(--brand-50);
  border-color: var(--brand-200);
}
.nav-link--console:hover {
  color: var(--brand-700);
  background: var(--brand-100);
  border-color: var(--brand-300);
}
.portal-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.account {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out);
}
.account:hover {
  background: var(--slate-100);
}
.account__name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.account__caret {
  font-size: 12px;
  color: var(--text-tertiary);
}

.portal-main {
  position: relative;
  z-index: 1;
  flex: 1;
  width: 100%;
  max-width: var(--portal-content-max);
  margin: 0 auto;
  padding: var(--space-6) var(--space-6) var(--space-12);
  box-sizing: border-box;
}

.portal-footer {
  position: relative;
  z-index: 1;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.7), var(--bg-surface) 60%);
  backdrop-filter: blur(8px);
}
.portal-footer__inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  max-width: var(--portal-content-max);
  margin: 0 auto;
  padding: var(--space-4) var(--space-6);
  text-align: center;
}
.portal-footer__links {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: var(--space-2) var(--space-3);
  width: 100%;
}
.portal-footer__links-label {
  position: relative;
  padding-right: var(--space-3);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-tertiary);
}
.portal-footer__links-label::after {
  content: '';
  position: absolute;
  top: 50%;
  right: 0;
  width: 1px;
  height: 14px;
  background: var(--border-color);
  transform: translateY(-50%);
}
.portal-footer__links-list {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}
.footer-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px var(--space-3);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-pill);
  background: var(--bg-app);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  text-decoration: none;
  transition: color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    background-color var(--duration-fast) var(--ease-out),
    transform var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-base) var(--ease-out);
}
.footer-link__icon {
  font-size: 14px;
  color: var(--text-tertiary);
  transition: color var(--duration-fast) var(--ease-out),
    transform var(--duration-base) var(--ease-out);
}
.footer-link__arrow {
  width: 0;
  font-size: 13px;
  opacity: 0;
  transform: translateX(-4px);
  transition: width var(--duration-base) var(--ease-out),
    opacity var(--duration-base) var(--ease-out),
    transform var(--duration-base) var(--ease-out);
}
.footer-link:hover {
  border-color: var(--brand-300);
  background: linear-gradient(135deg, var(--brand-50), var(--brand-100));
  color: var(--brand-600);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
.footer-link:hover .footer-link__icon {
  color: var(--brand-500);
  transform: rotate(-12deg) scale(1.1);
}
.footer-link:hover .footer-link__arrow {
  width: 13px;
  opacity: 1;
  transform: translateX(0);
}
.footer-link:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus);
}
.footer-link:active {
  transform: translateY(0);
  box-shadow: var(--shadow-xs);
}
@media (max-width: 860px) {
  .portal-nav {
    display: none;
  }
}
</style>
