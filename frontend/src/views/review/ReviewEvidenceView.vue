<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import type { AgentProposal, Criterion, MaterialPreflightSummary, Rubric } from '../../types/contracts'
import { reviewContextKey } from './reviewContext'
import { evidenceApi } from '../../services/evidence'
import { createRequestScope } from '../../utils/requestScope'
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
// 读（初始加载）与跑（运行队列/单项重试）使用独立 scope：重新加载不取消在飞运行，重新运行不取消加载。
const loadScope = createRequestScope()
const runScope = createRequestScope()
// 历史提案加载失败的材料：状态必须呈现为「未知」，不得当作「未运行」。
const proposalLoadFailed = ref<Set<string>>(new Set())

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
  // 历史提案拉取失败 ≠ 未运行：如实告知状态未知。
  if (proposalLoadFailed.value.has(materialId)) return { label: '历史状态未知', tone: 'waiting' }
  const proposal = latestProposal(materialId, criterionId)
  if (!proposal) return { label: '未运行', tone: 'idle' }
  if (proposal.status === 'failed') return { label: '上次运行失败', tone: 'failed' }
  return proposal.candidates.length > 0
    ? { label: `候选 ${proposal.candidates.length} 条`, tone: 'success' }
    : { label: '完成：未找到候选', tone: 'empty' }
}

