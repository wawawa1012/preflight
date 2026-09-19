<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Block, ConsistencyFinding, CrossCompareRequest, CrossCompareResponse, MaterialSummary } from '../types/contracts'
import EvidenceDrawer from '../components/EvidenceDrawer.vue'
import { locatorLabel } from '../utils/locatorLabel'

// 检查两份材料的说法是否一致：只检查两个下拉里由人显式选中的两份材料（主材料 / 对照材料）。
// 打开页面只 GET 材料列表；POST /api/v1/comparisons 只由「检查是否一致」按钮触发，绝不自动扫描材料库。
// findings 由服务端给出：这里不重算、不排名、不下结论，只把每条待核对问题按材料左右分栏摊开。
const materials = ref<MaterialSummary[]>([])
const loading = ref(true)
const loadError = ref('')

const materialIdA = ref('')
const materialIdB = ref('')

const checking = ref(false)
const compareError = ref('')
const result = ref<CrossCompareResponse | null>(null)

// 同一份材料不能与自己核对：不发送请求，就地说明。
const sameSelection = computed(() => materialIdA.value !== '' && materialIdA.value === materialIdB.value)
const canCompare = computed(() => materialIdA.value !== '' && materialIdB.value !== '')
// 空 findings 是合法结果：检查完成，但没有需要核对的同指标不同数字。
const emptyResult = computed(() => result.value !== null && result.value.findings.length === 0)

// 左右分栏要知道每条引用落在哪份材料：靠 Block.document_id 与结果里的两个 id 比对（只读 GET，不写）。
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

// 「检查是否一致」是唯一 POST 入口：两个 id 都选好、且不是同一份材料才发。
async function compare() {
  if (checking.value || !canCompare.value) return
  if (sameSelection.value) {
    result.value = null
    compareError.value = '不能对照同一份材料，请选择两份不同的材料'
    return
  }
  checking.value = true
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
    const compared = body as CrossCompareResponse
    // 先把两份材料的 blocks 取回来再亮结果：分栏判侧需要 document_id，避免先亮后跳。
    await ensureBlocks([compared.material_id_a, compared.material_id_b])
    result.value = compared
  } catch (cause) {
    result.value = null
    compareError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    checking.value = false
  }
}

// 只陈述检测到的事实：同一指标在两份材料下出现不同数字，或需人工判断；不给结论。
function findingLabel(kind: ConsistencyFinding['kind']) {
  return { numeric_inconsistency: '数值不一致', needs_review: '待人工判断' }[kind]
}

const allBlocks = computed(() => Object.values(blocksByMaterial.value).flat())

function blockById(blockId: string): Block | null {
  return allBlocks.value.find((block) => block.id === blockId) ?? null
}

// 引用属于哪一侧：Block 的 document_id 对上结果里的两个 id 才判侧；对不上就不猜（null）。
function citationSide(citation: ConsistencyFinding['citations'][number]): 'a' | 'b' | null {
  const compared = result.value
  if (!compared) return null
  const documentId = blockById(citation.block_id)?.document_id
  if (documentId === compared.material_id_a) return 'a'
  if (documentId === compared.material_id_b) return 'b'
  return null
}

function sideCitations(finding: ConsistencyFinding, side: 'a' | 'b') {
  return finding.citations.filter((citation) => citationSide(citation) === side)
}

