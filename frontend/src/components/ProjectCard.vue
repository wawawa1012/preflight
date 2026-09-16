<script setup lang="ts">
defineProps<{
  name: string
  readiness: string
  rubricCoverage: string
  criticalRisks: number
}>()
</script>

<template>
  <UCard>
    <div class="flex items-start justify-between gap-4">
      <h2 class="text-lg font-medium">{{ name }}</h2>
      <UBadge color="neutral" variant="subtle">MOCK 数据</UBadge>
    </div>
    <div class="mt-6 grid grid-cols-3 gap-4">
      <div>
        <p class="text-sm text-slate-400">就绪度</p>
        <p class="mt-1 text-2xl font-semibold">{{ readiness }}</p>
      </div>
      <div>
        <p class="text-sm text-slate-400">评分项覆盖</p>
        <p class="mt-1 text-2xl font-semibold">{{ rubricCoverage }}</p>
      </div>
      <div>
        <p class="text-sm text-slate-400">关键风险</p>
        <p class="mt-1 text-2xl font-semibold">{{ criticalRisks }}</p>
      </div>
    </div>
    <UButton class="mt-6" to="/report" icon="i-lucide-folder-open">查看 Mock 报告</UButton>
  </UCard>
</template>