async function load() {
  const ticket = loadScope.begin({ reviewId: reviewId.value, purpose: 'load' as const })
  loading.value = true
  loadError.value = ''
  queue.value = []
  selected.value = new Set()
  proposalLoadFailed.value = new Set()
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
    const currentRubric =
      (Array.isArray(rubricsBody) ? (rubricsBody as Rubric[]) : []).find(
        (entry) => current && entry.id === current.rubric_id && entry.revision === current.rubric_revision,
      ) ?? null
    const currentSummaries = Array.isArray(summariesBody) ? (summariesBody as MaterialPreflightSummary[]) : []
    if (!ticket.commit(() => {
      rubric.value = currentRubric
      summaries.value = currentSummaries
    })) return

    // 每个已绑定成员的历史提案并行拉取（确定性 GET）；单份失败只标记该材料，不拖垮整页。
    const bound = members.value.filter((member) => summaryOf(member.material_id)?.bound)
    const settled = await Promise.all(
      bound.map(async (member) => {
        try {
          const proposals = await evidenceApi.listProposals(member.material_id)
          return [member.material_id, proposals, true] as const
        } catch {
          return [member.material_id, [] as AgentProposal[], false] as const
        }
      }),
    )
    ticket.commit(() => {
      proposalsByMaterial.value = Object.fromEntries(settled.map(([materialId, proposals]) => [materialId, proposals]))
      proposalLoadFailed.value = new Set(settled.filter(([, , ok]) => !ok).map(([materialId]) => materialId))
      // 默认勾选：尚无 completed 提案的 criterion（历史未知的也勾选，运行后才有真相）。
      const defaults = new Set<string>()
      for (const member of bound) {
        for (const criterion of criteria.value) {
          if (!latestProposal(member.material_id, criterion.id)) defaults.add(itemKey(member.material_id, criterion.id))
        }
      }
      selected.value = defaults
    })
  } catch (cause) {
    ticket.commit(() => {
      loadError.value = cause instanceof Error ? cause.message : '未知错误'
    })
  } finally {
    ticket.commit(() => {
      loading.value = false
    })
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

// 逐项提交：不可变替换 queue 中的项，完成一项立即进入响应式状态，不依赖原对象突变。
function patchItem(target: RunItem, patch: Partial<RunItem>) {
  queue.value = queue.value.map((item) => (item === target || (item.materialId === target.materialId && item.criterionId === target.criterionId) ? { ...item, ...patch } : item))
}

// 单项重试：只执行目标项，不动其他结果；与全局 run 共用 run scope，begin 即作废旧 run ticket。
// 只在非 running 时允许；换 Review 后由 watch 作废，旧响应不落地。
async function retryItem(materialId: string, criterionId: string) {
  if (running.value) return
  const item = queueItem(materialId, criterionId)
  if (!item || item.state !== 'failed') return
  const ticket = runScope.begin({ reviewId: reviewId.value, purpose: 'run' as const })
  patchItem(item, { state: 'running', detail: '' })
  try {
    const proposal = await evidenceApi.runCriterion(materialId, criterionId)
    ticket.commit(() => {
      if (proposal.status === 'failed') {
        patchItem(item, { state: 'failed', detail: proposal.error ?? '运行失败' })
      } else if (proposal.candidates.length > 0) {
        patchItem(item, { state: 'success', detail: `候选 ${proposal.candidates.length} 条` })
      } else {
        patchItem(item, { state: 'empty', detail: '' })
      }
    })
    // 刷新该材料历史提案，让裁决入口看到最新状态。
    try {
      const proposals = await evidenceApi.listProposals(materialId)
      ticket.commit(() => {
        proposalsByMaterial.value = { ...proposalsByMaterial.value, [materialId]: proposals }
      })
    } catch {
      // 列表刷新失败不影响已展示的该项结果。
    }
  } catch (cause) {
    ticket.commit(() => {
      patchItem(item, { state: 'failed', detail: cause instanceof Error ? cause.message : '未知错误' })
    })
  }
}

// 渐进执行：3 个 worker 持续消费整个队列；每项完成立即落态；迟到响应由 run scope 丢弃。
async function runSelected() {
  if (running.value || selected.value.size === 0) return
  const ticket = runScope.begin({ reviewId: reviewId.value, purpose: 'run' as const })
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
      if (!ticket.isCurrent()) return
      patchItem(item, { state: 'running' })
      try {
        const proposal = await evidenceApi.runCriterion(item.materialId, item.criterionId)
        ticket.commit(() => {
          if (proposal.status === 'failed') {
            patchItem(item, { state: 'failed', detail: proposal.error ?? '运行失败' })
          } else if (proposal.candidates.length > 0) {
            patchItem(item, { state: 'success', detail: `候选 ${proposal.candidates.length} 条` })
          } else {
            patchItem(item, { state: 'empty', detail: '' })
          }
        })
      } catch (cause) {
        ticket.commit(() => {
          patchItem(item, { state: 'failed', detail: cause instanceof Error ? cause.message : '未知错误' })
        })
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(MAX_CONCURRENCY, items.length) }, () => worker()))
  // 收尾写入只允许在 commit 内：旧任务不得清掉新任务的 running，也不得覆盖新上下文的历史提案。
  if (!ticket.isCurrent()) return
  // 运行结束：按材料批量刷新历史提案（每份材料一次），让「裁决入口」看到最新状态。
  const affected = [...new Set(items.filter((item) => item.state !== 'waiting' && item.state !== 'running').map((item) => item.materialId))]
  const refreshed = await Promise.all(
    affected.map(async (materialId) => {
      try {
        return [materialId, await evidenceApi.listProposals(materialId), true] as const
      } catch {
        return [materialId, [] as AgentProposal[], false] as const
      }
    }),
  )
  ticket.commit(() => {
    const next = { ...proposalsByMaterial.value }
    const failed = new Set(proposalLoadFailed.value)
    for (const [materialId, proposals, ok] of refreshed) {
      if (ok) {
        next[materialId] = proposals
        failed.delete(materialId)
      }
    }
    proposalsByMaterial.value = next
    proposalLoadFailed.value = failed
  })
  ticket.commit(() => {
    running.value = false
  })
}

// 切换 Review：作废在飞响应（读与跑都作废），清空本视图全部运行态。
watch(
  () => review.value?.id,
  (id) => {
    loadScope.invalidate()
    runScope.invalidate()
    running.value = false
    if (id) void load()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  loadScope.invalidate()
  runScope.invalidate()
})
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
              <!-- 单项重试：只重跑这一条，不影响其他项的结果。 -->
              <UButton
                v-if="queueItem(member.material_id, criterion.id)?.state === 'failed'"
                size="xs"
                color="neutral"
                variant="ghost"
                icon="i-lucide-refresh-cw"
                :disabled="running"
                @click="retryItem(member.material_id, criterion.id)"
              >
                重试
              </UButton>
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
