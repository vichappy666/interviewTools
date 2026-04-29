import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'

import { getToken } from '@/api/client'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/Register.vue'),
    meta: { public: true },
  },
  {
    path: '/forgot-password',
    name: 'forgot',
    component: () => import('@/views/ForgotPassword.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/Home.vue'),
  },
  {
    path: '/profile',
    name: 'profile',
    component: () => import('@/views/Profile.vue'),
  },
  {
    path: '/ledger',
    name: 'ledger',
    component: () => import('@/views/Ledger.vue'),
  },
  {
    path: '/session/:id',
    name: 'session',
    component: () => import('@/views/Session.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to: RouteLocationNormalized) => {
  const isPublic = to.meta?.public === true
  const hasToken = !!getToken()
  if (!isPublic && !hasToken) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (isPublic && hasToken && (to.name === 'login' || to.name === 'register')) {
    return { path: '/' }
  }
})

export default router
