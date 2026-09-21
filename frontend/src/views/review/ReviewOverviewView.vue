<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { ConsistencyFinding, MaterialPreflightSummary, MaterialSummary } from '../../types/contracts'
import { reviewContextKey } from './reviewContext'
import { useSessionStore } from '../../stores/session'
import { reviewsApi } from '../../services/reviews'
import { materialIdentity } from '../../utils/materialIdentity'
import type { ActionItemModel } from '../../types/action'
import ActionItem from '../../components/action/ActionItem.vue'
import EmptyState from '../../components/review/EmptyState.vue'

// Review Overview：主视觉 = 真实状态，不是宣传展板。
// 角色区每一行都是「职责 + 当前真实状态 + 真实动作」；没有状态来源就写「尚未运行」，不造数字。
// 材料卡用 materialIdentity 去重（label == filename 只显示一次）。
const context = inject(reviewContextKey)
if (!context) throw new Error('ReviewOverviewView 必须在 ReviewWorkspaceView 内使用')
const { review } = context
const session = useSessionStore()
const router = useRouter()

// 删除本次审查：两步确认；文案必须说清楚材料和材料的审查标准绑定都不受影响。
const confirmingDelete = ref(false)
const deleting = ref(false)
const deleteError = ref('')

async function deleteReview() {
  if (deleting.value || reviewId.value === '') return
  deleting.value = true
  deleteError.value = ''
  try {
    await reviewsApi.remove(reviewId.value)
    router.replace('/')
  } catch (cause) {
    deleteError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    deleting.value = false
  }
}

const materials = ref<MaterialSummary[]>([])
const summaries = ref<MaterialPreflightSummary[]>([])
const factsError = ref('')

// 关键陈述信号：按成员并行拉取（确定性 GET），总数是真实状态；失败记为未运行。
const signalCounts = ref<Record<string, number> | null>(null)

interface ConsistencySnapshot {
  result: { findings: ConsistencyFinding[] } | null
}
interface GrillSnapshot {
  materialId: string
  questions: unknown[]
  generated: boolean
}
interface DiffSnapshot {
  result: { resolved: unknown[]; unchanged: unknown[]; new: unknown[] } | null
}

