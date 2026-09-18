<script setup lang="ts">
import { ref } from 'vue'
import type { MaterialPreflightSummary } from '../types/contracts'
import { formatSavedAt } from '../utils/format'

// 报告中心：只展示只读装配出的预审摘要，不做满足判定。
const summaries = ref<MaterialPreflightSummary[]>([])
const loading = ref(true)
const error = ref('')

const status = ref('尚未检查')
const checking = ref(false)

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

loadSummaries()
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 py-20">
    <p class="mb-4 text-sm font-medium text-violet-400">WORKBENCH</p>
    <h1 class="text-4xl font-semibold tracking-tight">让关键结论回到原文</h1>
    <p class="mt-5 text-slate-400">按评审标准预审材料。每条要求显示已确认关联数；没有引用时说明查过哪里。</p>

    <div class="mt-8 flex flex-wrap gap-3">
      <UButton to="/materials/new" icon="i-lucide-upload">开始预检</UButton>
      <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">材料库</UButton>
    </div>

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
        <UButton class="mt-4" to="/materials/new" icon="i-lucide-upload">开始预检</UButton>
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
              <p class="mt-1 text-xs text-slate-500">{{ item.block_count }} 个 Block · {{ formatSavedAt(item.created_at) }}</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <template v-if="item.bound">
                <UBadge color="neutral" variant="subtle" size="sm">已绑定 rev{{ item.rubric_revision }}</UBadge>
                <UBadge color="success" variant="subtle" size="sm">已确认关联 {{ item.verified_citation_count }} 条</UBadge>
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

    <div class="mt-12 flex flex-wrap items-center gap-3 border-t border-slate-800 pt-4 text-xs text-slate-500">
      <RouterLink to="/report" class="hover:text-slate-300">结构演示（Mock）</RouterLink>
      <span>·</span>
      <UButton size="xs" color="neutral" variant="ghost" icon="i-lucide-plug" :loading="checking" @click="checkBackend">
        检查后端连接
      </UButton>
      <span>开发诊断，不是产品功能</span>
      <span role="status">{{ status }}</span>
    </div>
  </main>
</template>
