<script setup lang="ts">
// 共享页头：标题 + 可选副标题 + 右侧默认插槽（页面级动作）。
// 无眉题、无边框包装：保持稀疏，页面背景就是容器。
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div class="min-w-0">
      <h1 class="text-2xl font-semibold tracking-tight text-slate-100">{{ title }}</h1>
      <p v-if="subtitle" class="mt-2 text-sm text-slate-400">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.default" class="flex flex-wrap items-center gap-2">
      <slot />
    </div>
  </div>
</template>
