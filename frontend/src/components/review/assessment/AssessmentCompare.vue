<script setup lang="ts">
import type {
  AssessmentComparisonVM,
  AssessmentSourceVM,
  CriterionComparisonVM,
  CriterionAssessmentVM,
} from '../../../types/assessment'
import {
  COMPARISON_FLAG_NOTES,
  COMPARISON_OBSERVATION_NOTES,
  COMPARISON_TRUTH_NOTE,
  NOT_COMPARABLE_NOTES,
  criterionStateLabel,
  scoringText,
} from '../../../utils/assessmentFormat'
import { locatorLabel } from '../../../utils/locatorLabel'

// 前后对比：只有 backend 判定 comparable 才逐条呈现；不可比较时如实转述 reason codes。
// 前端不自己判 comparable，也不做区间几何判断——区间重叠由 observation range_overlaps 表达。
const props = defineProps<{ comparison: AssessmentComparisonVM }>()
const emit = defineEmits<{ 'open-source': [source: AssessmentSourceVM] }>()

// assessed 显示分数/区间或档位；其他状态显示状态文案。区间保持区间，不压成中点。
function stateText(item: CriterionAssessmentVM): string {
  if (item.state === 'assessed') return scoringText(item.scoring) ?? criterionStateLabel(item.state)
  return criterionStateLabel(item.state)
}

function reasonNote(code: string): string {
  return NOT_COMPARABLE_NOTES[code] ?? code
}

// range_shifted_upward/downward 没有独立 observation 文案：before → after 的区间本身已说明方向。
function observationNote(entry: CriterionComparisonVM): string | null {
  return COMPARISON_OBSERVATION_NOTES[entry.observation] ?? null
}

// 三个变化维度独立为真，按 score/anchor/reason 顺序并列，互不覆盖。
function flagNotes(entry: CriterionComparisonVM): string[] {
  const notes: string[] = []
  if (entry.scoreChanged) notes.push(COMPARISON_FLAG_NOTES.score)
  if (entry.anchorChanged) notes.push(COMPARISON_FLAG_NOTES.anchor)
  if (entry.reasonChanged) notes.push(COMPARISON_FLAG_NOTES.reason)
  return notes
}
</script>

<template>
  <section class="space-y-3">
    <!-- 不可比较：逐条转述 backend reason code 的冻结文案。 -->
    <template v-if="props.comparison.kind === 'not_comparable'">
      <p class="text-sm leading-relaxed text-slate-300">两次评估不可直接比较。</p>
      <ul class="space-y-1">
        <li
          v-for="code in props.comparison.reasonCodes"
          :key="code"
          class="flex items-baseline gap-2 text-xs leading-relaxed text-slate-400"
        >
          <span aria-hidden="true" class="shrink-0 text-slate-600">·</span>
          <span class="min-w-0">{{ reasonNote(code) }}</span>
        </li>
      </ul>
    </template>

    <template v-else>
      <!-- 因果边界：同口径观察 ≠ 修改效果的因果证明。 -->
      <p class="text-xs leading-relaxed text-slate-500">{{ COMPARISON_TRUTH_NOTE }}</p>

      <ul class="space-y-3">
        <li
          v-for="entry in props.comparison.entries"
          :key="entry.criterionId"
          class="rounded-lg border border-slate-800 bg-slate-900/40 p-4"
        >
          <p class="text-sm font-medium leading-relaxed text-slate-100">{{ entry.title }}</p>

          <!-- before → after：newly_assessable 时 before 也存在（状态为不足/无法判断），不做特殊起点。 -->
          <div class="mt-2 flex flex-wrap items-baseline gap-2">
            <span class="font-mono text-sm tabular-nums text-slate-400">{{ stateText(entry.before) }}</span>
            <span aria-hidden="true" class="text-slate-600">→</span>
            <span class="font-mono text-base font-medium tabular-nums text-slate-100">{{ stateText(entry.after) }}</span>
          </div>

          <!-- observation：逐条解释「为什么列为这种变化」；无文案（range_shifted_*）时不显示。 -->
          <p v-if="observationNote(entry)" class="mt-1 text-xs leading-relaxed text-slate-400">
            {{ observationNote(entry) }}
          </p>

          <!-- 变化维度并列展示，互不覆盖。 -->
          <p v-if="flagNotes(entry).length > 0" class="mt-1 text-xs leading-relaxed text-slate-500">
            {{ flagNotes(entry).join(' · ') }}
          </p>

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
    </template>
  </section>
</template>
