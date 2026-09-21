<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { AgentProposal, Block, ConsistencyFinding, DetectedStatement, Locator, MaterialPreflightCitation, MaterialPreflightReport } from '../types/contracts'
import EvidenceDrawer from '../components/EvidenceDrawer.vue'
import RepairSuggestionPanel from '../components/RepairSuggestionPanel.vue'
import PageHeader from '../components/review/PageHeader.vue'
import { locatorLabel } from '../utils/locatorLabel'
import { latestCompletedProposal, latestProposal, passedCount, pendingPassedCount } from '../utils/preflightFacts'
import { failureFromResponse, toUserFacingError } from '../utils/userFacingError'

// 材料级预审报告：装配结果（需要绑定）与材料级信号（不需要绑定）各自装、各自画。
const route = useRoute()
const materialId = String(route.params.materialId)

// —— 报告主体：受绑定与装配状态影响 ——
const report = ref<MaterialPreflightReport | null>(null)
const loading = ref(true)
const notFound = ref(false)
const unbound = ref(false)
const error = ref('')

// I8 待核对问题：同材料内的数值对照结论由后端纯函数给出，前端只渲染。
const findings = ref<ConsistencyFinding[]>([])
const findingsUnavailable = ref(false)

// 修复建议：每条待核对问题一个入口；点开才由面板调用 LLM，材料原文不动。
const repairFinding = ref<ConsistencyFinding | null>(null)

// 修复建议运行状态按 finding 记录：只有「成功结果」才计数，运行/失败/成功分开。
// 切换 finding 后迟到的旧结果不会贴到新问题上（面板侧有 token 守卫，这里按 key 隔离）。
type RepairRunState = 'running' | 'succeeded' | 'failed'
const repairStates = ref<Record<string, RepairRunState>>({})

function findingKey(finding: ConsistencyFinding): string {
  const first = finding.citations[0]
  return `${finding.kind}:${finding.measure}:${first ? `${first.block_id}:${first.start}` : 'no-citation'}`
}

function onRepairStatus(state: RepairRunState) {
  const finding = repairFinding.value
  if (!finding) return
  repairStates.value = { ...repairStates.value, [findingKey(finding)]: state }
}

const repairRunningCount = computed(() => Object.values(repairStates.value).filter((state) => state === 'running').length)
const repairSucceededCount = computed(
  () => Object.values(repairStates.value).filter((state) => state === 'succeeded').length,
)
const repairFailedCount = computed(() => Object.values(repairStates.value).filter((state) => state === 'failed').length)

// I7 材料级信号：同样与绑定无关，一到手就画。
const signals = ref<DetectedStatement[]>([])
const signalsUnavailable = ref(false)

// —— 预检记录：报告页只读，不接 accept ——
const proposals = ref<AgentProposal[]>([])
const proposalsUnavailable = ref(false)

// —— 核验评分要求：顶栏按钮是唯一 POST 入口；失败只落在对应行 ——
const verifying = ref(false)
const verifyingIds = ref<string[]>([])
const rowError = ref<Record<string, string>>({})
const VERIFY_CONCURRENCY = 3

// 绑定前报告里没有 blocks：点开原文时才补取材料本体，保证 Drawer 有上下文。
const materialBlocks = ref<Block[]>([])
const blocksUnavailable = ref(false)

const drawerOpen = ref(false)
const highlight = ref<{ start: number; end: number } | null>(null)
const drawerBlockId = ref('')

const allBlocks = computed(() => report.value?.blocks ?? materialBlocks.value)

// 已确认依据 k / n 项：有引用的审查要求数 / 审查要求总数。与首页 summaries 同一口径，不是引用条数。
const confirmedCriterionCount = computed(() =>
  report.value ? report.value.criteria.filter((row) => row.verified_citation_count > 0).length : 0,
)

// 预检概览（C1）：材料级计数不依赖报告；已确认依据只在报告到手后给 k / n，否则给 —。
const overviewCounts = computed(() => {
  const base = `待核对项 ${findings.value.length} · 关键陈述 ${signals.value.length}`
  if (!report.value) return `${base} · 已确认依据 —`
  return `${base} · 已确认依据 ${confirmedCriterionCount.value} / ${report.value.criteria.length} 项`
})

