<script setup lang="ts">
import type { ActionItemAction, ActionItemModel } from '../../types/action'

// ActionItem 呈现组件：WHAT / WHY / WHERE / NEXT 四层信息层级。
// 视觉权重：what + detail 是主视觉；why 次之；where 与 meta 是低权重出处。
defineProps<{ item: ActionItemModel }>()
const emit = defineEmits<{ (e: 'act', action: ActionItemAction): void }>()

function run(action: ActionItemAction) {
  if (!action.to) emit('act', action)
}
</script>

<template>
  <article class="rounded-xl border border-slate-800 p-5">
    <div class="flex items-start justify-between gap-3">
      <p class="text-sm font-medium text-slate-100">{{ item.what }}</p>
      <span v-if="item.meta" class="shrink-0 text-[11px] text-slate-600">{{ item.meta }}</span>
    </div>
    <p v-if="item.detail" class="mt-2 font-mono text-xl font-semibold tracking-tight text-amber-300">{{ item.detail }}</p>
    <p class="mt-2 text-xs leading-relaxed text-slate-400">{{ item.why }}</p>
    <p class="mt-2 text-[11px] text-slate-600">来源：{{ item.where }}</p>
    <div class="mt-4 flex flex-wrap gap-2">
      <UButton
        v-for="action in item.actions"
        :key="action.key"
        :to="action.to"
        size="sm"
        :color="action.primary ? 'primary' : 'neutral'"
        :variant="action.primary ? 'solid' : 'subtle'"
        @click="run(action)"
      >
        {{ action.label }}
      </UButton>
    </div>
  </article>
</template>
