<script setup lang="ts">
import { computed, ref } from 'vue'
import type { MaterialPreflightSummary, MaterialSummary } from '../types/contracts'
import { formatSavedAt } from '../utils/format'
import { formatLabel } from '../utils/formatLabel'
import PageHeader from '../components/review/PageHeader.vue'
import EmptyState from '../components/review/EmptyState.vue'

const materials = ref<MaterialSummary[]>([])
// 行内 k/n 只来自只读装配的 preflight-summaries，不在前端另算一套计数。
const summaries = ref<MaterialPreflightSummary[]>([])
const loading = ref(true)
const error = ref('')

// 行内删除确认：pendingDelete 是唯一确认目标，动作走 UModal，不使用浏览器原生确认框。
const pendingDelete = ref<MaterialSummary | null>(null)
const deleting = ref(false)
const deleteError = ref('')

const summaryById = computed(() => new Map(summaries.value.map((item) => [item.material_id, item])))

type BadgeColor = 'neutral' | 'warning' | 'success'

// 状态词分级：已确认依据 k / n 项 / 未绑定 / 未评估；只陈述已实现能力的输出。
function relationshipLabel(item: MaterialSummary) {
  const summary = summaryById.value.get(item.id)
  if (!summary) return '未评估'
  if (!summary.bound) return '未绑定'
  if (summary.criteria_total === null || summary.criteria_total === undefined) return '未评估'
  return `已确认依据 ${summary.criteria_with_citations ?? 0} / ${summary.criteria_total} 项`
}

function relationshipColor(item: MaterialSummary): BadgeColor {
  const summary = summaryById.value.get(item.id)
  if (!summary) return 'neutral'
  if (!summary.bound) return 'warning'
  if (summary.criteria_total === null || summary.criteria_total === undefined) return 'neutral'
  return 'success'
}

// 待核对提示：复用摘要里已确认依据之外的引用缺口，不另算口径。
function pendingHint(item: MaterialSummary) {
  const summary = summaryById.value.get(item.id)
  if (!summary || !summary.bound) return 0
  return summary.criteria_without_citations ?? 0
}