// 引用/信号行只说位置：优先用条目自带的 Locator（kind 决定行 / 段 / 表格单元格）。
// 旧快照无 locator 时才退回 line_number，且为 null 时不显示（不发明第二套编号）。
function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function rowLocation(item: { locator?: Locator; line_number?: number | null }): string {
  if (item.locator) return locatorLabel(item.locator)
  if (typeof item.line_number === 'number') return locatorLabel({ kind: 'line', index: item.line_number })
  return ''
}

async function loadReport() {
  loading.value = true
  error.value = ''
  notFound.value = false
  unbound.value = false
  report.value = null
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/preflight-report`)
    const body = await response.json().catch(() => null)
    if (response.status === 404) {
      notFound.value = true
      return
    }
    if (response.status === 409) {
      unbound.value = true
      return
    }
    if (!response.ok) {
      throw failureFromResponse(response.status, body)
    }
    report.value = body as MaterialPreflightReport
  } catch (cause) {
    error.value = toUserFacingError(cause, '无法读取审查结果，请重试').message
  } finally {
    loading.value = false
  }
}

// 材料级两个 GET 自己装：报告还在装配、甚至未绑定，它们也能先画。
async function loadFindings() {
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/consistency-findings`)
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      findingsUnavailable.value = true
      return
    }
    findingsUnavailable.value = false
    findings.value = Array.isArray(body) ? (body as ConsistencyFinding[]) : []
  } catch {
    findingsUnavailable.value = true
  }
}

async function loadSignals() {
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/statement-signals`)
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      signalsUnavailable.value = true
      return
    }
    signalsUnavailable.value = false
    signals.value = Array.isArray(body) ? (body as DetectedStatement[]) : []
  } catch {
    signalsUnavailable.value = true
  }
}

async function loadProposals() {
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/agent-proposals`)
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      proposalsUnavailable.value = true
      return
    }
    proposalsUnavailable.value = false
    proposals.value = Array.isArray(body) ? (body as AgentProposal[]) : []
  } catch {
    proposalsUnavailable.value = true
  }
}

async function loadMaterialBlocks() {
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}`)
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      blocksUnavailable.value = true
      return
    }
    materialBlocks.value = Array.isArray(body?.blocks) ? (body.blocks as Block[]) : []
  } catch {
    blocksUnavailable.value = true
  }
}

async function ensureBlocks() {
  if (allBlocks.value.length > 0 || blocksUnavailable.value) return
  await loadMaterialBlocks()
}

const drawerBlock = computed(() => blockAt(0))
const previousBlock = computed(() => blockAt(-1))
const nextBlock = computed(() => blockAt(1))

function blockAt(offset: number): Block | null {
  const blocks = allBlocks.value
  const index = blocks.findIndex((item) => item.id === drawerBlockId.value)
  if (index < 0) return null
  return blocks[index + offset] ?? null
}

async function openHighlight(target: { block_id: string; start: number; end: number }) {
  highlight.value = { start: target.start, end: target.end }
  drawerBlockId.value = target.block_id
  drawerOpen.value = true
  await ensureBlocks()
}

function openCitation(citation: MaterialPreflightCitation) {
  openHighlight(citation)
}

function openRepair(finding: ConsistencyFinding) {
  repairFinding.value = finding
}

function signalLabel(signal: DetectedStatement['signal']) {
  return { numeric: '数字', percentage: '比例', comparative: '比较', absolute: '绝对化' }[signal]
}

// 只陈述检测到的事实：同一度量词出现不同数值，或需人工判断；不下裁决、不给结论。
function findingLabel(kind: ConsistencyFinding['kind']) {
  return { numeric_inconsistency: '数值不一致', needs_review: '待人工判断' }[kind]
}

function completedFor(criterionId: string) {
  return latestCompletedProposal(proposals.value, criterionId)
}

function pendingFor(criterionId: string) {
  return pendingPassedCount(completedFor(criterionId))
}

function emptyPreflight(criterionId: string) {
  const completed = completedFor(criterionId)
  return completed !== null && passedCount(completed) === 0
}

function neverPreflighted(criterionId: string) {
  return completedFor(criterionId) === null
}

function failedWithoutCompleted(criterionId: string) {
  const latest = latestProposal(proposals.value, criterionId)
  return latest?.status === 'failed' && completedFor(criterionId) === null
}

async function verifyCriterion(criterionId: string) {
  verifyingIds.value = [...verifyingIds.value, criterionId]
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/agent-proposals`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ criterion_id: criterionId }),
    })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw failureFromResponse(response.status, body)
    }
    const next = { ...rowError.value }
    delete next[criterionId]
    rowError.value = next
  } catch (cause) {
    // 失败只写在该行（如 material_too_large），不升级成整页红字主句，也不吞掉。
    rowError.value = { ...rowError.value, [criterionId]: toUserFacingError(cause, '本条依据审计失败，请稍后重试').message }
  } finally {
    verifyingIds.value = verifyingIds.value.filter((item) => item !== criterionId)
  }
}

