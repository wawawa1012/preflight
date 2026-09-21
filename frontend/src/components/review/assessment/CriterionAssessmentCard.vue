<script setup lang="ts">
import type { AssessmentSourceVM, CriterionAssessmentVM } from '../../../types/assessment'
import { criterionStateLabel, scoringText, NOT_SCORABLE_NOTE, NOT_SCORABLE_HINT } from '../../../utils/assessmentFormat'
import { locatorLabel } from '../../../utils/locatorLabel'

// 评估条目卡：状态 → 分数/区间（或明确的非评分状态）→ 为什么 → 依据 → 还缺什么。
// 卡片只呈现 VM：不读 wire 类型，不理解 locator.kind，不推断业务语义。
const props = defineProps<{ item: CriterionAssessmentVM }>()
const emit = defineEmits<{ 'open-source': [source: AssessmentSourceVM] }>()
</script>

<template>
  <!-- LEAF-TODO(DS)：按 task card 的视觉层级实现；结构与文案只允许来自 assessmentFormat。 -->
  <article>
    <p>{{ props.item.title }}</p>
    <p>{{ criterionStateLabel(props.item.state) }}</p>
    <p v-if="scoringText(props.item.scoring)">{{ scoringText(props.item.scoring) }}</p>
    <p v-else-if="props.item.state === 'assessed'">{{ NOT_SCORABLE_NOTE }}：{{ NOT_SCORABLE_HINT }}</p>
    <p v-if="props.item.levelLabel">{{ props.item.levelLabel }}</p>
    <p>{{ props.item.why }}</p>
    <ul>
      <li v-for="source in props.item.sources" :key="`${source.blockId}:${source.start}`">
        <button type="button" @click="emit('open-source', source)">
          “{{ source.quote }}” · {{ locatorLabel(source.locator) }} · {{ source.materialLabel }}
        </button>
      </li>
    </ul>
    <ul>
      <li v-for="(gap, index) in props.item.missing" :key="index">{{ gap }}</li>
    </ul>
  </article>
</template>
