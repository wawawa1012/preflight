<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { AgentProposal, Block, ConsistencyFinding, DetectedStatement, MaterialPreflightCitation, MaterialPreflightReport } from '../types/contracts'
import EvidenceDrawer from '../components/EvidenceDrawer.vue'
import RepairSuggestionPanel from '../components/RepairSuggestionPanel.vue'
import { locatorLabel } from '../utils/locatorLabel'
import { latestCompletedProposal, latestProposal, passedCount, pendingPassedCount } from '../utils/preflightFacts'

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
const highlight = ref<{ line_number: number; start: number; end: number } | null>(null)
const drawerBlockId = ref('')

const allBlocks = computed(() => report.value?.blocks ?? materialBlocks.value)

// 预检概览（C1）：材料级计数不依赖报告；已确认依据只在报告到手后给 k / n，否则给 —。
const overviewCounts = computed(() => {
  const base = `待核对 ${findings.value.length} · 关键陈述 ${signals.value.length}`
  if (!report.value) return `${base} · 已确认依据 —`
  const confirmed = report.value.criteria.reduce((sum, row) => sum + row.verified_citation_count, 0)
  return `${base} · 已确认依据 ${confirmed} / ${report.value.criteria.length} 项`
})

// 引用/信号行只说位置：kind 由该 Block 的 Locator 决定（md 显示行号，slide/page/paragraph 各自成句）。
// Block 未到手（未绑定、blocks 未取）时退回 line_number —— 它就是 locator.index，本季只有 md 入库，不发明第二套编号。
function rowLocation(blockId: string, lineNumber: number): string {
  const locator = allBlocks.value.find((item) => item.id === blockId)?.locator
  return locator ? locatorLabel(locator) : locatorLabel({ kind: 'line', index: lineNumber })
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
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    report.value = body as MaterialPreflightReport
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '未知错误'
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

async function openHighlight(target: { block_id: string; line_number: number; start: number; end: number }) {
  highlight.value = { line_number: target.line_number, start: target.start, end: target.end }
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

function verifyFailureText(code: string, message: string) {
  if (code === 'material_too_large') return '材料超出单次核验上限，本行未核验'
  return message || code
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
      const code = body && body.code ? body.code : `HTTP ${response.status}`
      throw new Error(verifyFailureText(code, body && body.message ? body.message : code))
    }
    const next = { ...rowError.value }
    delete next[criterionId]
    rowError.value = next
  } catch (cause) {
    // 失败只写在该行（如 material_too_large），不升级成整页红字主句，也不吞掉。
    rowError.value = { ...rowError.value, [criterionId]: cause instanceof Error ? cause.message : '未知错误' }
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
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="text-sm font-medium text-violet-400">PREFLIGHT REPORT</p>
        <h1 class="mt-2 text-3xl font-semibold tracking-tight">{{ report ? report.filename : '预审报告' }}</h1>
        <p class="mt-1 text-xs text-slate-500">按每条审查要求在原文里找依据</p>
        <p class="mt-2 text-sm text-slate-300">预检概览 · {{ overviewCounts }}</p>
        <p class="mt-2 text-sm text-slate-400">
          <span v-if="report">{{ report.rubric_title }} · rev{{ report.rubric_revision }} · {{ report.block_count }} 个 Block</span>
          <span v-else>材料级信号不需要绑定；绑定后才有可逐条核验的评分要求</span>
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <!-- 顶栏唯一核验入口：旧的「核验评分要求」入口 -->
        <UButton v-if="report" icon="i-lucide-sparkles" :loading="verifying" @click="verifyCriteria">
          {{ verifying ? '核验中…' : '开始核验' }}
        </UButton>
        <UButton :to="`/materials/${materialId}`" color="neutral" variant="ghost" size="xs" icon="i-lucide-file-text">返回材料</UButton>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
      </div>
    </div>

    <!-- 材料级区块：不依赖绑定，各自装、各自画（待核对问题在关键陈述之上）。 -->
    <div v-if="!notFound" class="mt-6 space-y-4">
      <!-- I8 待核对问题（首屏主区：待处理问题）：同一材料内同一度量词的数值对照；每条都能点回原文 Drawer。 -->
      <section class="rounded-lg border border-amber-900/50 bg-amber-950/10 p-5">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-lg font-semibold text-slate-100">待处理问题</h2>
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-xs text-slate-500">{{ findings.length }} 条 · 同一材料内数值对照</span>
            <!-- 与另一份材料对照：常显（未绑定/装配中也可用），不带 query，不触任何写接口。 -->
            <UButton to="/compare" color="neutral" variant="subtle" size="xs" icon="i-lucide-git-compare">与另一份材料对照</UButton>
          </div>
        </div>
        <p v-if="findingsUnavailable" class="mt-2 text-xs text-amber-300">待核对问题不可用</p>
        <p v-else-if="findings.length === 0" class="mt-2 text-xs text-slate-400">当前范围尚未发现待核对问题（同一材料内同一度量词的不同数字）</p>
        <ul v-else class="mt-3 space-y-3">
          <li
            v-for="finding in findings"
            :key="`${finding.kind}:${finding.measure}:${finding.citations[0].block_id}:${finding.citations[0].start}`"
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
                  <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}” · {{ rowLocation(citation.block_id, citation.line_number) }}</span>
                </button>
              </li>
            </ul>
            <div class="mt-2 flex justify-end">
              <UButton size="xs" color="neutral" variant="subtle" icon="i-lucide-wand-sparkles" @click="openRepair(finding)">
                生成修复建议
              </UButton>
            </div>
          </li>
        </ul>
      </section>

      <!-- 修复建议：LLM 只给改稿方向；引用仍点回同一 Drawer，材料原文不动。 -->
      <RepairSuggestionPanel
        v-if="repairFinding"
        :material-id="materialId"
        :finding="repairFinding"
        @open-citation="openHighlight"
        @close="repairFinding = null"
      />

    </div>

    <!-- 报告主体：需要绑定；装配中/未绑定/找不到/失败各自给出路，不挡上面的材料级区块。 -->
    <p v-if="loading" class="mt-4 text-xs text-slate-500">正在读取审查要求…</p>

    <UCard v-else-if="notFound" class="mt-4">
      <h2 class="text-lg font-medium">找不到该材料</h2>
      <p class="mt-2 text-sm text-slate-400">该 ID 不存在，或本地数据库中没有这条记录。</p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton :to="`/materials/${materialId}`" color="neutral" variant="subtle" icon="i-lucide-file-text">
          返回材料
        </UButton>
        <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">全部材料</UButton>
      </div>
    </UCard>

    <UCard v-else-if="unbound" class="mt-4">
      <h2 class="text-lg font-medium">尚未绑定评分标准</h2>
      <p class="mt-2 text-sm text-slate-400">
        上面的关键陈述与待核对问题来自材料本身，不需要绑定；绑定后才有可逐条核验的评分要求。
      </p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton :to="`/materials/${materialId}`" icon="i-lucide-link">去绑定评分标准</UButton>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
      </div>
    </UCard>

    <UCard v-else-if="error" class="mt-4">
      <h2 class="text-lg font-medium">无法装配报告</h2>
      <p class="mt-2 text-sm text-slate-400">请求失败：{{ error }}</p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton icon="i-lucide-refresh-cw" @click="loadReport">重试</UButton>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
      </div>
    </UCard>

    <div v-else-if="report" class="mt-4 space-y-4">
      <p v-if="proposalsUnavailable" class="text-xs text-amber-300">预检记录不可用</p>

      <div v-for="row in report.criteria" :key="row.criterion_id" class="rounded-lg border border-slate-800 p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h2 class="text-sm font-medium text-slate-200">{{ row.title }}</h2>
            <p class="mt-1 text-xs text-slate-500">{{ row.requirement }}</p>
          </div>
          <div class="flex flex-wrap justify-end gap-2">
            <UBadge v-if="neverPreflighted(row.criterion_id)" color="neutral" variant="subtle">尚未预检</UBadge>
            <UBadge v-if="emptyPreflight(row.criterion_id)" color="neutral" variant="subtle">
              {{ row.verified_citation_count > 0 ? '本次未提出新候选' : '预检完成 · 当前材料尚未发现候选引用' }}
            </UBadge>
            <UBadge v-if="pendingFor(row.criterion_id) > 0" color="warning" variant="subtle">
              已发现 {{ pendingFor(row.criterion_id) }} 条候选，待审核
            </UBadge>
            <UBadge v-if="row.verified_citation_count > 0" color="success" variant="subtle">
              已确认关联 {{ row.verified_citation_count }} 条
            </UBadge>
          </div>
        </div>
        <p v-if="failedWithoutCompleted(row.criterion_id)" class="mt-2 text-xs text-red-400">
          预检失败：{{ latestProposal(proposals, row.criterion_id)?.error }}
        </p>
        <p v-if="rowError[row.criterion_id]" class="mt-2 text-xs text-red-400" role="alert">
          {{ rowError[row.criterion_id] }}
        </p>
        <p v-if="emptyPreflight(row.criterion_id)" class="mt-2 text-xs text-slate-500">
          范围：{{ report.filename }} · {{ report.block_count }} 个 Block
        </p>
        <p v-if="pendingFor(row.criterion_id) > 0" class="mt-2 text-xs text-slate-500">
          <RouterLink :to="`/materials/${materialId}`" class="text-violet-300 hover:underline">去材料页审核候选</RouterLink>
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
                <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}” · {{ rowLocation(citation.block_id, citation.line_number) }}</span>
                <span class="ml-2 text-xs text-emerald-400">原文已校验</span>
                <span class="ml-2 inline-flex">
                  <UBadge :color="citation.proposed_by === 'agent' ? 'info' : 'neutral'" variant="subtle" size="sm">
                    {{ citation.proposed_by }}
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
    <section v-if="signalsUnavailable || signals.length > 0" class="mt-4 rounded-lg border border-slate-800 p-4">
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
            <span class="ml-2 font-mono text-xs text-slate-300">“{{ signal.quote }}” · {{ rowLocation(signal.block_id, signal.line_number) }}</span>
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
