<script setup lang="ts">
// 控制台壳层：分组侧栏导航（按权限裁剪）+ 顶栏 + 内容区。
import {
  Bell,
  Collection,
  DataAnalysis,
  Document,
  Files,
  Grid,
  HomeFilled,
  OfficeBuilding,
  Reading,
  Setting,
  Tickets,
  User,
  UserFilled,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { hasAnyPermission, PERMISSIONS } from '@/lib/rbac'
import { useSystemConfig } from '@/lib/system-config'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const { systemName, logo } = useSystemConfig()

interface MenuItem {
  label: string
  to: string
  icon: Component
  permissions: string[]
}

interface MenuGroup {
  label: string
  items: MenuItem[]
}

const menuGroups: MenuGroup[] = [
  {
    label: '概览',
    items: [{ label: '总览', to: '/admin', icon: DataAnalysis, permissions: [PERMISSIONS.dashboardView] }],
  },
  {
    label: '教学管理',
    items: [
      { label: '课程管理', to: '/admin/courses', icon: Reading, permissions: [PERMISSIONS.courseManage] },
      { label: '题库管理', to: '/admin/questions', icon: Collection, permissions: [PERMISSIONS.questionManage] },
      { label: '考试管理', to: '/admin/exams', icon: Tickets, permissions: [PERMISSIONS.examView, PERMISSIONS.examManage] },
      { label: '教师管理', to: '/admin/teachers', icon: UserFilled, permissions: [PERMISSIONS.teacherManage] },
    ],
  },
  {
    label: '组织与权限',
    items: [
      { label: '校区管理', to: '/admin/campuses', icon: OfficeBuilding, permissions: [PERMISSIONS.campusView, PERMISSIONS.campusManage, PERMISSIONS.campusMembersManage] },
      { label: '管理员管理', to: '/admin/admins', icon: User, permissions: [PERMISSIONS.administratorManage] },
      { label: '学员管理', to: '/admin/students', icon: Grid, permissions: [PERMISSIONS.studentManage] },
      { label: '角色管理', to: '/admin/roles', icon: Files, permissions: [PERMISSIONS.rolesManage] },
    ],
  },
  {
    label: '站点运营',
    items: [
      { label: '通知公告', to: '/admin/announcements', icon: Bell, permissions: [PERMISSIONS.announcementManage] },
      { label: '系统配置', to: '/admin/settings', icon: Setting, permissions: [PERMISSIONS.systemManage] },
      { label: '字典管理', to: '/admin/dictionaries', icon: Document, permissions: [PERMISSIONS.dictionaryManage] },
    ],
  },
]

// 仅保留有权限的菜单项；整组无权限时不展示
const visibleGroups = computed(() =>
  menuGroups
    .map((group) => ({ ...group, items: group.items.filter((item) => hasAnyPermission(auth.user, item.permissions)) }))
    .filter((group) => group.items.length > 0),
)

const displayName = computed(() => auth.user?.display_name || auth.user?.username || '')

async function handleLogout() {
  await auth.logout()
  await router.push('/login')
}

function handleCommand(command: string) {
  if (command === 'logout') void handleLogout()
  if (command === 'home') void router.push('/')
  if (command === 'profile') void router.push('/profile')
}
</script>

<template>
  <div class="admin">
    <aside class="admin-sidebar">
      <div class="admin-brand">
        <span class="admin-brand__mark">
          <img v-if="logo" :src="`/api/image/${logo}`" :alt="systemName" />
          <span v-else>{{ systemName.slice(0, 1) }}</span>
        </span>
        <span class="admin-brand__text">{{ systemName }}</span>
      </div>

      <nav class="admin-nav">
        <div v-for="group in visibleGroups" :key="group.label" class="admin-nav__group">
          <p class="admin-nav__label">{{ group.label }}</p>
          <router-link
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            class="admin-nav__item"
            :class="{ 'is-root': item.to === '/admin' }"
          >
            <el-icon class="admin-nav__icon"><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </router-link>
        </div>
      </nav>
    </aside>

    <div class="admin-body">
      <header class="admin-header">
        <div class="admin-header__left">
          <router-link to="/" class="admin-home">
            <el-icon class="admin-home__icon"><HomeFilled /></el-icon>
            <span class="admin-home__text">首页</span>
          </router-link>
        </div>
        <div class="admin-header__right">
          <el-dropdown trigger="click" @command="handleCommand">
            <button type="button" class="admin-user">
              <el-avatar :size="34" :src="auth.user?.avatar ? `/api/image/${auth.user.avatar}` : undefined">
                {{ displayName.slice(0, 1) }}
              </el-avatar>
              <span class="admin-user__name">{{ displayName }}</span>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人中心</el-dropdown-item>
                <el-dropdown-item command="home">前台首页</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="admin-main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.admin {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-app);
}

