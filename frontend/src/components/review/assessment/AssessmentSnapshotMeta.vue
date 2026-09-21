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
  <section class="text-xs text-slate-500">
    <!-- 主行保持一行级的低调密度：评估时间 · 标准版本 · 材料范围。 -->
    <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span>评估于 {{ createdAtText }}</span>
      <span aria-hidden="true" class="text-slate-700">·</span>
      <span>{{ props.snapshot.rubricTitle }} · v{{ props.snapshot.rubricRevision }}</span>
      <span aria-hidden="true" class="text-slate-700">·</span>
      <span>{{ props.snapshot.materialScope }}</span>
    </div>
    <!-- 评估方法收进次级详情，不占主行。 -->
    <details class="mt-1">
      <summary class="cursor-pointer text-slate-600 hover:text-slate-400">评估方法</summary>
      <p class="mt-1 leading-relaxed text-slate-500">{{ props.snapshot.methodNote }}</p>
    </details>
  </section>
</template>
