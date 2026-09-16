<script setup lang="ts">
import type { MarkdownPreview } from '../types/contracts'

defineProps<{ blocks: MarkdownPreview['blocks'] }>()
</script>

<template>
  <p v-if="blocks.length === 0" class="text-sm text-slate-400">
    没有 Block：只有长度为 0 的空行不生成 Block（仍计入行号）。
  </p>
  <div v-else class="divide-y divide-slate-800 overflow-hidden rounded-lg border border-slate-800">
    <div
      v-for="block in blocks"
      :key="block.id"
      class="flex items-start gap-3 px-3 py-2 hover:bg-slate-800/40"
    >
      <span class="w-24 shrink-0 whitespace-nowrap pt-0.5 font-mono text-xs">
        <span class="text-slate-300">line {{ block.locator.index }}</span>
        <span class="ml-1 text-slate-600">#{{ block.ordinal }}</span>
      </span>
      <p class="min-w-0 flex-1 whitespace-pre-wrap break-words font-mono text-sm text-slate-200">{{ block.text }}</p>
    </div>
  </div>
</template>
