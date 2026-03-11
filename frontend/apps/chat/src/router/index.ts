import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/chat',
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
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} - yamato` : 'yamato'
})

export default router