/* ===================== 侧栏 ===================== */
.admin-sidebar {
  display: flex;
  width: var(--sidebar-width);
  flex-shrink: 0;
  flex-direction: column;
  background: linear-gradient(180deg, #16213a 0%, #0f1a2e 100%);
  color: #c7d2e4;
}
.admin-brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: var(--header-height);
  flex-shrink: 0;
  padding: 0 var(--space-5);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.admin-brand__mark {
  display: grid;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  place-items: center;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--brand-500), var(--brand-700));
  color: #fff;
  font-size: var(--text-md);
  font-weight: 700;
  overflow: hidden;
}
.admin-brand__mark img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.admin-brand__text {
  font-size: var(--text-md);
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.admin-nav {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4) var(--space-3);
}
.admin-nav__group + .admin-nav__group {
  margin-top: var(--space-5);
}
.admin-nav__label {
  padding: 0 var(--space-3) var(--space-2);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #5f7295;
}
.admin-nav__item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px var(--space-3);
  margin-bottom: 2px;
  border-radius: var(--radius-md);
  color: #c7d2e4;
  text-decoration: none;
  font-size: var(--text-base);
  font-weight: 500;
  transition: background-color var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out);
}
.admin-nav__item:hover {
  background: rgba(255, 255, 255, 0.07);
  color: #fff;
}
.admin-nav__item.router-link-active {
  background: linear-gradient(135deg, var(--brand-500), var(--brand-600));
  color: #fff;
  box-shadow: 0 6px 16px -8px rgba(36, 87, 214, 0.9);
}
/* 总览使用前缀匹配会命中所有子页，这里仅精确匹配时高亮 */
.admin-nav__item.is-root.router-link-active:not(.router-link-exact-active) {
  background: transparent;
  color: #c7d2e4;
  box-shadow: none;
}
.admin-nav__item.is-root.router-link-active:not(.router-link-exact-active):hover {
  background: rgba(255, 255, 255, 0.07);
  color: #fff;
}
.admin-nav__icon {
  font-size: 18px;
}

/* ===================== 主体 ===================== */
.admin-body {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
}
.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--header-height);
  flex-shrink: 0;
  padding: 0 var(--space-6);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
}
.admin-header__left {
  display: flex;
  align-items: center;
}
.admin-header__right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.admin-home {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  height: 40px;
  padding: 0 var(--space-4);
  border-radius: var(--radius-pill);
  border: 1px solid var(--slate-300);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
  transition: all var(--duration-base) var(--ease-out);
}
.admin-home__icon {
  font-size: 18px;
  color: var(--brand-500);
  transition: color var(--duration-base) var(--ease-out);
}
.admin-home:hover {
  border-color: var(--brand-500);
  background: var(--brand-50);
  color: var(--brand-600);
  box-shadow: 0 6px 16px -8px rgba(36, 87, 214, 0.6);
}
.admin-home:hover .admin-home__icon {
  color: var(--brand-600);
}
.admin-user {
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
.admin-user:hover {
  background: var(--slate-100);
}
.admin-user__name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-main {
  flex: 1;
  min-height: 0;
  min-width: 0;
  padding: var(--space-5) var(--space-6);
  overflow: auto;
  background-color: var(--bg-app);
  background-image: var(--bg-app-gradient);
  background-attachment: local;
}

@media (max-width: 900px) {
  .admin-sidebar {
    display: none;
  }
}
</style>
