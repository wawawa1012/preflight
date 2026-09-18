<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { AgentProposal, Block, ConsistencyFinding, DetectedStatement, MaterialPreflightCitation, MaterialPreflightReport } from '../types/contracts'
import EvidenceDrawer from '../components/EvidenceDrawer.vue'
import { latestCompletedProposal, latestProposal, passedCount, pendingPassedCount } from '../utils/preflightFacts'

// 材料级预审报告：关联来自装配端点；关键陈述来自 statement-signals；预检态由提案列表前端组合。
const route = useRoute()
const materialId = String(route.params.materialId)

const report = ref<MaterialPreflightReport | null>(null)
const proposals = ref<AgentProposal[]>([])
const proposalsUnavailable = ref(false)
const signals = ref<DetectedStatement[]>([])
const signalsUnavailable = ref(false)
// I8 待核对问题：同材料内的数值对照结论由后端纯函数给出，前端只渲染。
const findings = ref<ConsistencyFinding[]>([])
const findingsUnavailable = ref(false)
const loading = ref(true)
const notFound = ref(false)
const unbound = ref(false)
const error = ref('')

const drawerOpen = ref(false)
const highlight = ref<{ line_number: number; start: number; end: number } | null>(null)
const drawerBlockId = ref('')

async function loadReport() {
  loading.value = true
  error.value = ''
  notFound.value = false
  unbound.value = false
  proposalsUnavailable.value = false
  proposals.value = []
  signalsUnavailable.value = false
  signals.value = []
  findingsUnavailable.value = false
  findings.value = []
  try {
    const [reportRes, proposalRes, signalRes, findingRes] = await Promise.all([
      fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/preflight-report`),
      fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/agent-proposals`),
      fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/statement-signals`),
      fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/consistency-findings`),
    ])
    const body = await reportRes.json().catch(() => null)
    if (reportRes.status === 404) {
      notFound.value = true
      return
    }
    if (reportRes.status === 409) {
      unbound.value = true
      return
    }
    if (!reportRes.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${reportRes.status}`)
    }
    report.value = body as MaterialPreflightReport
    if (proposalRes.ok) {
      const proposalBody = await proposalRes.json().catch(() => null)
      proposals.value = Array.isArray(proposalBody) ? (proposalBody as AgentProposal[]) : []
    } else {
      proposalsUnavailable.value = true
    }
    if (signalRes.ok) {
      const signalBody = await signalRes.json().catch(() => null)
      signals.value = Array.isArray(signalBody) ? (signalBody as DetectedStatement[]) : []
    } else {
      signalsUnavailable.value = true
    }
    if (findingRes.ok) {
      const findingBody = await findingRes.json().catch(() => null)
      findings.value = Array.isArray(findingBody) ? (findingBody as ConsistencyFinding[]) : []
    } else {
      findingsUnavailable.value = true
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

const drawerBlock = computed(() => blockAt(0))
const previousBlock = computed(() => blockAt(-1))
const nextBlock = computed(() => blockAt(1))

function blockAt(offset: number): Block | null {
  const blocks = report.value?.blocks ?? []
  const index = blocks.findIndex((item) => item.id === drawerBlockId.value)
  if (index < 0) return null
  return blocks[index + offset] ?? null
}

function openHighlight(target: { block_id: string; line_number: number; start: number; end: number }) {
  highlight.value = { line_number: target.line_number, start: target.start, end: target.end }
  drawerBlockId.value = target.block_id
  drawerOpen.value = true
}

function openCitation(citation: MaterialPreflightCitation) {
  openHighlight(citation)
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

loadReport()
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-10">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="text-sm font-medium text-violet-400">PREFLIGHT REPORT</p>
        <h1 class="mt-2 text-3xl font-semibold tracking-tight">{{ report ? report.filename : '预审报告' }}</h1>
        <p class="mt-2 text-sm text-slate-400">
          <span v-if="report">{{ report.rubric_title }} · rev{{ report.rubric_revision }} · {{ report.block_count }} 个 Block</span>
          <span v-else>按评审标准查看每条要求的已确认关联</span>
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <UButton :to="`/materials/${materialId}`" color="neutral" variant="subtle" icon="i-lucide-file-text">返回材料</UButton>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
      </div>
    </div>

    <UCard v-if="loading" class="mt-6">
      <p class="text-sm text-slate-400">正在装配预审报告…</p>
    </UCard>

    <UCard v-else-if="notFound" class="mt-6">
      <h2 class="text-lg font-medium">找不到该材料</h2>
      <p class="mt-2 text-sm text-slate-400">该 ID 不存在，或本地数据库中没有这条记录。</p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton :to="`/materials/${materialId}`" color="neutral" variant="subtle" icon="i-lucide-file-text">
          返回材料
        </UButton>
        <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">全部材料</UButton>
      </div>
    </UCard>

    <UCard v-else-if="unbound" class="mt-6">
      <h2 class="text-lg font-medium">尚未绑定评分标准</h2>
      <p class="mt-2 text-sm text-slate-400">先到材料页绑定一套标准，报告才有可对照的评分要求。</p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton :to="`/materials/${materialId}`" icon="i-lucide-link">去绑定评分标准</UButton>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
      </div>
    </UCard>

    <UCard v-else-if="error" class="mt-6">
      <h2 class="text-lg font-medium">无法装配报告</h2>
      <p class="mt-2 text-sm text-slate-400">请求失败：{{ error }}</p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton icon="i-lucide-refresh-cw" @click="loadReport">重试</UButton>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
      </div>
    </UCard>

    <div v-else-if="report" class="mt-6 space-y-4">
      <p v-if="proposalsUnavailable" class="text-xs text-amber-300">预检记录不可用</p>

      <!-- 关键陈述：确定性扫描结果，只标出值得核对的句子，不判真假。 -->
      <section v-if="signalsUnavailable || signals.length > 0" class="rounded-lg border border-slate-800 p-4">
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
              <span class="ml-2 font-mono text-xs text-slate-300">“{{ signal.quote }}” · line {{ signal.line_number }}</span>
            </button>
          </li>
        </ul>
      </section>

      <!-- I8 待核对问题：同一材料内同一度量词的数值对照；每条都能点回原文 Drawer。 -->
      <section v-if="findingsUnavailable || findings.length > 0" class="rounded-lg border border-slate-800 p-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-sm font-medium text-slate-200">待核对问题</h2>
          <span class="text-xs text-slate-500">{{ findings.length }} 条 · 同一材料内数值对照</span>
        </div>
        <p v-if="findingsUnavailable" class="mt-2 text-xs text-amber-300">待核对问题不可用</p>
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
                  <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}” · line {{ citation.line_number }}</span>
                </button>
              </li>
            </ul>
          </li>
        </ul>
      </section>

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
        <p v-if="emptyPreflight(row.criterion_id)" class="mt-2 text-xs text-slate-500">
          范围：{{ report.filename }} · {{ report.block_count }} 个 Block
        </p>
        <p v-if="pendingFor(row.criterion_id) > 0" class="mt-2 text-xs text-slate-500">
          <RouterLink :to="`/materials/${materialId}`" class="text-violet-300 hover:underline">去材料页审核候选</RouterLink>
        </p>

        <ul v-if="row.citations.length > 0" class="mt-3 space-y-2">
          <li v-for="citation in row.citations" :key="citation.link_id">
            <button
              type="button"
              class="w-full rounded-md bg-slate-900/60 p-2 text-left transition hover:bg-slate-800/60"
              @click="openCitation(citation)"
            >
              <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}” · line {{ citation.line_number }}</span>
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
        <p v-else-if="emptyPreflight(row.criterion_id) && row.missing" class="mt-3 text-xs text-slate-500">
          {{ row.missing.explanation }}
        </p>
      </div>
    </div>

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
