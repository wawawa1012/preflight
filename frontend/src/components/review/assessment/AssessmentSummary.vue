<script setup lang="ts">
import type { AssessmentTotalVM } from '../../../types/assessment'
import { totalText } from '../../../utils/assessmentFormat'

// 评估总览：数字只在 backend 判定完整可计算时出现；否则如实说明缺依据的条目。
const props = defineProps<{ total: AssessmentTotalVM }>()
</script>

<template>
  <!-- LEAF-TODO(DS)：总分/不可计算/未定义量化评分三态呈现；文案只允许来自 totalText。 -->
  <section>
    <p>{{ totalText(props.total).headline }}</p>
    <p v-if="totalText(props.total).detail">{{ totalText(props.total).detail }}</p>
  </section>
</template>
