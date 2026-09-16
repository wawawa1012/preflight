<script setup lang="ts">
// 材料身份头：filename + 状态徽章 + meta + 动作位。
// sticky 独立成条（自带边框），长 Block 列表滚动时保存动作与身份始终可达；
// 调用方不要再包 overflow-hidden 容器，否则 sticky 会失效。
defineProps<{
  filename: string
  meta: string
  badgeLabel: string
  badgeColor: 'warning' | 'success'
  hint?: string
}>()
</script>

<template>
  <header class="sticky top-4 z-10 rounded-lg border border-slate-800 bg-slate-900/95 px-4 py-3 backdrop-blur">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="min-w-0">
        <h1 class="truncate text-lg font-medium text-slate-100">{{ filename }}</h1>
        <p v-if="hint" class="mt-0.5 text-xs text-slate-500">{{ hint }}</p>
      </div>
      <div class="flex shrink-0 items-center gap-3">
        <UBadge :color="badgeColor" variant="subtle">{{ badgeLabel }}</UBadge>
        <slot />
      </div>
    </div>
    <p class="mt-2 break-all font-mono text-xs text-slate-500">{{ meta }}</p>
  </header>
</template>
