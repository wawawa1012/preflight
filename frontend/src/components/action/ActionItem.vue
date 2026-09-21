<script setup lang="ts">
import type { ActionItemAction, ActionItemModel } from '../../types/action'

// ActionItem 呈现组件：WHAT / WHY / WHERE / NEXT 四层信息层级。
// 视觉权重：what + detail 是主视觉；why 次之；where 与 meta 是低权重出处。
// tone 只来自真实语义：amber=待处理，emerald=确认/未再检出，violet=模型动作。
const props = withDefaults(defineProps<{ item: ActionItemModel; tone?: 'amber' | 'emerald' | 'violet'; dismissible?: boolean }>(), {
  tone: 'amber',
  dismissible: false,
})
const emit = defineEmits<{
  (e: 'act', action: ActionItemAction): void
  (e: 'dismiss', key: string): void
}>()

function run(action: ActionItemAction) {
  if (!action.to) emit('act', action)
}
</script>

<template>
  <article
    class="rounded-xl border p-5"
    :class="props.tone === 'emerald' ? 'border-emerald-800/50' : props.tone === 'violet' ? 'border-violet-800/50' : 'border-slate-800'"
  >
    <div class="flex items-start justify-between gap-3">
      <p class="text-sm font-medium text-slate-100">{{ item.what }}</p>
      <span class="flex shrink-0 items-center gap-3">
        <span v-if="item.meta" class="text-[11px] text-slate-600">{{ item.meta }}</span>
        <button
          v-if="dismissible"
          type="button"
          class="text-[11px] text-slate-600 transition hover:text-slate-300"
          @click="emit('dismiss', item.key)"
        >暂时忽略</button>
      </span>
    </div>
    <p
      v-if="item.detail"
      class="mt-2 font-mono text-xl font-semibold tracking-tight"
      :class="props.tone === 'emerald' ? 'text-emerald-300' : 'text-amber-300'"
    >{{ item.detail }}</p>
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
