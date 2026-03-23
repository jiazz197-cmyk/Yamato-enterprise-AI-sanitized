import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { config } from '../config'
import { readUserRole } from '../services/auth'

const PUBLIC_PATHS = ['/login', '/register']

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/chat',
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/pages/LoginPage.vue'),
    meta: { title: '登录' },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/pages/RegisterPage.vue'),
    meta: { title: '注册' },
  },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('@/pages/ChatPage.vue'),
    meta: { title: 'AI聊天' },
  },
  {
    path: '/files',
    name: 'files',
    component: () => import('@/pages/FileManagerPage.vue'),
    meta: { title: '文件管理' },
  },
  {
    path: '/policy',
    name: 'policy',
    component: () => import('@/pages/PolicyGeneratePage.vue'),
    meta: { title: '保单生成' },
  },
  {
    path: '/users',
    name: 'users',
    component: () => import('@/pages/UserManagePage.vue'),
    meta: { title: '用户管理', requiresSuperuser: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  let token: string | null = null
  try {
    token = localStorage.getItem(config.authTokenStorageKey)
  } catch {
    token = null
  }

  const isPublic = PUBLIC_PATHS.includes(to.path)

  if (!token && !isPublic) {
    next('/login')
    return
  }

  if (token && isPublic) {
    next('/chat')
    return
  }

  if (to.meta.requiresSuperuser && readUserRole() !== 'superuser') {
    next('/chat')
    return
  }

  next()
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} - yamato` : 'yamato'
})

export default router

