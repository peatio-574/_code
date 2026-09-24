/**
 * 路由与访问守卫。
 *
 * - 门户页（首页/课程/题库/考试/个人中心）使用 PortalLayout。
 * - 控制台页使用 AdminLayout，仅管理员/超管可进入，且按权限码裁剪。
 * - 学员访问控制台会被重定向回首页；未登录访问受保护页跳转登录。
 */
import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { hasAnyPermission } from '@/lib/rbac'
import { PERMISSIONS } from '@/types'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
    {
      path: '/',
      component: () => import('@/layouts/PortalLayout.vue'),
      children: [
        { path: '', name: 'home', component: () => import('@/views/HomeView.vue') },
        { path: 'courses', name: 'courses', component: () => import('@/views/CoursesView.vue') },
        { path: 'courses/:courseId', name: 'course-detail', component: () => import('@/views/CourseDetailView.vue') },
        {
          path: 'courses/:courseId/learn',
          name: 'course-learn',
          component: () => import('@/views/CourseLearnView.vue'),
          meta: { requiresAuth: true },
        },
        { path: 'question', name: 'questions', component: () => import('@/views/QuestionsView.vue'), meta: { requiresAuth: true } },
        { path: 'exams', name: 'exams', component: () => import('@/views/ExamsView.vue'), meta: { requiresAuth: true } },
        { path: 'profile', name: 'profile', component: () => import('@/views/ProfileView.vue'), meta: { requiresAuth: true } },
      ],
    },
    {
      path: '/admin',
      component: () => import('@/layouts/AdminLayout.vue'),
      meta: { admin: true },
      children: [
        { path: '', name: 'admin-dashboard', component: () => import('@/views/admin/DashboardView.vue'), meta: { permissions: [PERMISSIONS.dashboardView] } },
        { path: 'courses', name: 'admin-courses', component: () => import('@/views/admin/CoursesView.vue'), meta: { permissions: [PERMISSIONS.courseManage] } },
        { path: 'questions', name: 'admin-questions', component: () => import('@/views/admin/QuestionsView.vue'), meta: { permissions: [PERMISSIONS.questionManage] } },
        { path: 'exams', name: 'admin-exams', component: () => import('@/views/admin/ExamsView.vue'), meta: { permissions: [PERMISSIONS.examView, PERMISSIONS.examManage, PERMISSIONS.examCompose] } },
        { path: 'teachers', name: 'admin-teachers', component: () => import('@/views/admin/TeachersView.vue'), meta: { permissions: [PERMISSIONS.teacherManage] } },
        { path: 'campuses', name: 'admin-campuses', component: () => import('@/views/admin/CampusesView.vue'), meta: { permissions: [PERMISSIONS.campusView, PERMISSIONS.campusManage, PERMISSIONS.campusMembersManage] } },
        { path: 'admins', name: 'admin-admins', component: () => import('@/views/admin/AdminsView.vue'), meta: { permissions: [PERMISSIONS.administratorManage] } },
        { path: 'students', name: 'admin-students', component: () => import('@/views/admin/StudentsView.vue'), meta: { permissions: [PERMISSIONS.studentManage] } },
        { path: 'roles', name: 'admin-roles', component: () => import('@/views/admin/RolesView.vue'), meta: { permissions: [PERMISSIONS.rolesManage] } },
        { path: 'announcements', name: 'admin-announcements', component: () => import('@/views/admin/AnnouncementsView.vue'), meta: { permissions: [PERMISSIONS.announcementManage] } },
        { path: 'settings', name: 'admin-settings', component: () => import('@/views/admin/SettingsView.vue'), meta: { permissions: [PERMISSIONS.systemManage] } },
        { path: 'dictionaries', name: 'admin-dictionaries', component: () => import('@/views/admin/DictionariesView.vue'), meta: { permissions: [PERMISSIONS.dictionaryManage] } },
        { path: 'dictionaries/:typeId', name: 'admin-dictionary-detail', component: () => import('@/views/admin/DictionaryDetailView.vue'), meta: { permissions: [PERMISSIONS.dictionaryManage] } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

// 全局前置守卫：加载会话 → 公开页/登录校验 → 控制台角色与权限校验
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await auth.loadSelf()
  }
  // 已登录用户不再停留在登录页
  if (to.meta.public) {
    if (auth.isAuthenticated) return { path: '/' }
    return true
  }
  // 受保护页面要求登录，回跳地址随 query 携带
  const requiresAuth = to.meta.requiresAuth || to.meta.admin
  if (requiresAuth && !auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  // 控制台仅管理员/超管可进入
  if (to.meta.admin && !auth.isAdmin) {
    return { path: '/' }
  }
  // 按权限码校验单个控制台模块
  const permissions = to.meta.permissions as string[] | undefined
  if (permissions && !hasAnyPermission(auth.user, permissions)) {
    return { path: '/admin' }
  }
  return true
})

export default router
