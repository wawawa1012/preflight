<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import type { AgentProposal, Criterion, MaterialPreflightSummary, Rubric } from '../../types/contracts'
import { reviewContextKey } from './reviewContext'
import { evidenceApi } from '../../services/evidence'
import { createAsyncGuard } from '../../utils/asyncGuard'
import { materialIdentity } from '../../utils/materialIdentity'
import EmptyState from '../../components/review/EmptyState.vue'

// 依据（Evidence）视图：把「一次运行一个 criterion」的现有 API 升级成渐进执行。
// - 有限并发队列 MAX 3，持续消费全部用户选择，不 slice 截断；
// - 每项独立状态 waiting/running/success/empty/failed，一项失败不遮挡其他；
// - stale guard：切换 Review 或再次运行时，迟到响应一律丢弃；
// - 裁决（接受/拒绝候选）仍在材料工作台，这里只负责执行与状态呈现。
const context = inject(reviewContextKey)
if (!context) throw new Error('ReviewEvidenceView 必须在 ReviewWorkspaceView 内使用')
const { review } = context

const MAX_CONCURRENCY = 3

type RunState = 'waiting' | 'running' | 'success' | 'empty' | 'failed'
interface RunItem {
  materialId: string
  criterionId: string
  state: RunState
  detail: string
}

const rubric = ref<Rubric | null>(null)
const summaries = ref<MaterialPreflightSummary[]>([])
const proposalsByMaterial = ref<Record<string, AgentProposal[]>>({})
const loading = ref(true)
const loadError = ref('')

const selected = ref<Set<string>>(new Set())
const queue = ref<RunItem[]>([])
const running = ref(false)
const guard = createAsyncGuard()

const reviewId = computed(() => review.value?.id ?? '')
const members = computed(() => review.value?.materials ?? [])
const basePath = computed(() => `/reviews/${reviewId.value}`)
const criteria = computed<Criterion[]>(() => rubric.value?.criteria ?? [])

function summaryOf(materialId: string) {
  return summaries.value.find((summary) => summary.material_id === materialId)
}
const boundMembers = computed(() => members.value.filter((member) => summaryOf(member.material_id)?.bound))

function identityOf(materialId: string, label: string) {
  return materialIdentity(label, summaryOf(materialId)?.filename ?? '')
}

function itemKey(materialId: string, criterionId: string) {
  return `${materialId}:${criterionId}`
}

// 每个 criterion 的最新一次提案：已持久化在服务端，进入页面即可见（确定性优先）。
function latestProposal(materialId: string, criterionId: string): AgentProposal | null {
  const list = proposalsByMaterial.value[materialId] ?? []
  return list.find((proposal) => proposal.criterion_id === criterionId) ?? null
}

function queueItem(materialId: string, criterionId: string): RunItem | null {
  return queue.value.find((item) => item.materialId === materialId && item.criterionId === criterionId) ?? null
}

function stateOf(materialId: string, criterionId: string): { label: string; tone: 'waiting' | 'running' | 'success' | 'empty' | 'failed' | 'idle' } {
  const item = queueItem(materialId, criterionId)
  if (item) {
    const map = {
      waiting: { label: '等待', tone: 'waiting' as const },
      running: { label: '运行中', tone: 'running' as const },
      success: { label: item.detail, tone: 'success' as const },
      empty: { label: '完成：未找到候选', tone: 'empty' as const },
      failed: { label: `失败：${item.detail}`, tone: 'failed' as const },
    }
    return map[item.state]
  }
  const proposal = latestProposal(materialId, criterionId)
  if (!proposal) return { label: '未运行', tone: 'idle' }
  if (proposal.status === 'failed') return { label: '上次运行失败', tone: 'failed' }
  return proposal.candidates.length > 0
    ? { label: `候选 ${proposal.candidates.length} 条`, tone: 'success' }
    : { label: '完成：未找到候选', tone: 'empty' }
}

