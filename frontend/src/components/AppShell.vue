<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

// 全站一级导航只剩两条：审查（Home）与材料库。
// 一致性/修改效果/质询不再是独立入口——它们是 Review Workspace 内的视角，避免与首页重复的 IA。
const route = useRoute()

const links = [
  { label: '审查', to: '/' },
  { label: '材料', to: '/materials' },
]

const currentPath = computed(() => route.path)

// 审查匹配根路径与整个 /reviews 工作区；材料按前缀匹配子路由。
function isActive(to: string) {
  if (to === '/') return currentPath.value === '/' || currentPath.value.startsWith('/reviews')
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
