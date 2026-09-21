<script setup lang="ts">
import { ref } from 'vue'
import type { RunReport } from '../types/contracts'
import { locatorLabel } from '../utils/locatorLabel'

type Finding = RunReport['findings'][number]
type EvidenceItem = RunReport['evidence'][number]

const report = ref<RunReport | null>(null)
const loading = ref(true)
const error = ref('')
const selectedFinding = ref<Finding | null>(null)

const kindLabels: Record<Finding['kind'], string> = {
  missing_evidence: 'Missing',
  weak_evidence: 'Weak',
  unsupported_claim: 'Unsupported',
  cross_document_conflict: 'Conflict',
  overclaim: 'Overclaim',
}

const kindColors: Record<Finding['kind'], 'error' | 'warning' | 'neutral'> = {
  missing_evidence: 'error',
  weak_evidence: 'warning',
  unsupported_claim: 'warning',
  cross_document_conflict: 'error',
  overclaim: 'warning',
}

const relationLabels: Record<EvidenceItem['relation'], string> = {
  supports: 'Supports',
  contradicts: 'Contradicts',
  context: 'Context',
}

const relationColors: Record<EvidenceItem['relation'], 'success' | 'error' | 'neutral'> = {
  supports: 'success',
  contradicts: 'error',
  context: 'neutral',
}