async function load() {
  loading.value = true
  loadError.value = ''
  queue.value = []
  selected.value = new Set()
  try {
    const [rubricsResponse, summariesResponse] = await Promise.all([
      fetch('/api/v1/rubrics'),
      fetch('/api/v1/preflight-summaries'),
    ])
    const rubricsBody = await rubricsResponse.json().catch(() => null)
    const summariesBody = await summariesResponse.json().catch(() => null)
    if (!rubricsResponse.ok) throw new Error(rubricsBody?.message ?? `HTTP ${rubricsResponse.status}`)
    if (!summariesResponse.ok) throw new Error(summariesBody?.message ?? `HTTP ${summariesResponse.status}`)
    const current = review.value
    rubric.value =
      (Array.isArray(rubricsBody) ? (rubricsBody as Rubric[]) : []).find(
        (entry) => current && entry.id === current.rubric_id && entry.revision === current.rubric_revision,
      ) ?? null
    summaries.value = Array.isArray(summariesBody) ? (summariesBody as MaterialPreflightSummary[]) : []

    // 每个已绑定成员的历史提案并行拉取（确定性 GET）。
    const bound = members.value.filter((member) => summaryOf(member.material_id)?.bound)
    const settled = await Promise.all(
      bound.map(async (member) => {
        try {
          const proposals = await evidenceApi.listProposals(member.material_id)
          return [member.material_id, proposals] as const
        } catch {
          return [member.material_id, []] as const
        }
      }),
    )
    proposalsByMaterial.value = Object.fromEntries(settled)
    // 默认勾选：尚无 completed 提案的 criterion。
    const defaults = new Set<string>()
    for (const member of bound) {
      for (const criterion of criteria.value) {
        if (!latestProposal(member.material_id, criterion.id)) defaults.add(itemKey(member.material_id, criterion.id))
      }
    }
    selected.value = defaults
  } catch (cause) {
    loadError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

function toggle(materialId: string, criterionId: string) {
  const next = new Set(selected.value)
  const key = itemKey(materialId, criterionId)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selected.value = next
}

const selectedCount = computed(() => selected.value.size)

// 渐进执行：3 个 worker 持续消费整个队列；每项完成立即落态；迟到响应由 guard 丢弃。
async function runSelected() {
  if (running.value || selected.value.size === 0) return
  const token = guard.next()
  running.value = true
  const items: RunItem[] = []
  for (const member of boundMembers.value) {
    for (const criterion of criteria.value) {
      if (selected.value.has(itemKey(member.material_id, criterion.id))) {
        items.push({ materialId: member.material_id, criterionId: criterion.id, state: 'waiting', detail: '' })
      }
    }
  }
  queue.value = items
  let cursor = 0
  async function worker() {
    while (cursor < items.length) {
      const item = items[cursor]
      cursor += 1
      if (!guard.isCurrent(token)) return
      item.state = 'running'
      try {
        const proposal = await evidenceApi.runCriterion(item.materialId, item.criterionId)
        if (!guard.isCurrent(token)) return
        if (proposal.status === 'failed') {
          item.state = 'failed'
          item.detail = proposal.error ?? '运行失败'
        } else if (proposal.candidates.length > 0) {
          item.state = 'success'
          item.detail = `候选 ${proposal.candidates.length} 条`
        } else {
          item.state = 'empty'
        }
      } catch (cause) {
        if (!guard.isCurrent(token)) return
        item.state = 'failed'
        item.detail = cause instanceof Error ? cause.message : '未知错误'
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(MAX_CONCURRENCY, items.length) }, () => worker()))
  if (guard.isCurrent(token)) {
    // 运行结束：把新提案并入历史列表，让「裁决入口」看到最新状态。
    for (const item of items) {
      if (item.state === 'success' || item.state === 'empty' || item.state === 'failed') {
        try {
          const proposals = await evidenceApi.listProposals(item.materialId)
          if (!guard.isCurrent(token)) return
          proposalsByMaterial.value = { ...proposalsByMaterial.value, [item.materialId]: proposals }
        } catch {
          // 列表刷新失败不影响已展示的逐项结果。
        }
      }
    }
  }
  running.value = false
}

// 切换 Review：作废在飞响应，清空本视图全部运行态。
watch(
  () => review.value?.id,
  (id) => {
    guard.invalidate()
    running.value = false
    if (id) void load()
  },
  { immediate: true },
)
</script>

<template>
  <div class="space-y-8">
    <section>
      <h2 class="text-sm font-medium tracking-wide text-slate-200">依据</h2>
      <p class="mt-1 text-xs leading-relaxed text-slate-500">
        按本次审查的标准逐条在原文里找依据。一次运行一条要求，结果立刻出现；确认候选在材料工作台完成。
      </p>

      <EmptyState
        v-if="members.length === 0"
        class="mt-4 rounded-xl bg-slate-950/40"
        title="本次审查还没有材料"
        hint="先在材料页加入至少一份材料。"
      >
        <UButton :to="`${basePath}/members`" icon="i-lucide-files">管理材料</UButton>
      </EmptyState>

      <p v-else-if="loading" class="mt-4 text-sm text-slate-400">正在读取标准与材料状态…</p>

      <div v-else-if="loadError" class="mt-4 rounded-xl bg-slate-950/40 px-5 py-4">
        <p class="text-sm text-red-400" role="alert">无法加载依据视图：{{ loadError }}</p>
        <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="load">重试</UButton>
      </div>

      <template v-else>
        <div v-if="boundMembers.length === 0" class="mt-4 rounded-xl bg-amber-950/30 px-5 py-4">
          <p class="text-sm text-amber-200">本次审查的材料还没有应用审查标准。</p>
          <p class="mt-1 text-xs text-slate-500">在「材料」页把材料加入审查并应用标准后，才能运行依据审计。</p>
        </div>

        <div v-else class="mt-4 flex flex-wrap items-center gap-3">
          <UButton icon="i-lucide-play" :loading="running" :disabled="selectedCount === 0" @click="runSelected">
            {{ running ? '正在运行…' : `运行所选（${selectedCount}）` }}
          </UButton>
          <span class="text-xs text-slate-500">每次最多同时运行 {{ MAX_CONCURRENCY }} 条；完成一条立即显示。</span>
        </div>

        <div v-for="member in boundMembers" :key="member.material_id" class="mt-6">
          <div class="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-800 pb-2">
            <h3 class="text-sm font-medium text-slate-200">
              {{ identityOf(member.material_id, member.label).primary }}
              <span v-if="identityOf(member.material_id, member.label).secondary" class="ml-2 font-mono text-[11px] font-normal text-slate-500">
                {{ identityOf(member.material_id, member.label).secondary }}
              </span>
            </h3>
            <UButton size="xs" color="neutral" variant="ghost" :to="`/materials/${member.material_id}`" icon="i-lucide-arrow-right">
              去确认依据
            </UButton>
          </div>
          <ul class="mt-2 divide-y divide-slate-800/60">
            <li v-for="criterion in criteria" :key="criterion.id" class="flex flex-wrap items-center gap-3 py-2.5">
              <input
                type="checkbox"
                class="size-4 shrink-0 accent-violet-500"
                :checked="selected.has(itemKey(member.material_id, criterion.id))"
                :disabled="running"
                :aria-label="`选择 ${criterion.title}`"
                @change="toggle(member.material_id, criterion.id)"
              />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm text-slate-200">{{ criterion.title }}</span>
                <span class="block truncate text-[11px] text-slate-600">{{ criterion.requirement }}</span>
              </span>
              <span
                class="shrink-0 text-xs"
                :class="{
                  waiting: 'text-slate-500',
                  running: 'text-violet-300',
                  success: 'text-emerald-300',
                  empty: 'text-slate-500',
                  failed: 'text-red-400',
                  idle: 'text-slate-600',
                }[stateOf(member.material_id, criterion.id).tone]"
              >{{ stateOf(member.material_id, criterion.id).label }}</span>
            </li>
          </ul>
        </div>

        <p v-if="members.length > boundMembers.length" class="mt-4 text-xs text-slate-600">
          {{ members.length - boundMembers.length }} 份材料尚未应用审查标准，未列出。
        </p>
      </template>
    </section>
  </div>
</template>
