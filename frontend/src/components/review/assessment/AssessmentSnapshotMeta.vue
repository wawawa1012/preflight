<script setup lang="ts">
import { computed } from 'vue'
import type { AssessmentSnapshotVM } from '../../../types/assessment'
import { formatSavedAt } from '../../../utils/format'

// Snapshot 元信息：用户语言 = 评估时间 / 标准版本 / 材料范围；方法版本只在次级详情。
// Snapshot 不可原地编辑；重新评估由页面动作生成新 Snapshot。
const props = defineProps<{ snapshot: AssessmentSnapshotVM }>()

const createdAtText = computed(() => formatSavedAt(props.snapshot.createdAt))
</script>

<template>
  <!-- LEAF-TODO(DS)：主行 = 评估时间 + 标准版本 + 材料范围；方法版本进 details/次级。 -->
  <section>
    <p>评估于 {{ createdAtText }} · {{ props.snapshot.rubricTitle }} · v{{ props.snapshot.rubricRevision }} · {{ props.snapshot.materialScope }}</p>
    <details>
      <summary>评估方法</summary>
      <p>{{ props.snapshot.methodNote }}</p>
    </details>
  </section>
</template>
