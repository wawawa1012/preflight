<script setup lang="ts">
// 共享空态：标题 + 可选提示 + 一个 CTA 插槽；不包边框，靠间距分隔。
defineProps<{ title: string; hint?: string }>()
</script>

<template>
  <div class="flex flex-col items-center gap-2 px-6 py-10 text-center">
    <p class="text-sm font-medium text-slate-200">{{ title }}</p>
    <p v-if="hint" class="text-xs text-slate-500">{{ hint }}</p>
    <div v-if="$slots.default" class="mt-2 flex flex-wrap items-center justify-center gap-2">
      <slot />
    </div>
  </div>
</template>
