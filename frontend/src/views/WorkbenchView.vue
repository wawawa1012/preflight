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
    <p class="mb-4 text-sm font-medium text-violet-400">WORKBENCH / MOCK</p>
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
      <h2 class="text-lg font-medium">Materials</h2>
      <p class="mt-2 text-sm text-slate-400">
        上传 Markdown 生成 Block 预览并保存；已保存材料可随时打开，刷新或重启后端后仍在。
      </p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton to="/materials/new" icon="i-lucide-plus">添加材料</UButton>
        <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">查看材料库</UButton>
      </div>
    </UCard>
    <UCard class="mt-10">
      <h2 class="text-lg font-medium">开发诊断</h2>
      <p class="mt-2 text-sm text-slate-400">后端连通性检查，仅用于本地开发；不是产品功能。</p>
      <UButton class="mt-6" color="neutral" variant="subtle" icon="i-lucide-plug" :loading="checking" @click="checkBackend">检查后端连接</UButton>
      <p class="mt-3 text-sm text-slate-400" role="status">{{ status }}</p>
    </UCard>
  </main>
</template>
