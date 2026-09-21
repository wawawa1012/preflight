<script setup lang="ts">
import { computed } from 'vue'
import type { AssessmentSourceVM, CriterionAssessmentVM } from '../../../types/assessment'
import { criterionStateLabel, scoringText, NOT_SCORABLE_NOTE, NOT_SCORABLE_HINT, SOURCES_SECTION_LABEL, MISSING_SECTION_LABEL } from '../../../utils/assessmentFormat'
import { locatorLabel } from '../../../utils/locatorLabel'

// 评估条目卡：状态 → 分数/区间（或明确的非评分状态）→ 为什么 → 依据 → 还缺什么。
// 卡片只呈现 VM：不读 wire 类型，不理解定位种类，不推断业务语义。
const props = defineProps<{ item: CriterionAssessmentVM }>()
const emit = defineEmits<{ 'open-source': [source: AssessmentSourceVM] }>()

// 分数/区间只在 assessed 且标准确实定义了量化评分时出现；区间保持 12–15 / 20。
const scoring = computed(() => (props.item.state === 'assessed' ? scoringText(props.item.scoring) : null))

// 状态 badge 只表达结果状态：assessed=emerald、insufficient=amber、abstain/not_scorable=slate、failed=red。
const badgeClass = computed(() => {
  switch (props.item.state) {
    case 'assessed':
      return 'border-emerald-700/50 bg-emerald-950/30 text-emerald-300'
    case 'insufficient':
      return 'border-amber-700/50 bg-amber-950/20 text-amber-200'
    case 'abstain':
    case 'not_scorable':
      return 'border-slate-700 bg-slate-800/40 text-slate-300'
    case 'failed':
      return 'border-red-800/60 bg-red-950/30 text-red-300'
  }
})
</script>

<template>
  <article class="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
    <!-- criterion title 是主体；状态 badge 靠右，不抢标题。 -->
    <div class="flex flex-wrap items-start justify-between gap-3">
      <h3 class="min-w-0 flex-1 text-base font-medium leading-relaxed text-slate-100">{{ props.item.title }}</h3>
      <span class="shrink-0 rounded-md border px-2 py-0.5 text-xs" :class="badgeClass">
        {{ criterionStateLabel(props.item.state) }}
      </span>
    </div>

    <!-- 分数/区间：assessed 且标准定义了量化评分才显示，作为大字号主视觉。 -->
    <p v-if="scoring" class="mt-3 font-mono text-3xl font-semibold tabular-nums text-slate-100">{{ scoring }}</p>
    <!-- assessed 但标准未定义量化评分：不显示分数位，只说明原因与仍可参考的内容。 -->
    <template v-else-if="props.item.state === 'assessed'">
      <p class="mt-3 text-sm font-medium text-slate-200">{{ NOT_SCORABLE_NOTE }}</p>
      <p class="mt-1 text-xs leading-relaxed text-slate-500">{{ NOT_SCORABLE_HINT }}</p>
    </template>
    <!-- not_scorable：badge 已说明状态，不显示分数位，只给仍可参考的提示。 -->
    <p v-else-if="props.item.state === 'not_scorable'" class="mt-3 text-xs leading-relaxed text-slate-500">
      {{ NOT_SCORABLE_HINT }}
    </p>

    <!-- 档位/anchor 的人话：低权重，附在分数之下。 -->
    <p v-if="props.item.levelLabel" class="mt-1.5 text-xs text-slate-400">{{ props.item.levelLabel }}</p>

    <!-- 为什么：依据不足/无法判断/执行失败时这里是主体。 -->
    <p class="mt-3 text-sm leading-relaxed text-slate-300">{{ props.item.why }}</p>

    <!-- 依据 chips：每条 quote + 位置 + 材料，点击回到原文；小、可换行。 -->
    <template v-if="props.item.sources.length > 0">
      <p class="mt-4 text-xs tracking-widest text-slate-500">{{ SOURCES_SECTION_LABEL }}</p>
      <ul class="mt-1.5 flex flex-wrap gap-2">
        <li v-for="source in props.item.sources" :key="`${source.blockId}:${source.start}`" class="max-w-full">
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
    </template>

    <!-- 还缺什么：amber 语义但克制，只列缺口本身。 -->
    <template v-if="props.item.missing.length > 0">
      <p class="mt-4 text-xs tracking-widest text-slate-500">{{ MISSING_SECTION_LABEL }}</p>
      <ul class="mt-1.5 space-y-1">
        <li
          v-for="(gap, index) in props.item.missing"
          :key="index"
          class="flex items-baseline gap-2 text-xs leading-relaxed text-amber-200/80"
        >
          <span aria-hidden="true" class="shrink-0 text-amber-500/70">·</span>
          <span class="min-w-0">{{ gap }}</span>
        </li>
      </ul>
    </template>

    <!-- 注意事项：评估方对本次判断的保留说明，低权重呈现。 -->
    <template v-if="props.item.caveats.length > 0">
      <p class="mt-4 text-xs tracking-widest text-slate-500">注意事项</p>
      <ul class="mt-1.5 space-y-1">
        <li
          v-for="(caveat, index) in props.item.caveats"
          :key="index"
          class="flex items-baseline gap-2 text-xs leading-relaxed text-slate-500"
        >
          <span aria-hidden="true" class="shrink-0 text-slate-600">·</span>
          <span class="min-w-0">{{ caveat }}</span>
        </li>
      </ul>
    </template>
  </article>
</template>
