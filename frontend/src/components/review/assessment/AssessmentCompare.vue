<script setup lang="ts">
import type { AssessmentComparisonVM, AssessmentSourceVM } from '../../../types/assessment'
import {
  COMPARISON_ASPECT_LABELS,
  NEWLY_ASSESSABLE_NOTE,
  RANGE_OVERLAP_NOTE,
  criterionStateLabel,
  scoringText,
} from '../../../utils/assessmentFormat'
import type { ScoringVM } from '../../../types/assessment'

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
</script>

<template>
  <!-- LEAF-TODO(DS)：comparable → 每 Criterion Before → After + changeNote；
       区间重叠显示 RANGE_OVERLAP_NOTE，不写「提升 N 分」；
       before=null → NEWLY_ASSESSABLE_NOTE，不写「从 0 分提升」；
       not_comparable → 列出变化项（标准版本/评估方法/材料范围）。 -->
  <section v-if="props.comparison.kind === 'not_comparable'">
    <p>两次评估不可直接比较：{{ props.comparison.changedAspects.map(aspectLabel).join('、') }} 已变化。</p>
  </section>
  <ul v-else>
    <li v-for="entry in props.comparison.entries" :key="entry.criterionId">
      <p>{{ entry.title }}</p>
      <p v-if="entry.before === null">{{ NEWLY_ASSESSABLE_NOTE }}</p>
      <template v-else>
        <p>
          {{ entry.before.state === 'assessed' ? (scoringText(entry.before.scoring) ?? criterionStateLabel(entry.before.state)) : criterionStateLabel(entry.before.state) }}
          →
          {{ entry.after.state === 'assessed' ? (scoringText(entry.after.scoring) ?? criterionStateLabel(entry.after.state)) : criterionStateLabel(entry.after.state) }}
        </p>
        <p v-if="rangesOverlap(entry.before.scoring, entry.after.scoring)">{{ RANGE_OVERLAP_NOTE }}</p>
      </template>
      <p>{{ entry.changeNote }}</p>
    </li>
  </ul>
</template>
