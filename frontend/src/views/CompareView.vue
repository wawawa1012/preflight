<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Block, ConsistencyFinding, CrossCompareRequest, CrossCompareResponse, MaterialSummary } from '../types/contracts'
import EvidenceDrawer from '../components/EvidenceDrawer.vue'
import { locatorLabel } from '../utils/locatorLabel'

// 两材料数值对照：只比较两个下拉里由人显式选中的两个材料 id。
// 打开页面只 GET 材料列表；POST /api/v1/comparisons 只由「对照」按钮触发，绝不自动扫描材料库。
const materials = ref<MaterialSummary[]>([])
const loading = ref(true)
const loadError = ref('')

const materialIdA = ref('')
const materialIdB = ref('')

const comparing = ref(false)
const compareError = ref('')
const result = ref<CrossCompareResponse | null>(null)

// 同一份材料不能与自己对照：不发送请求，就地说明。
const sameSelection = computed(() => materialIdA.value !== '' && materialIdA.value === materialIdB.value)
const canCompare = computed(() => materialIdA.value !== '' && materialIdB.value !== '')
// 空 findings 是合法结果：对照完成但没有可对照的数值差异。
const emptyResult = computed(() => result.value !== null && result.value.findings.length === 0)

// Drawer 需要 Block 本体：点开引用时才按需 GET 两份材料的 blocks（只读）。
const blocksByMaterial = ref<Record<string, Block[]>>({})
const blocksUnavailable = ref(false)

const drawerOpen = ref(false)
const drawerBlockId = ref('')
const highlight = ref<{ line_number: number; start: number; end: number } | null>(null)