/** 顶栏唯一 POST 入口：逐条核验评分要求；有界并发，失败互不影响。 */
async function verifyCriteria() {
  if (verifying.value || !report.value) return
  const queue = report.value.criteria.map((row) => row.criterion_id)
  if (queue.length === 0) return
  verifying.value = true
  try {
    const workers = Array.from({ length: Math.min(VERIFY_CONCURRENCY, queue.length) }, async () => {
      while (queue.length > 0) {
        const criterionId = queue.shift()
        if (!criterionId) return
        await verifyCriterion(criterionId)
      }
    })
    await Promise.all(workers)
  } finally {
    // 后端把失败也落库（status=failed）；刷新提案让每行状态回到真实来源。
    await loadProposals()
    verifying.value = false
  }
}

// 首次进入只读：所有加载都是 GET，核验只由人点。
loadReport()
loadFindings()
loadSignals()
loadProposals()
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-10">
    <PageHeader :title="report ? report.filename : '审查结果'" subtitle="按每条审查要求在原文里找依据">
      <UButton v-if="report" icon="i-lucide-sparkles" :loading="verifying" @click="verifyCriteria">
        {{ verifying ? '依据审计中…' : '运行依据审计' }}
      </UButton>
      <UButton :to="`/materials/${materialId}`" color="neutral" variant="ghost" size="xs" icon="i-lucide-file-text">返回材料</UButton>
      <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
    </PageHeader>
    <p class="mt-2 text-sm text-slate-300">审查概览 · {{ overviewCounts }}</p>
    <p class="mt-2 text-sm text-slate-400">
      <span v-if="report">{{ report.rubric_title }} · 标准版本 {{ report.rubric_revision }} · {{ report.block_count }} 段原文</span>
      <span v-else>绑定审查标准后才能逐条运行依据审计。</span>
    </p>

    <!-- 材料级区块：不依赖绑定，各自装、各自画（待核对问题在关键陈述之上）。 -->
    <div v-if="!notFound" class="mt-6 space-y-4">
      <!-- 审查团队：三张主卡（一模型两程序）。修复/质询按需，不排成并列「五个 Agent」。 -->
      <section class="rounded-lg bg-slate-950/40 p-4">
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h2 class="text-sm font-medium text-slate-200">审查团队</h2>
          <span class="text-xs text-slate-500">一致性与关键陈述由程序扫描。依据审计、修复建议、模拟评审才会调用模型。</span>
        </div>
        <ul class="mt-3 grid gap-2 sm:grid-cols-3">
          <li>
            <button type="button" class="h-full w-full rounded-md bg-slate-900/40 p-3 text-left" @click="scrollToSection('review-criteria')">
              <p class="text-xs text-slate-200">依据审计员</p>
              <p class="mt-0.5 text-[10px] text-violet-300">模型</p>
              <p class="mt-1 text-xs text-slate-400">按审查要求寻找可直接引用的原文</p>
              <p class="mt-2 text-sm text-slate-200">
                <span v-if="verifying">依据审计中…</span>
                <span v-else-if="report">已确认依据 {{ confirmedCriterionCount }} / {{ report.criteria.length }} 项</span>
                <span v-else-if="unbound">未绑定审查标准</span>
                <span v-else-if="loading">正在读取审查要求</span>
                <span v-else>尚未读取审查要求</span>
              </p>
            </button>
          </li>
          <li>
            <button type="button" class="h-full w-full rounded-md bg-slate-900/40 p-3 text-left" @click="scrollToSection('pending-findings')">
              <p class="text-xs text-slate-200">一致性检查</p>
              <p class="mt-0.5 text-[10px] text-slate-500">程序</p>
              <p class="mt-1 text-xs text-slate-400">检查同一指标在材料中的不同说法</p>
              <p class="mt-2 text-sm text-slate-200">
                <span v-if="findingsUnavailable">扫描不可用</span>
                <span v-else>待核对项 {{ findings.length }} 条</span>
              </p>
            </button>
          </li>
          <li>
            <button type="button" class="h-full w-full rounded-md bg-slate-900/40 p-3 text-left" @click="scrollToSection('key-statements')">
              <p class="text-xs text-slate-200">关键陈述检查</p>
              <p class="mt-0.5 text-[10px] text-slate-500">程序</p>
              <p class="mt-1 text-xs text-slate-400">标出值得进一步核查的数字和强表述</p>
              <p class="mt-2 text-sm text-slate-200">
                <span v-if="signalsUnavailable">扫描不可用</span>
                <span v-else>标记 {{ signals.length }} 条</span>
              </p>
            </button>
          </li>
        </ul>
        <p class="mt-3 text-xs text-slate-500">
          <button type="button" class="text-slate-300 hover:underline" @click="scrollToSection('pending-findings')">修复顾问</button>
          <span v-if="repairRunningCount > 0"> · 正在生成 {{ repairRunningCount }} 条建议…</span>
          <span v-else-if="repairSucceededCount > 0"> · 已生成 {{ repairSucceededCount }} 条建议</span>
          <span v-else-if="repairFailedCount > 0"> · 最近一次生成失败，可在面板重试</span>
          <span v-else> · 点待核对项后才运行</span>
          <span class="mx-2 text-slate-700">·</span>
          <span class="text-slate-300">质询官</span>
          · 需要时在模拟评审中生成追问
        </p>
      </section>

      <!-- I8 待核对项（首屏主区）：同一材料内同一指标的数值对照；每条都能点回原文 Drawer。 -->
      <section id="pending-findings" class="rounded-lg border border-amber-900/50 bg-amber-950/10 p-5">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-lg font-semibold text-slate-100">待核对项</h2>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-xs text-slate-500">{{ findings.length }} 条 · 同一材料内数值对照</span>
          </div>
        </div>
        <p v-if="findingsUnavailable" class="mt-2 text-xs text-amber-300">待核对项不可用</p>
        <!-- 空态只有一块：两句话同段（原先两个连续 v-else-if 让第二句永不渲染）。 -->
        <p v-else-if="findings.length === 0" class="mt-2 text-xs text-slate-400">当前范围尚未发现待核对项（同一指标在材料中出现了不同数值）。跨材料的数值对照在「一致性检查」。</p>
        <ul v-else class="mt-3 space-y-3">
          <li
            v-for="finding in findings"
            :key="findingKey(finding)"
            class="rounded-md border border-slate-800 p-2"
          >
            <div class="flex flex-wrap items-center gap-2">
              <UBadge
                :color="finding.kind === 'numeric_inconsistency' ? 'warning' : 'neutral'"
                variant="subtle"
                size="sm"
              >
                {{ findingLabel(finding.kind) }}
              </UBadge>
              <span v-if="finding.measure" class="text-xs text-slate-300">度量词：{{ finding.measure }}</span>
              <span class="font-mono text-xs text-slate-300">{{ finding.values.join(' / ') }}</span>
            </div>
            <p class="mt-1 text-xs text-slate-500">{{ finding.explanation }}</p>
            <ul class="mt-2 space-y-1">
              <li v-for="citation in finding.citations" :key="`${citation.block_id}:${citation.start}`">
                <button
                  type="button"
                  class="w-full rounded-md bg-slate-900/60 p-2 text-left transition hover:bg-slate-800/60"
                  @click="openHighlight(citation)"
                >
                  <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}”<template v-if="rowLocation(citation)"> · {{ rowLocation(citation) }}</template></span>
                </button>
              </li>
            </ul>
            <div class="mt-2 flex justify-end">
              <UButton size="xs" color="neutral" variant="subtle" icon="i-lucide-wand-sparkles" @click="openRepair(finding)">
                生成修复建议
              </UButton>
            </div>

            <!-- 修复建议：LLM 只给改稿方向；引用仍点回同一 Drawer，材料原文不动。面板只挂在被选中的这条问题卡片内。 -->
            <RepairSuggestionPanel
              v-if="repairFinding === finding"
              :material-id="materialId"
              :material-label="report?.filename ?? ''"
              :finding="repairFinding"
              :on-status="onRepairStatus"
              @open-citation="openHighlight"
              @close="repairFinding = null"
            />
          </li>
        </ul>
      </section>

    </div>

    <!-- 报告主体：需要绑定；装配中/未绑定/找不到/失败各自给出路，不挡上面的材料级区块。 -->
    <p v-if="loading" class="mt-4 text-xs text-slate-500">正在读取审查结果…</p>

    <UCard v-else-if="notFound" class="mt-4">
      <h2 class="text-lg font-medium">找不到这份材料</h2>
      <p class="mt-2 text-sm text-slate-400">可能已被删除。</p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton :to="`/materials/${materialId}`" color="neutral" variant="subtle" icon="i-lucide-file-text">
          返回材料
        </UButton>
        <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">全部材料</UButton>
      </div>
    </UCard>

    <UCard v-else-if="unbound" class="mt-4">
      <h2 class="text-lg font-medium">尚未绑定审查标准</h2>
      <p class="mt-2 text-sm text-slate-400">
        上面的材料级检查结果无需绑定审查标准也可查看。绑定审查标准后才能逐条运行依据审计。
      </p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton :to="`/materials/${materialId}`" icon="i-lucide-link">去绑定审查标准</UButton>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
      </div>
    </UCard>

    <UCard v-else-if="error" class="mt-4">
      <h2 class="text-lg font-medium">无法读取审查结果</h2>
      <p class="mt-2 text-sm text-slate-400">请求失败：{{ error }}</p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton icon="i-lucide-refresh-cw" @click="loadReport">重试</UButton>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
      </div>
    </UCard>

    <div v-else-if="report" class="mt-4 space-y-4">
      <!-- Phase 3：审查要求进度 —— 每条要求一行；行内显示本条核验状态，失败只落在该行。 -->
      <h2 id="review-criteria" class="text-sm font-medium text-slate-200">审查要求进度</h2>
      <p v-if="proposalsUnavailable" class="text-xs text-amber-300">依据审计记录不可用</p>

      <div v-for="row in report.criteria" :key="row.criterion_id" class="rounded-lg border border-slate-800 p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h2 class="text-sm font-medium text-slate-200">{{ row.title }}</h2>
            <p class="mt-1 text-xs text-slate-500">{{ row.requirement }}</p>
          </div>
          <div class="flex flex-wrap justify-end gap-2">
            <UBadge v-if="neverPreflighted(row.criterion_id)" color="neutral" variant="subtle">尚未运行依据审计</UBadge>
            <UBadge v-if="emptyPreflight(row.criterion_id)" color="neutral" variant="subtle">
              {{ row.verified_citation_count > 0 ? '本次未提出新候选' : '依据审计完成 · 当前材料尚未发现候选引用' }}
            </UBadge>
            <UBadge v-if="pendingFor(row.criterion_id) > 0" color="warning" variant="subtle">
              已发现 {{ pendingFor(row.criterion_id) }} 条候选，待审核
            </UBadge>
            <UBadge v-if="row.verified_citation_count > 0" color="success" variant="subtle">
              已确认关联 {{ row.verified_citation_count }} 条
            </UBadge>
            <!-- 行内核验态：只在这一行的徽章旁显示，不做整卡 spinner，也不门控上方区块。 -->
            <span v-if="verifyingIds.includes(row.criterion_id)" class="text-xs text-slate-500">本条依据审计中…</span>
          </div>
        </div>
        <p v-if="failedWithoutCompleted(row.criterion_id)" class="mt-2 text-xs text-red-400">
          依据审计失败：{{ latestProposal(proposals, row.criterion_id)?.error }}
        </p>
        <p v-if="rowError[row.criterion_id]" class="mt-2 text-xs text-red-400" role="alert">
          {{ rowError[row.criterion_id] }}
        </p>
        <p v-if="emptyPreflight(row.criterion_id)" class="mt-2 text-xs text-slate-500">
          范围：{{ report.filename }} · {{ report.block_count }} 段原文
        </p>
        <p v-if="pendingFor(row.criterion_id) > 0" class="mt-2 text-xs text-slate-500">
          <RouterLink :to="`/materials/${materialId}`" class="text-violet-300 hover:underline">去确认这些依据</RouterLink>
        </p>

        <details v-if="row.citations.length > 0">
          <summary class="mt-3 text-xs text-slate-400">查看已确认原文</summary>
          <ul class="mt-3 space-y-2">
            <li v-for="citation in row.citations" :key="citation.link_id">
              <button
                type="button"
                class="w-full rounded-md bg-slate-900/60 p-2 text-left transition hover:bg-slate-800/60"
                @click="openCitation(citation)"
              >
                <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}”<template v-if="rowLocation(citation)"> · {{ rowLocation(citation) }}</template></span>
                <span class="ml-2 text-xs text-emerald-400">原文已校验</span>
                <span class="ml-2 inline-flex">
                  <UBadge :color="citation.proposed_by === 'agent' ? 'info' : 'neutral'" variant="subtle" size="sm">
                    {{ citation.proposed_by === 'human' ? '人工' : '程序' }}
                  </UBadge>
                </span>
                <span class="mt-1 block text-xs text-slate-500">用途：{{ citation.rationale }}</span>
              </button>
            </li>
          </ul>
        </details>
        <p v-else-if="emptyPreflight(row.criterion_id) && row.missing" class="mt-3 text-xs text-slate-500">
          {{ row.missing.explanation }}
        </p>
      </div>
    </div>

    <!-- 关键陈述：确定性扫描结果，只标出值得核对的句子，不判真假；排在评分要求矩阵之后。 -->
    <section id="key-statements" v-if="(signalsUnavailable || signals.length > 0) && !notFound" class="mt-4 rounded-lg border border-slate-800 p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-sm font-medium text-slate-200">关键陈述</h2>
        <span class="text-xs text-slate-500">{{ signals.length }} 条 · 数字 / 比例 / 比较 / 绝对化</span>
      </div>
      <p v-if="signalsUnavailable" class="mt-2 text-xs text-amber-300">关键陈述不可用</p>
      <ul v-else class="mt-3 space-y-2">
        <li v-for="signal in signals" :key="`${signal.block_id}:${signal.start}`">
          <button
            type="button"
            class="w-full rounded-md bg-slate-900/60 p-2 text-left transition hover:bg-slate-800/60"
            @click="openHighlight(signal)"
          >
            <UBadge color="neutral" variant="subtle" size="sm">{{ signalLabel(signal.signal) }}</UBadge>
            <span class="ml-2 font-mono text-xs text-slate-300">“{{ signal.quote }}”<template v-if="rowLocation(signal)"> · {{ rowLocation(signal) }}</template></span>
          </button>
        </li>
      </ul>
    </section>

    <EvidenceDrawer
      :open="drawerOpen"
      :highlight="highlight"
      :block="drawerBlock"
      :previous-block="previousBlock"
      :next-block="nextBlock"
      :filename="report?.filename ?? ''"
      @update:open="drawerOpen = $event"
    />
  </main>
</template>
