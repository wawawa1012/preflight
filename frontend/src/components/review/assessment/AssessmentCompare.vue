<script setup lang="ts">
import { computed } from 'vue'
import type {
  AssessmentComparisonVM,
  AssessmentSourceVM,
  CriterionComparisonVM,
  CriterionAssessmentVM,
} from '../../../types/assessment'
import {
  COMPARISON_ASPECT_LABELS,
  NEWLY_ASSESSABLE_NOTE,
  RANGE_OVERLAP_NOTE,
  criterionStateLabel,
  scoringText,
} from '../../../utils/assessmentFormat'
import type { ScoringVM } from '../../../types/assessment'
import { locatorLabel } from '../../../utils/locatorLabel'

// 前后对比：只有 backend 判定 comparable 才逐条呈现；不可比较时如实说明哪一项变了。
// 前端不自己判 comparable；区间重叠只是两个区间的展示事实（纯几何），不是业务判断。
const props = defineProps<{ comparison: AssessmentComparisonVM }>()
const emit = defineEmits<{ 'open-source': [source: AssessmentSourceVM] }>()

function aspectLabel(aspect: string): string {
  return COMPARISON_ASPECT_LABELS[aspect] ?? aspect
}

function rangesOverlap(before: ScoringVM, after: ScoringVM): boolean {
  if (before.kind !== 'range' || after.kind !== 'range') return false
  return before.min <= after.max && after.min <= before.max
}

// assessed 显示分数/区间或档位；其他状态显示状态文案。区间保持区间，不压成中点。
function stateText(item: CriterionAssessmentVM): string {
  if (item.state === 'assessed') return scoringText(item.scoring) ?? criterionStateLabel(item.state)
  return criterionStateLabel(item.state)
}

function overlap(entry: CriterionComparisonVM): boolean {
  return entry.before !== null && rangesOverlap(entry.before.scoring, entry.after.scoring)
}
</script>

<template>
  <section class="space-y-3">
    <!-- 不可比较：说明哪一项变了（标准版本 / 评估方法 / 材料范围）。 -->
    <p v-if="props.comparison.kind === 'not_comparable'" class="text-sm leading-relaxed text-slate-300">
      两次评估不可直接比较：{{ props.comparison.changedAspects.map(aspectLabel).join('、') }} 已变化。
    </p>

    <ul v-else class="space-y-3">
      <li v-for="entry in props.comparison.entries" :key="entry.criterionId" class="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        <p class="text-sm font-medium leading-relaxed text-slate-100">{{ entry.title }}</p>

        <!-- newly assessable：before 为 null 不是零分起点，只说明本次已有足够依据。 -->
        <p v-if="entry.before === null" class="mt-2 text-xs text-emerald-300">{{ NEWLY_ASSESSABLE_NOTE }}</p>
        <template v-else>
          <div class="mt-2 flex flex-wrap items-baseline gap-2">
            <span class="font-mono text-sm tabular-nums text-slate-400">{{ stateText(entry.before) }}</span>
            <span aria-hidden="true" class="text-slate-600">→</span>
            <span class="font-mono text-base font-medium tabular-nums text-slate-100">{{ stateText(entry.after) }}</span>
          </div>
          <p v-if="overlap(entry)" class="mt-1 text-xs text-slate-500">{{ RANGE_OVERLAP_NOTE }}</p>
        </template>

        <p class="mt-2 text-xs leading-relaxed text-slate-400">{{ entry.changeNote }}</p>

        <!-- 本次评估的依据 chips：点击回到原文；位置一律经 locatorLabel。 -->
        <ul v-if="entry.after.sources.length > 0" class="mt-2.5 flex flex-wrap gap-2">
          <li v-for="source in entry.after.sources" :key="`${source.blockId}:${source.start}`" class="max-w-full">
            <button
              type="button"
              class="group flex max-w-full items-baseline gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-2.5 py-1.5 text-left text-xs text-slate-400 transition hover:border-violet-700/60 hover:text-slate-200"
              @click="emit('open-source', source)"
            >
              <span class="min-w-0 truncate">“{{ source.quote }}”</span>
              <span class="shrink-0 text-slate-600 group-hover:text-violet-300">{{ locatorLabel(source.locator) }}</span>
              <span class="shrink-0 text-slate-600">· {{ source.materialLabel }}</span>
            </button>
          </li>
        </ul>
      </li>
    </ul>
  </section>
</template>
