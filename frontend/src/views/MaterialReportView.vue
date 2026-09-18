<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import type { MaterialPreflightCitation, MaterialPreflightReport } from '../types/contracts'
import EvidenceDrawer from '../components/EvidenceDrawer.vue'

// 材料级预审报告：只读展示已核证引用与当前检索范围，不做满足判定。
const route = useRoute()
const materialId = String(route.params.materialId)

const report = ref<MaterialPreflightReport | null>(null)
const loading = ref(true)
const notFound = ref(false)
const unbound = ref(false)
const error = ref('')

const drawerOpen = ref(false)
const selectedCitation = ref<MaterialPreflightCitation | null>(null)

async function loadReport() {
  loading.value = true
  error.value = ''
  notFound.value = false
  unbound.value = false
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

function blockFor(citation: MaterialPreflightCitation) {
  return report.value?.blocks.find((block) => block.id === citation.block_id) ?? null
}

function openCitation(citation: MaterialPreflightCitation) {
  selectedCitation.value = citation
  drawerOpen.value = true
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
          <span v-else>按评审标准查看每条要求的已核证引用</span>
        </p>
      </div>
      <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
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
      <UButton class="mt-6" :to="`/materials/${materialId}`" icon="i-lucide-link">去绑定评分标准</UButton>
    </UCard>

    <UCard v-else-if="error" class="mt-6">
      <h2 class="text-lg font-medium">无法装配报告</h2>
      <p class="mt-2 text-sm text-slate-400">请求失败：{{ error }}</p>
      <UButton class="mt-6" icon="i-lucide-refresh-cw" @click="loadReport">重试</UButton>
    </UCard>

    <div v-else-if="report" class="mt-6 space-y-4">
      <div v-for="row in report.criteria" :key="row.criterion_id" class="rounded-lg border border-slate-800 p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h2 class="text-sm font-medium text-slate-200">{{ row.title }}</h2>
            <p class="mt-1 text-xs text-slate-500">{{ row.requirement }}</p>
          </div>
          <UBadge v-if="row.verified_citation_count > 0" color="success" variant="subtle">
            已核证引用 {{ row.verified_citation_count }} 条
          </UBadge>
          <UBadge v-else color="neutral" variant="subtle">当前范围尚未发现引用</UBadge>
        </div>

        <ul v-if="row.citations.length > 0" class="mt-3 space-y-2">
          <li v-for="citation in row.citations" :key="citation.link_id">
            <button
              type="button"
              class="w-full rounded-md bg-slate-900/60 p-2 text-left transition hover:bg-slate-800/60"
              @click="openCitation(citation)"
            >
              <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}” · line {{ citation.line_number }}</span>
              <span class="ml-2 inline-flex">
                <UBadge :color="citation.proposed_by === 'agent' ? 'info' : 'neutral'" variant="subtle" size="sm">
                  {{ citation.proposed_by }}
                </UBadge>
              </span>
              <span class="mt-1 block text-xs text-slate-500">用途：{{ citation.rationale }}</span>
            </button>
          </li>
        </ul>
        <p v-else-if="row.missing" class="mt-3 text-xs text-slate-500">{{ row.missing.explanation }}</p>
      </div>
    </div>

    <EvidenceDrawer
      :open="drawerOpen"
      :citation="selectedCitation"
      :block="selectedCitation ? blockFor(selectedCitation) : null"
      :filename="report?.filename ?? ''"
      @update:open="drawerOpen = $event"
    />
  </main>
</template>
