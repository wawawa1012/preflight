<script setup lang="ts">
import { ref } from 'vue'
import type { MaterialPreflightSummary } from '../types/contracts'
import { formatSavedAt } from '../utils/format'

// 报告中心：只展示只读装配出的预审摘要，不做满足判定。
const summaries = ref<MaterialPreflightSummary[]>([])
const loading = ref(true)
const error = ref('')

async function loadSummaries() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/v1/preflight-summaries')
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    summaries.value = body as MaterialPreflightSummary[]
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

// 行状态只用已实现能力：已确认依据 k / n 项（来自只读装配摘要）；标准版本不可用时按未评估展示。
function criteriaLabel(item: MaterialPreflightSummary) {
  if (item.criteria_total === null || item.criteria_total === undefined) return '未评估'
  return `已确认依据 ${item.criteria_with_citations ?? 0} / ${item.criteria_total} 项`
}

function criteriaColor(item: MaterialPreflightSummary): 'neutral' | 'success' {
  return item.criteria_total === null || item.criteria_total === undefined ? 'neutral' : 'success'
}

loadSummaries()
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 py-20">
    <p class="mb-4 text-sm font-medium text-violet-400">WORKBENCH</p>
    <h1 class="text-4xl font-semibold tracking-tight">让关键结论回到原文</h1>
    <p class="mt-5 text-slate-400">核验是按每条审查要求在原文找依据，不是打分。</p>

    <div class="mt-8 flex flex-wrap gap-3">
      <UButton to="/materials/new" icon="i-lucide-upload">添加材料</UButton>
      <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">材料库</UButton>
      <UButton to="/compare" color="neutral" variant="ghost" size="sm" icon="i-lucide-git-compare">两材料对照</UButton>
    </div>
    <p class="mt-3 text-xs text-slate-500">上传后直接进入核验页</p>

    <section class="mt-12">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-medium">预审概览</h2>
        <span class="text-xs text-slate-500">{{ summaries.length }} 份材料</span>
      </div>

      <UCard v-if="loading" class="mt-4">
        <p class="text-sm text-slate-400">正在读取预审摘要…</p>
      </UCard>
      <UCard v-else-if="error" class="mt-4">
        <p class="text-sm text-red-400" role="alert">无法加载预审摘要：{{ error }}</p>
        <UButton class="mt-4" size="sm" icon="i-lucide-refresh-cw" @click="loadSummaries">重试</UButton>
      </UCard>
      <UCard v-else-if="summaries.length === 0" class="mt-4">
        <p class="text-sm text-slate-400">还没有材料。先上传一份 Markdown 并绑定评分标准。</p>
        <UButton class="mt-4" to="/materials/new" icon="i-lucide-upload">添加材料</UButton>
      </UCard>

      <div v-else class="mt-4 divide-y divide-slate-800 overflow-hidden rounded-lg border border-slate-800">
        <RouterLink
          v-for="item in summaries"
          :key="item.material_id"
          :to="item.bound ? `/materials/${item.material_id}/report` : `/materials/${item.material_id}`"
          class="block px-4 py-3 transition hover:bg-slate-800/40"
        >
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="min-w-0">
              <p class="truncate text-sm text-slate-200">{{ item.filename }}</p>
              <p class="mt-1 text-xs text-slate-500">{{ item.block_count }} 段原文 · {{ formatSavedAt(item.created_at) }}</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <template v-if="item.bound">
                <UBadge color="neutral" variant="subtle" size="sm">已绑定 rev{{ item.rubric_revision }}</UBadge>
                <UBadge :color="criteriaColor(item)" variant="subtle" size="sm">{{ criteriaLabel(item) }}</UBadge>
                <UBadge v-if="item.criteria_without_citations" color="neutral" variant="subtle" size="sm">
                  当前范围尚未发现引用 {{ item.criteria_without_citations }} 项
                </UBadge>
              </template>
              <UBadge v-else color="warning" variant="subtle" size="sm">未绑定</UBadge>
            </div>
          </div>
        </RouterLink>
      </div>
    </section>
  </main>
</template>
