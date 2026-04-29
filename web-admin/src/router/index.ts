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
    path: '/',
    redirect: '/users',
  },
  {
    path: '/users',
    name: 'user-list',
    component: () => import('@/views/UserList.vue'),
  },
  {
    path: '/users/:id',
    name: 'user-detail',
    component: () => import('@/views/UserDetail.vue'),
    props: (route: RouteLocationNormalized) => ({ id: Number(route.params.id) }),
  },
  {
    path: '/configs',
    name: 'configs',
    component: () => import('@/views/Configs.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/users',
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
    return { path: '/login' }
  }
  if (isPublic && hasToken && to.name === 'login') {
    return { path: '/' }
  }
})

export default router
