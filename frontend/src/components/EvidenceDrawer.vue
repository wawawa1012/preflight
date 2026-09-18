<script setup lang="ts">
import { computed } from 'vue'
import type { Block } from '../types/contracts'

interface DrawerHighlight {
  line_number: number
  start: number
  end: number
}

const props = defineProps<{
  open: boolean
  highlight: DrawerHighlight | null
  block: Block | null
  previousBlock?: Block | null
  nextBlock?: Block | null
  filename: string
}>()

defineEmits<{ 'update:open': [value: boolean] }>()

// Unicode：必须 Array.from 对齐 Python 的 code point start/end，不能用 UTF-16 slice。
const segments = computed(() => {
  const block = props.block
  const highlight = props.highlight
  if (!block || !highlight) return []
  const chars = Array.from(block.text)
  const start = Math.max(0, Math.min(highlight.start, chars.length))
  const end = Math.max(start, Math.min(highlight.end, chars.length))
  return [
    { text: chars.slice(0, start).join(''), highlight: false },
    { text: chars.slice(start, end).join(''), highlight: true },
    { text: chars.slice(end).join(''), highlight: false },
  ].filter((part) => part.text.length > 0)
})
</script>

<template>
  <USlideover
    :open="open"
    :title="`原文 · 第 ${highlight?.line_number ?? '?'} 行`"
    @update:open="$emit('update:open', $event)"
  >
    <template #body>
      <p class="text-xs text-slate-500">{{ filename }}</p>
      <div class="mt-3 space-y-1 break-words font-mono text-sm">
        <p v-if="previousBlock" class="whitespace-pre-wrap text-slate-500">{{ previousBlock.text }}</p>
        <p class="whitespace-pre-wrap text-slate-200">
          <template v-for="(part, index) in segments" :key="index">
            <mark v-if="part.highlight" class="rounded bg-violet-500/30 text-slate-100">{{ part.text }}</mark>
            <span v-else>{{ part.text }}</span>
          </template>
        </p>
        <p v-if="nextBlock" class="whitespace-pre-wrap text-slate-500">{{ nextBlock.text }}</p>
      </div>
    </template>
  </USlideover>
</template>
