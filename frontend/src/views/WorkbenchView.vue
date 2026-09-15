<script setup lang="ts">
import { ref } from 'vue'
import ProjectCard from '../components/ProjectCard.vue'

// 本页唯一的 mock 项目数据：readiness 使用 contract 的 Metrics.submission_readiness 枚举，不用自创百分制。
const project = {
  name: 'Preflight · AIC 2026',
  readiness: 'blocked',
  rubricCoverage: '0 / 3',
  criticalRisks: 1,
}

const status = ref('尚未检查')
const checking = ref(false)
// 这里只检查连通性；Phase 0 不运行任何材料分析。
async function checkBackend() {
  checking.value = true
  try {
    const response = await fetch('/api/v1/health')
    if (!response.ok) throw new Error('Health check failed')
    const result = await response.json()
    status.value = result.status === 'ok' ? '后端连接正常' : '后端状态异常'
  } catch {
    status.value = '无法连接，请按 README 启动后端'
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <main class="mx-auto max-w-3xl px-6 py-20">
    <p class="mb-4 text-sm font-medium text-violet-400">PREFLIGHT / PHASE 0</p>
    <h1 class="text-4xl font-semibold tracking-tight">参赛材料的 CI</h1>
    <p class="mt-5 text-slate-400">提交之前，让重要结论回到真实证据。</p>
    <ProjectCard
      class="mt-10"
      :name="project.name"
      :readiness="project.readiness"
      :rubric-coverage="project.rubricCoverage"
      :critical-risks="project.criticalRisks"
    />
    <UCard class="mt-10">
      <h2 class="text-lg font-medium">工程骨架已就绪</h2>
      <p class="mt-2 text-sm text-slate-400">当前为空壳；Mock 演示在下一阶段实现。</p>
      <UButton class="mt-6" icon="i-lucide-plug" :loading="checking" @click="checkBackend">检查后端连接</UButton>
      <p class="mt-3 text-sm text-slate-400" role="status">{{ status }}</p>
    </UCard>
  </main>
</template>
