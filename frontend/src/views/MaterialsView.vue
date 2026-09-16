<script setup lang="ts">
import { computed, ref } from 'vue'
import type { MaterialSummary } from '../types/contracts'
import { formatSavedAt } from '../utils/format'

const materials = ref<MaterialSummary[]>([])
const loading = ref(true)
const error = ref('')

async function loadMaterials() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/v1/materials')
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    materials.value = body as MaterialSummary[]
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

// 文件类型只从 filename 后缀展示，不新增字段。
function formatLabel(filename: string) {
  const parts = filename.split('.')
  return parts.length > 1 ? parts[parts.length - 1].toUpperCase() : 'FILE'
}

// 右侧 rail 只展示由列表响应直接计算的真实数据，不引入后端 KPI。
const totalBlocks = computed(() => materials.value.reduce((sum, item) => sum + item.block_count, 0))
// 列表已按保存时间倒序，第一条即最近保存。
const latestSavedAt = computed(() => (materials.value.length > 0 ? formatSavedAt(materials.value[0].created_at) : ''))

loadMaterials()
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-10">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="text-sm font-medium text-violet-400">MATERIALS</p>
        <h1 class="mt-2 text-3xl font-semibold tracking-tight">Materials</h1>
        <p class="mt-2 text-sm text-slate-400">Preflight 的 evidence sources：每条预检结论都回溯到这些原文。</p>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
        <UButton to="/materials/new" icon="i-lucide-plus">添加材料</UButton>
      </div>
    </div>

    <UCard v-if="loading" class="mt-8">
      <p class="text-sm text-slate-400">正在读取材料列表…</p>
    </UCard>

    <UCard v-else-if="error" class="mt-8">
      <h2 class="text-lg font-medium">无法加载材料列表</h2>
      <p class="mt-2 text-sm text-slate-400">请求失败：{{ error }}</p>
      <UButton class="mt-6" icon="i-lucide-refresh-cw" @click="loadMaterials">重试</UButton>
    </UCard>

    <!-- 空态：一句说明 + 唯一 CTA，不做填充式页面。 -->
    <div v-else-if="materials.length === 0" class="mt-16 text-center">
      <UIcon name="i-lucide-folder-open" class="mx-auto text-3xl text-slate-600" />
      <p class="mt-4 text-sm text-slate-300">还没有已保存的材料</p>
      <p class="mt-1 text-xs text-slate-500">上传第一份 Markdown，生成可追溯的 Block 与原文件行号。</p>
      <UButton class="mt-6" to="/materials/new" icon="i-lucide-plus">添加第一份材料</UButton>
    </div>

    <div v-else class="mt-8 grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(240px,1fr)]">
      <section class="divide-y divide-slate-800 self-start overflow-hidden rounded-lg border border-slate-800">
        <RouterLink
          v-for="item in materials"
          :key="item.id"
          :to="`/materials/${item.id}`"
          class="flex items-center justify-between gap-3 px-3 py-2.5 text-slate-200 transition hover:bg-slate-800/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-violet-500"
        >
          <span class="flex min-w-0 items-center gap-2">
            <span class="truncate text-sm">{{ item.filename }}</span>
            <UBadge color="neutral" variant="subtle" size="sm">{{ formatLabel(item.filename) }}</UBadge>
          </span>
          <span class="flex shrink-0 items-center gap-4 text-xs text-slate-500">
            <span>{{ item.block_count }} blocks</span>
            <span>{{ formatSavedAt(item.created_at) }}</span>
          </span>
        </RouterLink>
      </section>

      <aside class="self-start rounded-lg border border-slate-800 p-4 lg:sticky lg:top-4">
        <h2 class="text-xs font-medium uppercase tracking-wide text-slate-500">概览</h2>
        <dl class="mt-4 space-y-3">
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-xs text-slate-500">已保存材料</dt>
            <dd class="text-sm font-medium text-slate-200">{{ materials.length }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-xs text-slate-500">总 Block 数</dt>
            <dd class="text-sm font-medium text-slate-200">{{ totalBlocks }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-xs text-slate-500">最近保存</dt>
            <dd class="text-sm font-medium text-slate-200">{{ latestSavedAt }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-xs text-slate-500">支持格式</dt>
            <dd class="text-sm font-medium text-slate-200">Markdown（.md，≤ 1 MiB）</dd>
          </div>
        </dl>
      </aside>
    </div>
  </main>
</template>
