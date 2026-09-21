<script setup lang="ts">
import { computed } from 'vue'
import type { AssessmentTotalVM } from '../../../types/assessment'
import { totalText } from '../../../utils/assessmentFormat'

// 评估总览：数字只在 backend 判定完整可计算时出现；否则如实说明缺依据的条目。
const props = defineProps<{ total: AssessmentTotalVM }>()

const text = computed(() => totalText(props.total))

// range/score 才是大字号数字主视觉；不可计算/未定义量化评分走中性 slate，绝不是红色警报。
const numeric = computed(() => props.total.kind === 'range' || props.total.kind === 'score')
const detailClass = computed(() => (props.total.kind === 'unavailable' ? 'text-amber-200/90' : 'text-slate-500'))
</script>

<template>
  <section class="rounded-xl border border-slate-800 bg-slate-950/40 px-5 py-4">
    <p
      class="font-semibold tabular-nums"
      :class="numeric ? 'font-mono text-3xl text-slate-100' : 'text-lg leading-relaxed text-slate-300'"
    >
      {{ text.headline }}
    </p>
    <p v-if="text.detail" class="mt-1.5 text-xs leading-relaxed" :class="detailClass">{{ text.detail }}</p>
  </section>
</template>