async function loadMaterials() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetch('/api/v1/materials')
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    materials.value = Array.isArray(body) ? (body as MaterialSummary[]) : []
  } catch (cause) {
    loadError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

// 「对照」是唯一 POST 入口：两个 id 都选好、且不是同一份材料才发。
async function compare() {
  if (comparing.value || !canCompare.value) return
  if (sameSelection.value) {
    result.value = null
    compareError.value = '不能对照同一份材料，请选择两份不同的材料'
    return
  }
  comparing.value = true
  compareError.value = ''
  const payload: CrossCompareRequest = { material_id_a: materialIdA.value, material_id_b: materialIdB.value }
  try {
    const response = await fetch('/api/v1/comparisons', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    result.value = body as CrossCompareResponse
  } catch (cause) {
    result.value = null
    compareError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    comparing.value = false
  }
}

// 只陈述检测到的事实：同一度量词在两份材料下出现不同数值，或需人工判断；不给结论。
function findingLabel(kind: ConsistencyFinding['kind']) {
  return { numeric_inconsistency: '数值不一致', needs_review: '待人工判断' }[kind]
}

const allBlocks = computed(() => Object.values(blocksByMaterial.value).flat())

function blockById(blockId: string): Block | null {
  return allBlocks.value.find((block) => block.id === blockId) ?? null
}

// 引用行只说位置：Block 到手用它的 Locator，未到手退回 line_number（本季只有 md 入库，不发明第二套编号）。
function rowLocation(blockId: string, lineNumber: number): string {
  const locator = blockById(blockId)?.locator
  return locator ? locatorLabel(locator) : locatorLabel({ kind: 'line', index: lineNumber })
}

function materialOf(blockId: string): string | null {
  for (const [materialId, blocks] of Object.entries(blocksByMaterial.value)) {
    if (blocks.some((block) => block.id === blockId)) return materialId
  }
  return null
}

function blockAt(offset: number): Block | null {
  const materialId = materialOf(drawerBlockId.value)
  if (!materialId) return null
  const blocks = blocksByMaterial.value[materialId] ?? []
  const index = blocks.findIndex((block) => block.id === drawerBlockId.value)
  if (index < 0) return null
  return blocks[index + offset] ?? null
}

const drawerBlock = computed(() => blockById(drawerBlockId.value))
const previousBlock = computed(() => blockAt(-1))
const nextBlock = computed(() => blockAt(1))

const drawerFilename = computed(() => {
  const materialId = materialOf(drawerBlockId.value)
  const material = materialId ? materials.value.find((item) => item.id === materialId) : undefined
  return material ? material.filename : (result.value?.filename_a ?? '')
})

async function ensureBlocks() {
  const missing = [materialIdA.value, materialIdB.value].filter((id) => id !== '' && !(id in blocksByMaterial.value))
  if (missing.length === 0 || blocksUnavailable.value) return
  for (const id of missing) {
    try {
      const response = await fetch(`/api/v1/materials/${encodeURIComponent(id)}`)
      const body = await response.json().catch(() => null)
      if (!response.ok) {
        blocksUnavailable.value = true
        return
      }
      blocksByMaterial.value = {
        ...blocksByMaterial.value,
        [id]: Array.isArray(body?.blocks) ? (body.blocks as Block[]) : [],
      }
    } catch {
      blocksUnavailable.value = true
      return
    }
  }
}

async function openCitation(citation: ConsistencyFinding['citations'][number]) {
  highlight.value = { line_number: citation.line_number, start: citation.start, end: citation.end }
  drawerBlockId.value = citation.block_id
  drawerOpen.value = true
  await ensureBlocks()
}

// 首次进入只读：唯一加载是 GET /api/v1/materials。
loadMaterials()
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 py-10">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="text-sm font-medium text-violet-400">COMPARE</p>
        <h1 class="mt-2 text-3xl font-semibold tracking-tight">两材料对照</h1>
        <p class="mt-2 text-sm text-slate-400">只对照你显式选中的两份材料，逐条回看原文；打开页面不会发起对照请求。</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">材料库</UButton>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
      </div>
    </div>

    <UCard class="mt-6">
      <p v-if="loading" class="text-sm text-slate-400">正在读取材料列表…</p>
      <div v-else-if="loadError">
        <p class="text-sm text-slate-400">请求失败：{{ loadError }}</p>
        <UButton class="mt-4" size="sm" icon="i-lucide-refresh-cw" @click="loadMaterials">重试</UButton>
      </div>
      <div v-else-if="materials.length < 2">
        <p class="text-sm text-slate-300">至少需要两份已保存的材料才能对照。</p>
        <UButton class="mt-4" size="sm" to="/materials/new" icon="i-lucide-plus">添加材料</UButton>
      </div>
      <div v-else>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="text-xs text-slate-400">
            材料 A
            <select
              v-model="materialIdA"
              aria-label="材料 A"
              class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            >
              <option value="">请选择材料</option>
              <option v-for="item in materials" :key="item.id" :value="item.id">{{ item.filename }}</option>
            </select>
          </label>
          <label class="text-xs text-slate-400">
            材料 B
            <select
              v-model="materialIdB"
              aria-label="材料 B"
              class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            >
              <option value="">请选择材料</option>
              <option v-for="item in materials" :key="item.id" :value="item.id">{{ item.filename }}</option>
            </select>
          </label>
        </div>
        <p class="mt-3 text-xs text-slate-500">范围：只对照选中的两份材料，不会自动扫描材料库。</p>
        <div class="mt-4 flex flex-wrap items-center gap-3">
          <UButton icon="i-lucide-git-compare" :loading="comparing" :disabled="!canCompare" @click="compare">
            {{ comparing ? '对照中…' : '对照' }}
          </UButton>
          <span v-if="sameSelection" class="text-xs text-amber-300">不能对照同一份材料，请选择两份不同的材料</span>
        </div>
        <p v-if="compareError" class="mt-3 text-sm text-red-400" role="alert">{{ compareError }}</p>
      </div>
    </UCard>

    <!-- 对照结果：findings 只保留引用横跨两份材料的数值对照；空结果合法。 -->
    <section v-if="result" class="mt-6 rounded-lg border border-slate-800 p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-sm font-medium text-slate-200">{{ result.filename_a }} × {{ result.filename_b }}</h2>
        <span class="text-xs text-slate-500">{{ result.findings.length }} 条 · 引用横跨两份材料</span>
      </div>
      <p v-if="emptyResult" class="mt-3 text-sm text-slate-400">
        本次对照未发现跨两份材料的数值差异；空结果合法，只说明这两份材料间没有可对照的同度量词数值。
      </p>
      <ul v-else class="mt-3 space-y-3">
        <li
          v-for="finding in result.findings"
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
                @click="openCitation(citation)"
              >
                <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}” · {{ rowLocation(citation.block_id, citation.line_number) }}</span>
              </button>
            </li>
          </ul>
        </li>
      </ul>
      <p v-if="blocksUnavailable" class="mt-3 text-xs text-amber-300">原文暂不可用</p>
    </section>

    <EvidenceDrawer
      :open="drawerOpen"
      :highlight="highlight"
      :block="drawerBlock"
      :previous-block="previousBlock"
      :next-block="nextBlock"
      :filename="drawerFilename"
      @update:open="drawerOpen = $event"
    />
  </main>
</template>