async function loadFacts() {
  factsError.value = ''
  signalCounts.value = null
  try {
    const [materialsResponse, summariesResponse] = await Promise.all([
      fetch('/api/v1/materials'),
      fetch('/api/v1/preflight-summaries'),
    ])
    const materialsBody = await materialsResponse.json().catch(() => null)
    const summariesBody = await summariesResponse.json().catch(() => null)
    if (!materialsResponse.ok) throw new Error(materialsBody?.message ?? `HTTP ${materialsResponse.status}`)
    if (!summariesResponse.ok) throw new Error(summariesBody?.message ?? `HTTP ${summariesResponse.status}`)
    materials.value = Array.isArray(materialsBody) ? materialsBody : []
    summaries.value = Array.isArray(summariesBody) ? summariesBody : []
  } catch (cause) {
    factsError.value = cause instanceof Error ? cause.message : '未知错误'
  }

  const memberIds = (review.value?.materials ?? []).map((member) => member.material_id)
  if (memberIds.length === 0) return
  const counts: Record<string, number> = {}
  const settled = await Promise.all(
    memberIds.map(async (materialId) => {
      try {
        const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/statement-signals`)
        if (!response.ok) return false
        const body = await response.json().catch(() => null)
        counts[materialId] = Array.isArray(body) ? body.length : 0
        return true
      } catch {
        return false
      }
    }),
  )
  // 任一成员拉取失败都不展示部分总数（那不是真实状态），保持「尚未运行」。
  if (settled.every(Boolean)) signalCounts.value = counts
}

watch(() => review.value?.id, loadFacts, { immediate: true })

const reviewId = computed(() => review.value?.id ?? '')
const members = computed(() => review.value?.materials ?? [])
const basePath = computed(() => `/reviews/${reviewId.value}`)

function materialOf(materialId: string) {
  return materials.value.find((item) => item.id === materialId)
}

function identityOf(materialId: string, label: string) {
  return materialIdentity(label, materialOf(materialId)?.filename ?? '')
}

function summaryOf(materialId: string) {
  return summaries.value.find((item) => item.material_id === materialId)
}

// 依据事实只复述装配摘要的口径：已确认依据 k/n 项；缺口用「当前范围尚未发现引用」句。
function criteriaFact(materialId: string): string {
  const summary = summaryOf(materialId)
  if (!summary || !summary.bound || summary.criteria_total === undefined) return ''
  return `已确认依据 ${summary.criteria_with_citations ?? 0} / ${summary.criteria_total} 项`
}

function gapFact(materialId: string): number {
  const summary = summaryOf(materialId)
  if (!summary || !summary.bound) return 0
  return summary.criteria_without_citations ?? 0
}

const boundMembers = computed(() => members.value.filter((member) => summaryOf(member.material_id)?.bound))
const firstBoundId = computed(() => boundMembers.value[0]?.material_id ?? '')
const firstMemberId = computed(() => members.value[0]?.material_id ?? '')

// —— 角色当前状态：全部来自真实数据（装配摘要 / 信号 endpoint / 本会话已运行结果）——
const verifiedTotal = computed(() =>
  boundMembers.value.reduce((total, member) => total + (summaryOf(member.material_id)?.verified_citation_count ?? 0), 0),
)

const consistencySnapshot = computed(
  () => session.capabilitySnapshots[`${reviewId.value}:consistency`] as ConsistencySnapshot | undefined,
)
const grillSnapshot = computed(
  () => session.capabilitySnapshots[`${reviewId.value}:grill`] as GrillSnapshot | undefined,
)
const diffSnapshot = computed(
  () => session.capabilitySnapshots[`${reviewId.value}:diff`] as DiffSnapshot | undefined,
)
const signalTotal = computed(() =>
  signalCounts.value === null ? null : Object.values(signalCounts.value).reduce((total, count) => total + count, 0),
)

interface RoleState {
  key: string
  name: string
  type: '模型' | '程序' | '按需模型'
  icon: string
  state: string
  action?: { to: string; label: string }
}

const roles = computed<RoleState[]>(() => {
  const rows: RoleState[] = []
  // 依据审计员（模型）：状态来自只读装配摘要；事实加载失败时不得据空摘要报绑定结论。
  rows.push({
    key: 'evidence',
    name: '依据审计员',
    type: '模型',
    icon: 'i-lucide-scan-search',
    state: factsError.value
      ? '状态未知：材料事实加载失败'
      : boundMembers.value.length > 0
        ? `已确认关联 ${verifiedTotal.value} 条 · ${boundMembers.value.length}/${members.value.length} 份材料已绑定`
        : members.value.length > 0
          ? '尚未绑定审查标准'
          : '等待材料',
    action: factsError.value
      ? undefined
      : boundMembers.value.length > 0
        ? { to: `${basePath.value}/evidence`, label: '运行依据审计' }
        : firstMemberId.value
          ? { to: `/materials/${firstMemberId.value}`, label: '去绑定标准' }
          : undefined,
  })
  // 一致性检查（程序）：状态只认本会话真实跑过的结果。
  const consistency = consistencySnapshot.value?.result
  rows.push({
    key: 'consistency',
    name: '一致性检查',
    type: '程序',
    icon: 'i-lucide-git-compare',
    state: consistency ? `本次会话发现 ${consistency.findings.length} 处待核对项` : '尚未运行',
    action:
      members.value.length >= 2
        ? { to: `${basePath.value}/consistency`, label: consistency ? '查看结果' : '运行检查' }
        : undefined,
  })
  // 关键陈述检查（程序）：状态来自 statement-signals endpoint 的真实计数；事实加载失败时不报结论。
  rows.push({
    key: 'claims',
    name: '关键陈述检查',
    type: '程序',
    icon: 'i-lucide-list-checks',
    state: factsError.value
      ? '状态未知：材料事实加载失败'
      : signalTotal.value !== null
        ? `发现 ${signalTotal.value} 条陈述信号`
        : '尚未运行',
    action:
      factsError.value || !firstMemberId.value
        ? undefined
        : { to: `/materials/${firstMemberId.value}`, label: '查看信号' },
  })
  // 修复顾问（按需模型）：不维持自身状态，入口在依据报告的待核对项里。
  rows.push({
    key: 'repair',
    name: '修复顾问',
    type: '按需模型',
    icon: 'i-lucide-wrench',
    state: '有待核对项时按需调用，不主动运行',
    action: firstBoundId.value ? { to: `/materials/${firstBoundId.value}/report`, label: '查看待核对项' } : undefined,
  })
  // 质询官（按需模型）：状态只认本会话真实生成过的追问。
  const grill = grillSnapshot.value
  rows.push({
    key: 'grill',
    name: '质询官',
    type: '按需模型',
    icon: 'i-lucide-messages-square',
    state: grill?.generated ? `本次会话已生成 ${grill.questions.length} 条追问` : '尚未运行',
    action:
      members.value.length >= 1
        ? { to: `${basePath.value}/grill`, label: grill?.generated ? '查看评审问题' : '开始模拟评审' }
        : undefined,
  })
  return rows
})

function badgeProps(type: RoleState['type']): { color: 'primary' | 'neutral'; variant: 'subtle' | 'outline' } {
  if (type === '模型') return { color: 'primary', variant: 'subtle' }
  if (type === '按需模型') return { color: 'primary', variant: 'outline' }
  return { color: 'neutral', variant: 'subtle' }
}

// 下一步：按当前状态给出 2~4 个情境化动作，不做 dashboard。
const nextActions = computed(() => {
  const actions: { to: string; label: string; icon: string; primary?: boolean }[] = []
  if (members.value.length === 0) {
    actions.push({ to: `${basePath.value}/members`, label: '添加本次审查的材料', icon: 'i-lucide-plus', primary: true })
    return actions
  }
  if (members.value.length >= 2) {
    actions.push({ to: `${basePath.value}/consistency`, label: '运行一致性检查', icon: 'i-lucide-git-compare', primary: true })
  }
  actions.push({ to: `${basePath.value}/grill`, label: '开始模拟评审', icon: 'i-lucide-messages-square', primary: members.value.length < 2 })
  if (firstBoundId.value) {
    actions.push({ to: `/materials/${firstBoundId.value}/report`, label: '查看依据报告', icon: 'i-lucide-scan-search' })
  }
  actions.push({ to: `${basePath.value}/members`, label: '管理材料', icon: 'i-lucide-files' })
  return actions
})

// Action Inbox：从真实来源聚合「现在应该处理什么」。
// 语义按 issue 类型区分（待核对数值 / 值得核对的关键陈述 / 待确认依据 / 答辩准备），
// 不按 Agent 分栏；「暂时忽略」只承诺本次会话。没有状态来源的事项不造。
interface InboxEntry {
  item: ActionItemModel
  tone: 'amber' | 'emerald' | 'violet'
}
const inboxEntries = computed<InboxEntry[]>(() => {
  const entries: InboxEntry[] = []

  // 待核对数值：来自本会话真实跑过的一致性结果，逐条列出（最多 5 条）。
  const consistency = consistencySnapshot.value?.result
  if (consistency) {
    for (const finding of consistency.findings.slice(0, 5)) {
      entries.push({
        tone: 'amber',
        item: {
          key: `${reviewId.value}:consistency:${finding.kind}:${finding.measure}`,
          what: `待核对数值：${finding.measure}`,
          detail: finding.values.join(' / '),
          why: finding.explanation,
          where: review.value?.title ?? '',
          actions: [{ key: 'view', label: '查看一致性检查', to: `${basePath.value}/consistency`, primary: true }],
          meta: '由：一致性检查（程序）',
        },
      })
    }
  }

  // 待确认依据：来自装配摘要（确定性）。
  for (const member of members.value) {
    const summary = summaryOf(member.material_id)
    const missing = summary?.bound ? (summary.criteria_without_citations ?? 0) : 0
    if (missing > 0) {
      entries.push({
        tone: 'amber',
        item: {
          key: `${reviewId.value}:evidence:${member.material_id}`,
          what: `待确认依据：当前范围尚未发现引用 ${missing} 项`,
          why: '没有原文依据支撑的要求，评审时无法自证。',
          where: identityOf(member.material_id, member.label).primary,
          actions: [
            { key: 'run', label: '运行依据审计', to: `${basePath.value}/evidence`, primary: true },
            { key: 'open', label: '打开材料', to: `/materials/${member.material_id}` },
          ],
          meta: '由：依据审计员（模型）',
        },
      })
    }
  }

  // 值得核对的关键陈述：来自确定性 statement-signals。
  if (signalCounts.value !== null) {
    for (const member of members.value) {
      const count = signalCounts.value[member.material_id] ?? 0
      if (count > 0) {
        entries.push({
          tone: 'amber',
          item: {
            key: `${reviewId.value}:signals:${member.material_id}:${count}`,
            what: `值得核对的关键陈述 ${count} 条`,
            why: '数字、比例、比较级与绝对化表述最容易被评审追问，提前确认出处。',
            where: identityOf(member.material_id, member.label).primary,
            actions: [{ key: 'view', label: '查看信号', to: `/materials/${member.material_id}/report`, primary: true }],
            meta: '由：关键陈述检查（程序）',
          },
        })
      }
    }
  }

  // 答辩准备：来自本会话真实生成的模拟评审问题。
  const grill = grillSnapshot.value
  if (grill?.generated && grill.questions.length > 0) {
    entries.push({
      tone: 'violet',
      item: {
        key: `${reviewId.value}:grill:${grill.questions.length}`,
        what: `答辩准备：${grill.questions.length} 条可能的评审追问`,
        why: '这些问题由材料原文触发，提前准备回答或修改材料。',
        where: review.value?.title ?? '',
        actions: [{ key: 'view', label: '查看模拟评审', to: `${basePath.value}/grill`, primary: true }],
        meta: '由：质询官（按需模型）',
      },
    })
  }

  return entries
})

// 修改效果是状态变化而不是待办：不进 Action Inbox，只在有真实 diff 快照时给一行事实。
const diffSummary = computed(() => {
  const diff = diffSnapshot.value?.result
  if (!diff) return null
  return {
    resolved: diff.resolved.length,
    unchanged: diff.unchanged.length,
    added: diff.new.length,
    to: `${basePath.value}/diff`,
  }
})

const dismissed = computed(() => new Set(session.dismissedActionKeys))
const visibleEntries = computed(() => inboxEntries.value.filter((entry) => !dismissed.value.has(entry.item.key)))
const dismissedCount = computed(() => inboxEntries.value.length - visibleEntries.value.length)
</script>

<template>
  <div v-if="review" class="space-y-10">
    <!-- 审查团队：每行 = 职责 + 当前真实状态 + 真实动作；没有状态就写「尚未运行」。 -->
    <section aria-label="审查团队当前状态">
      <h2 class="text-xs font-medium uppercase tracking-wider text-slate-500">审查团队 · 当前状态</h2>
      <ol class="mt-3 divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800">
        <li v-for="role in roles" :key="role.key" class="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
          <span class="flex w-36 items-center gap-2">
            <UIcon :name="role.icon" class="size-4 shrink-0 text-slate-400" />
            <span class="truncate text-sm font-medium text-slate-200">{{ role.name }}</span>
          </span>
          <UBadge v-bind="badgeProps(role.type)" size="sm" class="shrink-0">{{ role.type }}</UBadge>
          <span class="min-w-0 flex-1 truncate text-sm text-slate-400">{{ role.state }}</span>
          <UButton
            v-if="role.action"
            :to="role.action.to"
            color="neutral"
            variant="ghost"
            size="xs"
            icon="i-lucide-arrow-right"
            trailing
            class="shrink-0"
          >
            {{ role.action.label }}
          </UButton>
        </li>
      </ol>
    </section>

    <!-- 审查对象：label 是一等身份；label == filename 时只显示一次。 -->
    <section aria-label="审查对象">
      <div class="flex items-baseline justify-between gap-3">
        <h2 class="text-xs font-medium uppercase tracking-wider text-slate-500">审查对象</h2>
        <span class="text-[11px] text-slate-600">{{ members.length }} 份材料 · {{ boundMembers.length }} 份已绑定标准</span>
      </div>

      <EmptyState
        v-if="members.length === 0"
        class="mt-3 rounded-xl bg-slate-950/40"
        title="这次审查还没有材料"
        hint="把材料加入审查后，它们在这里以你起的名字出现（原文件名保留作出处）。"
      >
        <UButton :to="`${basePath}/members`" icon="i-lucide-plus">添加材料</UButton>
      </EmptyState>

      <div v-else class="mt-3 grid gap-3 sm:grid-cols-2">
        <article v-for="member in members" :key="member.material_id" class="rounded-xl bg-slate-950/40 p-4">
          <div class="flex items-start justify-between gap-3">
            <p class="truncate text-base font-medium text-slate-100">{{ identityOf(member.material_id, member.label).primary }}</p>
            <UBadge
              :color="summaryOf(member.material_id)?.bound ? 'success' : 'warning'"
              variant="subtle"
              size="sm"
              class="shrink-0"
            >
              {{ summaryOf(member.material_id)?.bound ? `已绑定 · v${summaryOf(member.material_id)?.rubric_revision}` : '未绑定' }}
            </UBadge>
          </div>
          <p v-if="identityOf(member.material_id, member.label).secondary" class="mt-1 truncate font-mono text-xs text-slate-500">
            {{ identityOf(member.material_id, member.label).secondary }}
          </p>
          <p v-if="criteriaFact(member.material_id)" class="mt-2 text-xs text-slate-400">{{ criteriaFact(member.material_id) }}</p>
          <p v-if="gapFact(member.material_id)" class="mt-1 text-xs text-amber-300/90">
            当前范围尚未发现引用 {{ gapFact(member.material_id) }} 项
          </p>
        </article>
      </div>
      <p v-if="factsError" class="mt-2 text-xs text-red-400" role="alert">材料事实加载失败：{{ factsError }}</p>
    </section>

    <!-- 下一步：Action Inbox——先回答「现在应该处理什么」，再给情境化动作；不做 dashboard。 -->
    <section aria-label="下一步" class="rounded-xl border border-slate-800 p-5">
      <h2 class="text-xs font-medium uppercase tracking-wider text-slate-500">现在应该处理什么</h2>
      <div v-if="visibleEntries.length > 0" class="mt-3 space-y-3">
        <ActionItem
          v-for="entry in visibleEntries"
          :key="entry.item.key"
          :item="entry.item"
          :tone="entry.tone"
          dismissible
          @dismiss="session.dismissAction"
        />
      </div>
      <p v-else class="mt-3 text-xs text-slate-600">当前会话还没有需要处理的事项；运行一致性或依据审计后会出现在这里。</p>
      <p v-if="dismissedCount > 0" class="mt-2 text-[11px] text-slate-600">
        已暂时忽略 {{ dismissedCount }} 项（仅本次会话有效，刷新后恢复显示）。
      </p>
      <!-- 修改效果是会话内的状态变化，不是待办：只复述事实，不伪装成 action。 -->
      <p v-if="diffSummary" class="mt-2 text-[11px] text-slate-500">
        修改效果 · 本次会话：本次未再检出 {{ diffSummary.resolved }} · 仍存在 {{ diffSummary.unchanged }} · 新增 {{ diffSummary.added }}
        <RouterLink :to="diffSummary.to" class="text-slate-400 underline decoration-slate-700 underline-offset-2 hover:text-slate-200">
          查看修改效果
        </RouterLink>
      </p>
      <div class="mt-3 flex flex-wrap gap-2">
        <UButton
          v-for="action in nextActions"
          :key="action.to + action.label"
          :to="action.to"
          :icon="action.icon"
          :color="action.primary ? 'primary' : 'neutral'"
          :variant="action.primary ? 'solid' : 'subtle'"
        >
          {{ action.label }}
        </UButton>
      </div>
      <p class="mt-3 text-xs leading-relaxed text-slate-600">
        一致性、修改效果与模拟评审都在这次审查的上下文中进行——材料以你起的名字出现，不再需要从整个材料库重新猜测。
      </p>
    </section>

    <!-- 删除本次审查：两步确认；必须说清楚材料和材料的审查标准绑定都不受影响。 -->
    <section aria-label="删除本次审查" class="rounded-xl border border-slate-800/60 p-5">
      <template v-if="!confirmingDelete">
        <UButton color="neutral" variant="ghost" size="sm" icon="i-lucide-trash-2" @click="confirmingDelete = true">
          删除本次审查
        </UButton>
      </template>
      <template v-else>
        <p class="text-sm text-slate-200">确定删除「{{ review?.title }}」吗？</p>
        <p class="mt-2 text-xs leading-relaxed text-slate-400">
          删除只会移除这次审查的上下文与材料清单。<span class="text-slate-300">不会删除任何材料，也不会修改材料当前使用的审查标准。</span>
        </p>
        <p v-if="deleteError" class="mt-2 text-sm text-red-400" role="alert">删除失败：{{ deleteError }}</p>
        <div class="mt-4 flex flex-wrap gap-3">
          <UButton color="error" size="sm" :loading="deleting" @click="deleteReview">
            {{ deleting ? '正在删除…' : '确认删除' }}
          </UButton>
          <UButton color="neutral" variant="subtle" size="sm" :disabled="deleting" @click="confirmingDelete = false">
            取消
          </UButton>
        </div>
      </template>
    </section>
  </div>
</template>
