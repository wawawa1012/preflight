<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

// 全站唯一一级导航：五项已实现入口，高亮只来自当前路由 path。
const route = useRoute()

const links = [
  { label: '审查', to: '/' },
  { label: '一致性检查', to: '/compare' },
  { label: '修改效果', to: '/diff' },
  { label: '质询', to: '/grill' },
  { label: '材料', to: '/materials' },
]

const currentPath = computed(() => route.path)

// 首页只匹配根路径；其余按前缀匹配子路由（如 /materials/:id、/materials/new）。
function isActive(to: string) {
  if (to === '/') return currentPath.value === '/'
  return currentPath.value === to || currentPath.value.startsWith(`${to}/`)
}
</script>

<template>
  <div class="min-h-screen">
    <header class="border-b border-slate-800 bg-slate-950/80 backdrop-blur">
      <div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-6 py-3">
        <RouterLink to="/" class="text-sm font-semibold tracking-tight text-slate-100">Preflight</RouterLink>
        <nav class="flex flex-wrap items-center gap-1" aria-label="主导航">
          <UButton
            v-for="link in links"
            :key="link.to"
            :to="link.to"
            color="neutral"
            size="sm"
            :variant="isActive(link.to) ? 'soft' : 'ghost'"
          >
            {{ link.label }}
          </UButton>
        </nav>
      </div>
    </header>
    <slot />
  </div>
</template>