async function loadReport() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/v1/report')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data: RunReport = await response.json()
    report.value = data
    selectedFinding.value = data.findings[0] ?? null
  } catch (cause) {
    // 后端不可用时不退回本地 mock，明确报错。
    report.value = null
    selectedFinding.value = null
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

function blockById(id: string) {
  return report.value?.blocks.find(block => block.id === id)
}

function documentLabel(blockId: string) {
  const block = blockById(blockId)
  if (!block) return '未知位置'
  const document = report.value?.documents.find(item => item.id === block.document_id)
  return `${document ? document.filename : block.document_id} · ${locatorLabel(block.locator)}`
}

function evidenceRows(finding: Finding) {
  const current = report.value
  if (!current) return []
  return finding.evidence_ids
    .map(id => current.evidence.find(item => item.id === id))
    .filter(item => item !== undefined)
    .map(item => ({
      id: item.id,
      location: documentLabel(item.source.block_id),
      quote: item.source.quote,
      relation: item.relation,
    }))
}

function claimsOf(finding: Finding) {
  const current = report.value
  if (!current) return []
  return finding.claim_ids
    .map(id => current.claims.find(item => item.id === id))
    .filter(item => item !== undefined)
}

function criterionOf(finding: Finding) {
  return report.value?.rubric.criteria.find(item => item.id === finding.criterion_id)
}

function searchedDocuments(finding: Finding) {
  const current = report.value
  if (!current) return []
  return finding.searched_document_ids.map(id => current.documents.find(item => item.id === id)?.filename ?? id)
}

function rubricCoverageLabel() {
  const current = report.value
  if (!current || current.metrics.rubric_coverage === null) return '未评估'
  const supported = current.assessments.filter(item => item.status === 'supported').length
  return `${supported} / ${current.rubric.criteria.length}`
}

loadReport()
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-16">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="text-sm font-medium text-violet-400">REPORT / MOCK</p>
        <h1 class="mt-2 text-3xl font-semibold tracking-tight">{{ report ? report.project.name : 'Report' }}</h1>
        <p class="mt-2 text-sm text-slate-400">
          {{ report ? `${report.findings.length} 条 findings · ${report.material_version.label}` : '从后端读取统一契约 Mock' }}
        </p>
      </div>
      <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">返回 Workbench</UButton>
    </div>

    <UCard v-if="loading" class="mt-6">
      <p class="text-sm text-slate-400">正在从后端读取报告…</p>
    </UCard>

    <UCard v-else-if="error" class="mt-6">
      <h2 class="text-lg font-medium">无法加载报告</h2>
      <p class="mt-2 text-sm text-slate-400">请求 /api/v1/report 失败：{{ error }}</p>
      <p class="mt-1 text-sm text-slate-400">请按 README 启动后端后重试；页面不会退回本地 mock。</p>
      <UButton class="mt-6" icon="i-lucide-refresh-cw" @click="loadReport">重试</UButton>
    </UCard>

    <div v-else-if="report" class="mt-6">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div class="rounded-lg border border-slate-800 p-3">
          <p class="text-xs text-slate-400">Submission readiness</p>
          <p class="mt-1 font-medium">{{ report.metrics.submission_readiness }}</p>
        </div>
        <div class="rounded-lg border border-slate-800 p-3">
          <p class="text-xs text-slate-400">Rubric coverage</p>
          <p class="mt-1 font-medium">{{ rubricCoverageLabel() }}</p>
        </div>
        <div class="rounded-lg border border-slate-800 p-3">
          <p class="text-xs text-slate-400">Verified evidence</p>
          <p class="mt-1 font-medium">{{ report.metrics.verified_evidence }}</p>
        </div>
        <div class="rounded-lg border border-slate-800 p-3">
          <p class="text-xs text-slate-400">Critical risks</p>
          <p class="mt-1 font-medium">{{ report.metrics.critical_risks }}</p>
        </div>
      </div>

      <div class="mt-6 grid gap-6 lg:grid-cols-3">
        <section class="space-y-3 lg:col-span-2">
          <UCard
            v-for="finding in report.findings"
            :key="finding.id"
            class="cursor-pointer transition"
            :class="selectedFinding && finding.id === selectedFinding.id ? 'ring-2 ring-violet-500' : 'hover:ring-1 hover:ring-slate-600'"
            @click="selectedFinding = finding"
          >
            <div class="flex items-start justify-between gap-4">
              <h2 class="font-medium">{{ finding.title }}</h2>
              <div class="flex shrink-0 items-center gap-2">
                <UBadge v-if="finding.severity === 'critical'" color="error" variant="solid" size="sm">Critical</UBadge>
                <UBadge :color="kindColors[finding.kind]" variant="subtle">{{ kindLabels[finding.kind] }}</UBadge>
              </div>
            </div>
            <p class="mt-1 text-sm text-violet-400">{{ criterionOf(finding)?.title ?? finding.criterion_id }}</p>
            <p class="mt-3 text-sm text-slate-400">{{ finding.explanation }}</p>
          </UCard>
        </section>

        <aside v-if="selectedFinding">
          <UCard class="lg:sticky lg:top-8">
            <div class="flex items-center justify-between gap-4">
              <h2 class="text-lg font-medium">Evidence</h2>
              <UBadge :color="kindColors[selectedFinding.kind]" variant="subtle">{{ kindLabels[selectedFinding.kind] }}</UBadge>
            </div>

            <div v-if="evidenceRows(selectedFinding).length > 0" class="mt-6 space-y-4">
              <p
                v-if="claimsOf(selectedFinding).length > 0 && claimsOf(selectedFinding)[0].comparison_key"
                class="text-xs text-slate-500"
              >
                同一指标、同一数据集/条件、同一材料版本（{{ report.material_version.label }}）·
                {{ claimsOf(selectedFinding)[0].comparison_key }}
              </p>
              <div v-for="row in evidenceRows(selectedFinding)" :key="row.id" class="rounded-lg border border-slate-800 p-4">
                <div class="flex items-center justify-between gap-3">
                  <p class="text-sm font-medium">{{ row.location }}</p>
                  <UBadge :color="relationColors[row.relation]" variant="subtle">{{ relationLabels[row.relation] }}</UBadge>
                </div>
                <p class="mt-2 text-sm text-slate-300">“{{ row.quote }}”</p>
              </div>
            </div>

            <div v-else class="mt-6 space-y-4">
              <p class="text-sm text-slate-300">没有可引用的 Evidence（{{ kindLabels[selectedFinding.kind] }}）。</p>
              <div v-if="criterionOf(selectedFinding)" class="rounded-lg border border-slate-800 p-4">
                <p class="text-sm font-medium">{{ criterionOf(selectedFinding)?.title }}</p>
                <p class="mt-1 text-sm text-slate-400">{{ criterionOf(selectedFinding)?.requirement }}</p>
              </div>
              <div v-for="claim in claimsOf(selectedFinding)" :key="claim.id" class="rounded-lg border border-slate-800 p-4">
                <p class="text-sm font-medium">Claim 原文（非 Evidence）· {{ documentLabel(claim.source.block_id) }}</p>
                <p class="mt-2 text-sm text-slate-300">“{{ claim.source.quote }}”</p>
              </div>
              <p class="text-xs text-slate-500">检索范围：{{ searchedDocuments(selectedFinding).join('、') }}</p>
            </div>
          </UCard>
        </aside>
      </div>
    </div>
  </main>
</template>
