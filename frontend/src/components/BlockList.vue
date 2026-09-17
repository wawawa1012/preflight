<script setup lang="ts">
import type { MarkdownPreview } from '../types/contracts'

// annotatedCounts 可选：block_id → Annotation 条数（不是关联数）；preview 流不传，行为不变。
const props = defineProps<{
  blocks: MarkdownPreview['blocks']
  annotatedCounts?: Record<string, number>
  highlightBlockId?: string
}>()

function annotatedCount(blockId: string) {
  return props.annotatedCounts?.[blockId] ?? 0
}
</script>

<template>
  <p v-if="blocks.length === 0" class="text-sm text-slate-400">
    没有 Block：只有长度为 0 的空行不生成 Block（仍计入行号）。
  </p>
  <div v-else class="divide-y divide-slate-800 overflow-hidden rounded-lg border border-slate-800">
    <div
      v-for="block in blocks"
      :id="`block-${block.id}`"
      :key="block.id"
      class="flex flex-wrap items-start gap-3 px-3 py-2 hover:bg-slate-800/40"
      :class="[
        annotatedCount(block.id) > 0 ? 'bg-slate-800/30' : '',
        highlightBlockId === block.id ? 'ring-1 ring-inset ring-violet-500/60' : '',
      ]"
    >
      <span class="w-24 shrink-0 whitespace-nowrap pt-0.5 font-mono text-xs">
        <span class="text-slate-300">line {{ block.locator.index }}</span>
        <span class="ml-1 text-slate-600">#{{ block.ordinal }}</span>
      </span>
      <p class="min-w-0 flex-1 whitespace-pre-wrap break-words font-mono text-sm text-slate-200">{{ block.text }}</p>
      <UBadge v-if="annotatedCount(block.id) > 0" color="neutral" variant="subtle" size="sm">
        已标注 {{ annotatedCount(block.id) }} 条
      </UBadge>
      <!-- 可选 cite 槽：只有调用方提供内容时才渲染（preview 流不传，行为不变）。 -->
      <slot name="cite" :block="block" />
    </div>
  </div>
</template>
