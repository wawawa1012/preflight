<script setup lang="ts">
import { ref } from 'vue'
import type { MaterialPreflightSummary } from '../types/contracts'
import { formatSavedAt } from '../utils/format'
import PageHeader from '../components/review/PageHeader.vue'
import EmptyState from '../components/review/EmptyState.vue'

// 首页：只读装配的审查摘要 + 固定入口；只陈述已实现能力。
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
  <main class="mx-auto max-w-6xl px-6 py-10">
    <PageHeader title="让重要结论有据可查" subtitle="按你的审查标准检查材料中的依据、关键陈述、一致性与风险。" />

    <!-- 主入口：一张大卡承担唯一 CTA，不铺一排小按钮。 -->
    <UCard class="mt-8">
      <div class="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p class="text-base font-medium text-slate-100">开始审查</p>
          <p class="mt-1 text-sm text-slate-400">上传材料并按标准检查</p>
        </div>
        <UButton to="/materials/new" size="lg" icon="i-lucide-upload">开始审查</UButton>
      </div>
    </UCard>

    <section class="mt-10">
      <h2 class="text-sm font-medium text-slate-400">快速工具</h2>
      <div class="mt-4 grid gap-3 sm:grid-cols-3">
        <UButton to="/compare" color="neutral" variant="subtle" icon="i-lucide-git-compare" block>一致性检查</UButton>
        <UButton to="/diff" color="neutral" variant="subtle" icon="i-lucide-git-compare-arrows" block>修改效果</UButton>
        <UButton to="/grill" color="neutral" variant="subtle" icon="i-lucide-messages-square" block>质询</UButton>
      </div>
    </section>

    <section class="mt-10">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-medium text-slate-400">最近审查</h2>
        <span class="text-xs text-slate-500">{{ summaries.length }} 份材料</span>
      </div>

      <UCard v-if="loading" class="mt-4">
        <p class="text-sm text-slate-400">正在读取审查摘要…</p>
      </UCard>
      <UCard v-else-if="error" class="mt-4">
        <p class="text-sm text-red-400" role="alert">无法加载审查摘要：{{ error }}</p>
        <UButton class="mt-4" size="sm" icon="i-lucide-refresh-cw" @click="loadSummaries">重试</UButton>
      </UCard>
      <EmptyState
        v-else-if="summaries.length === 0"
        class="mt-4"
        title="还没有材料"
        hint="上传后这里会列出每份材料的审查摘要。"
      >
        <UButton to="/materials/new" icon="i-lucide-upload">开始审查</UButton>
      </EmptyState>

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