async function loadMaterials() {
  loading.value = true
  error.value = ''
  try {
    const [materialsResponse, summariesResponse] = await Promise.all([
      fetch('/api/v1/materials'),
      fetch('/api/v1/preflight-summaries'),
    ])
    const materialsBody = await materialsResponse.json().catch(() => null)
    if (!materialsResponse.ok) {
      throw new Error(materialsBody && materialsBody.message ? materialsBody.message : `HTTP ${materialsResponse.status}`)
    }
    const summariesBody = await summariesResponse.json().catch(() => null)
    if (!summariesResponse.ok) {
      throw new Error(summariesBody && summariesBody.message ? summariesBody.message : `HTTP ${summariesResponse.status}`)
    }
    materials.value = materialsBody as MaterialSummary[]
    summaries.value = summariesBody as MaterialPreflightSummary[]
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

function requestDelete(item: MaterialSummary) {
  if (deleting.value) return
  deleteError.value = ''
  pendingDelete.value = item
}

function cancelDelete() {
  if (deleting.value) return
  pendingDelete.value = null
  deleteError.value = ''
}

async function confirmDelete() {
  const item = pendingDelete.value
  if (!item || deleting.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    const response = await fetch(`/api/v1/materials/${item.id}`, { method: 'DELETE' })
    // 204（已删除）与 404（本就已不存在）都表示该材料不再存在：按事实移除该行。
    if (!response.ok && response.status !== 404) {
      const body = await response.json().catch(() => null)
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    materials.value = materials.value.filter((entry) => entry.id !== item.id)
    summaries.value = summaries.value.filter((entry) => entry.material_id !== item.id)
    pendingDelete.value = null
  } catch (cause) {
    deleteError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    deleting.value = false
  }
}

// 右侧 rail 只展示由列表响应直接计算的真实数据，不引入后端 KPI。
const boundCount = computed(() => summaries.value.filter((item) => item.bound).length)
// 列表已按保存时间倒序，第一条即最近保存。
const latestSavedAt = computed(() => (materials.value.length > 0 ? formatSavedAt(materials.value[0].created_at) : ''))

loadMaterials()
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-10">
    <PageHeader title="材料" subtitle="所有审查基于这里的材料进行，结论可回溯到原文。">
      <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
      <UButton to="/materials/new" icon="i-lucide-plus">添加材料</UButton>
    </PageHeader>

    <UCard v-if="loading" class="mt-8">
      <p class="text-sm text-slate-400">正在读取材料列表…</p>
    </UCard>

    <UCard v-else-if="error" class="mt-8">
      <h2 class="text-lg font-medium">无法加载材料列表</h2>
      <p class="mt-2 text-sm text-slate-400">请求失败：{{ error }}</p>
      <UButton class="mt-6" icon="i-lucide-refresh-cw" @click="loadMaterials">重试</UButton>
    </UCard>

    <!-- 空态：一句说明 + 唯一 CTA，不做填充式页面。 -->
    <EmptyState
      v-else-if="materials.length === 0"
      class="mt-10"
      title="还没有材料"
      hint="上传第一份材料文件，即可开始按标准审查。"
    >
      <UButton to="/materials/new" icon="i-lucide-plus">添加第一份材料</UButton>
    </EmptyState>

    <div v-else class="mt-8 grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(240px,1fr)]">
      <section class="divide-y divide-slate-800 self-start overflow-hidden rounded-lg border border-slate-800">
        <div
          v-for="item in materials"
          :key="item.id"
          class="flex items-center gap-2 px-3 py-2.5 transition hover:bg-slate-800/40"
        >
          <RouterLink
            :to="`/materials/${item.id}`"
            class="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-3 gap-y-1 py-0.5 text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-violet-500"
          >
            <span class="flex min-w-0 items-center gap-2">
              <span class="truncate text-sm">{{ item.filename }}</span>
              <UBadge color="neutral" variant="subtle" size="sm">{{ formatLabel(item.format) }}</UBadge>
            </span>
            <span class="flex shrink-0 flex-wrap items-center gap-3 text-xs text-slate-500">
              <UBadge :color="relationshipColor(item)" variant="subtle" size="sm">{{ relationshipLabel(item) }}</UBadge>
              <UBadge v-if="pendingHint(item)" color="neutral" variant="subtle" size="sm">
                当前范围尚未发现引用 {{ pendingHint(item) }} 项
              </UBadge>
              <span>{{ formatSavedAt(item.created_at) }}</span>
            </span>
          </RouterLink>
          <UButton
            color="error"
            variant="ghost"
            size="sm"
            icon="i-lucide-trash-2"
            :aria-label="`删除材料 ${item.filename}`"
            @click="requestDelete(item)"
          />
        </div>
      </section>

      <aside class="self-start rounded-lg border border-slate-800 p-4 lg:sticky lg:top-4">
        <h2 class="text-xs font-medium uppercase tracking-wide text-slate-500">概览</h2>
        <dl class="mt-4 space-y-3">
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-xs text-slate-500">已保存材料</dt>
            <dd class="text-sm font-medium text-slate-200">{{ materials.length }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-xs text-slate-500">已绑定审查标准</dt>
            <dd class="text-sm font-medium text-slate-200">{{ boundCount }} / {{ materials.length }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-xs text-slate-500">最近保存</dt>
            <dd class="text-sm font-medium text-slate-200">{{ latestSavedAt }}</dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-xs text-slate-500">支持格式</dt>
            <dd class="text-sm font-medium text-slate-200">Markdown / 纯文本 / Word 文档（.md / .txt / .docx，≤ 1 MiB）</dd>
          </div>
        </dl>
      </aside>
    </div>

    <!-- 行内删除确认：UModal 承担确认动作；删除中不允许关闭。 -->
    <UModal
      :open="pendingDelete !== null"
      :dismissible="!deleting"
      title="删除材料"
      description="删除后无法恢复。"
      @update:open="(value: boolean) => { if (!value) cancelDelete() }"
    >
      <template #body>
        <p class="text-sm text-slate-300">
          确定删除「{{ pendingDelete?.filename }}」？该材料已确认的关联与审查结果将一并删除。
        </p>
        <p v-if="deleteError" class="mt-3 text-sm text-red-400" role="alert">{{ deleteError }}</p>
      </template>
      <template #footer>
        <div class="flex justify-end gap-3">
          <UButton color="neutral" variant="subtle" :disabled="deleting" @click="cancelDelete">取消</UButton>
          <UButton color="error" icon="i-lucide-trash-2" :loading="deleting" @click="confirmDelete">删除</UButton>
        </div>
      </template>
    </UModal>
  </main>
</template>
