<script setup lang="ts">
import { computed } from 'vue'
import type { Block, MaterialPreflightCitation } from '../types/contracts'

const props = defineProps<{
  open: boolean
  citation: MaterialPreflightCitation | null
  block: Block | null
  filename: string
}>()

defineEmits<{ 'update:open': [value: boolean] }>()

// Unicode：必须 Array.from 对齐 Python 的 code point start/end，不能用 UTF-16 slice。
const segments = computed(() => {
  const block = props.block
  const citation = props.citation
  if (!block || !citation) return []
  const chars = Array.from(block.text)
  const start = Math.max(0, Math.min(citation.start, chars.length))
  const end = Math.max(start, Math.min(citation.end, chars.length))
  return [
    { text: chars.slice(0, start).join(''), highlight: false },
    { text: chars.slice(start, end).join(''), highlight: true },
    { text: chars.slice(end).join(''), highlight: false },
  ].filter((part) => part.text.length > 0)
})
</script>

<template>
  <USlideover :open="open" title="证据原文" @update:open="$emit('update:open', $event)">
    <template #body>
      <p class="text-xs text-slate-500">{{ filename }} · Line {{ citation?.line_number }}</p>
      <p class="mt-3 whitespace-pre-wrap break-words font-mono text-sm text-slate-200">
        <template v-for="(part, index) in segments" :key="index">
          <mark v-if="part.highlight" class="rounded bg-violet-500/30 text-slate-100">{{ part.text }}</mark>
          <span v-else>{{ part.text }}</span>
        </template>
      </p>
      <p class="mt-4 text-xs text-slate-500">quote：{{ citation?.quote }}</p>
    </template>
  </USlideover>
</template>