// 原文还没到手时判不了侧：这些引用放在分栏下方原样列出，不假装归到某一边。
function unsidedCitations(finding: ConsistencyFinding) {
  return finding.citations.filter((citation) => citationSide(citation) === null)
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

async function ensureBlocks(ids: string[]) {
  const missing = ids.filter((id) => id !== '' && !(id in blocksByMaterial.value))
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
  await ensureBlocks(result.value ? [result.value.material_id_a, result.value.material_id_b] : [materialIdA.value, materialIdB.value])
}

// 首次进入只读：唯一加载是 GET /api/v1/materials。
loadMaterials()
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 py-10">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 class="text-3xl font-semibold tracking-tight">检查两份材料有没有说法不一致</h1>
        <p class="mt-2 text-sm text-slate-400">看它们是否对同一指标说了不同的数字。</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">材料库</UButton>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
      </div>
    </div>

    <UCard class="mt-6">
      <p v-if="loading" class="text-sm text-slate-400">正在读取材料列表…</p>
      <div v-else-if="loadError">
        <p class="text-sm text-slate-400">请求失败：{{ loadError }}</p>
        <UButton class="mt-4" size="sm" icon="i-lucide-refresh-cw" @click="loadMaterials">重试</UButton>
      </div>
      <div v-else-if="materials.length < 2">
        <p class="text-sm text-slate-300">至少需要两份已保存的材料才能检查。</p>
        <UButton class="mt-4" size="sm" to="/materials/new" icon="i-lucide-plus">添加材料</UButton>
      </div>
      <div v-else>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="text-xs text-slate-400">
            主材料
            <select
              v-model="materialIdA"
              aria-label="主材料"
              class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            >
              <option value="">请选择材料</option>
              <option v-for="item in materials" :key="item.id" :value="item.id">{{ item.filename }}</option>
            </select>
          </label>
          <label class="text-xs text-slate-400">
            对照材料
            <select
              v-model="materialIdB"
              aria-label="对照材料"
              class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            >
              <option value="">请选择材料</option>
              <option v-for="item in materials" :key="item.id" :value="item.id">{{ item.filename }}</option>
            </select>
          </label>
        </div>
        <p class="mt-3 text-xs text-slate-500">只检查你选中的这两份材料；点引用可回看原文。</p>
        <div class="mt-4 flex flex-wrap items-center gap-3">
          <UButton icon="i-lucide-git-compare" :loading="checking" :disabled="!canCompare" @click="compare">
            {{ checking ? '检查中…' : '检查是否一致' }}
          </UButton>
          <span v-if="sameSelection" class="text-xs text-amber-300">不能对照同一份材料，请选择两份不同的材料</span>
        </div>
        <p v-if="compareError" class="mt-3 text-sm text-red-400" role="alert">{{ compareError }}</p>
      </div>
    </UCard>

    <!-- 检查结果：一条待核对问题一行，细条放指标与类型，左右两栏各放一份材料的引用；空结果合法。 -->
    <section v-if="result" class="mt-6 rounded-lg border border-slate-800 p-4">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h2 class="text-sm font-medium text-slate-200">发现 {{ result.findings.length }} 处需要核对</h2>
        <span class="text-xs text-slate-500">{{ result.filename_a }} · {{ result.filename_b }}</span>
      </div>
      <p v-if="emptyResult" class="mt-3 text-sm text-slate-400">
        当前范围尚未发现同指标不同数字；中英译文通常对不上，需要两份材料对同一个指标各自给出数字。
      </p>
      <ul v-else class="mt-3 space-y-3">
        <li
          v-for="finding in result.findings"
          :key="`${finding.kind}:${finding.measure}:${finding.citations[0].block_id}:${finding.citations[0].start}`"
          class="rounded-md border border-slate-800 p-3"
        >
          <div class="flex flex-wrap items-center justify-center gap-2 border-b border-slate-800 pb-2">
            <UBadge
              :color="finding.kind === 'numeric_inconsistency' ? 'warning' : 'neutral'"
              variant="subtle"
              size="sm"
            >
              {{ findingLabel(finding.kind) }}
            </UBadge>
            <span v-if="finding.measure" class="text-xs text-slate-300">指标：{{ finding.measure }}</span>
            <span class="font-mono text-xs text-slate-400">{{ finding.values.join(' / ') }}</span>
          </div>
          <div class="mt-2 grid gap-2 sm:grid-cols-2">
            <div class="rounded-md bg-slate-900/40 p-2">
              <p class="text-[11px] text-slate-500">主材料 · {{ result.filename_a }}</p>
              <ul class="mt-1 space-y-1">
                <li v-for="citation in sideCitations(finding, 'a')" :key="`a:${citation.block_id}:${citation.start}`">
                  <button
                    type="button"
                    class="w-full rounded-md bg-slate-900/60 p-2 text-left transition hover:bg-slate-800/60"
                    @click="openCitation(citation)"
                  >
                    <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}” · {{ rowLocation(citation.block_id, citation.line_number) }}</span>
                  </button>
                </li>
              </ul>
              <p v-if="sideCitations(finding, 'a').length === 0" class="mt-1 text-xs text-slate-600">—</p>
            </div>
            <div class="rounded-md bg-slate-900/40 p-2">
              <p class="text-[11px] text-slate-500">对照材料 · {{ result.filename_b }}</p>
              <ul class="mt-1 space-y-1">
                <li v-for="citation in sideCitations(finding, 'b')" :key="`b:${citation.block_id}:${citation.start}`">
                  <button
                    type="button"
                    class="w-full rounded-md bg-slate-900/60 p-2 text-left transition hover:bg-slate-800/60"
                    @click="openCitation(citation)"
                  >
                    <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}” · {{ rowLocation(citation.block_id, citation.line_number) }}</span>
                  </button>
                </li>
              </ul>
              <p v-if="sideCitations(finding, 'b').length === 0" class="mt-1 text-xs text-slate-600">—</p>
            </div>
          </div>
          <ul v-if="unsidedCitations(finding).length > 0" class="mt-2 space-y-1">
            <li v-for="citation in unsidedCitations(finding)" :key="`u:${citation.block_id}:${citation.start}`">
              <button
                type="button"
                class="w-full rounded-md bg-slate-900/60 p-2 text-left transition hover:bg-slate-800/60"
                @click="openCitation(citation)"
              >
                <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}” · {{ rowLocation(citation.block_id, citation.line_number) }}</span>
              </button>
            </li>
          </ul>
          <p class="mt-2 text-xs text-slate-500">{{ finding.explanation }}</p>
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
