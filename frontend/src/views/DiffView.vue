<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Block, ConsistencyFinding, MaterialSummary } from '../types/contracts'
import EvidenceDrawer from '../components/EvidenceDrawer.vue'
import { locatorLabel } from '../utils/locatorLabel'

// 修改前后变化时间线：只比较两个下拉里由人显式选中的「修改前 / 修改后」两个材料 id。
// 打开页面只 GET 材料列表；POST /api/v1/diffs 只由「比较修改效果」按钮触发，不会自动扫描材料库。
// 契约与后端 app/diff.py 同形，自带在本视图内，不改共享 types。
interface DiffRequest {
  material_id_before: string
  material_id_after: string
}
interface DiffResponse {
  material_id_before: string
  material_id_after: string
  filename_before: string
  filename_after: string
  resolved: ConsistencyFinding[]
  unchanged: ConsistencyFinding[]
  new: ConsistencyFinding[]
}

const materials = ref<MaterialSummary[]>([])
const loading = ref(true)
const loadError = ref('')

const materialIdBefore = ref('')
const materialIdAfter = ref('')

const diffing = ref(false)
const diffError = ref('')
const result = ref<DiffResponse | null>(null)

// 同一份材料不能与自己做修改前后对照：不发送请求，就地说明。
const sameSelection = computed(() => materialIdBefore.value !== '' && materialIdBefore.value === materialIdAfter.value)
const canDiff = computed(() => materialIdBefore.value !== '' && materialIdAfter.value !== '')

// 修改前的待处理数 = 已解决 + 仍存在；修改后的待处理数 = 仍存在 + 新增。
const beforeCount = computed(() => (result.value ? result.value.resolved.length + result.value.unchanged.length : 0))
const afterCount = computed(() => (result.value ? result.value.unchanged.length + result.value.new.length : 0))

// 三组都空是合法结果：对照完成但两份版本间没有可对照的数值一致性差异。
const emptyResult = computed(
  () =>
    result.value !== null &&
    result.value.resolved.length === 0 &&
    result.value.unchanged.length === 0 &&
    result.value.new.length === 0,
)

// 变化时间线固定顺序：已解决（emerald）→ 仍存在（amber）→ 新增（rose）；空组也渲染（合法结果）。
const groups = computed(() =>
  result.value === null
    ? []
    : [
        { key: 'resolved', title: '已解决', tone: 'emerald', hint: '修改前存在、修改后不再出现。', findings: result.value.resolved },
        { key: 'unchanged', title: '仍存在', tone: 'amber', hint: '修改前后都在，还没有被改掉。', findings: result.value.unchanged },
        { key: 'new', title: '新增', tone: 'rose', hint: '修改前没有、修改后新出现。', findings: result.value.new },
      ],
)

// 组色调只做视觉提示（点 / 大数字 / 卡片描边），不改文案语义。
const toneDot: Record<string, string> = {
  emerald: 'border-emerald-400 bg-emerald-950',
  amber: 'border-amber-400 bg-amber-950',
  rose: 'border-rose-400 bg-rose-950',
}
const toneCount: Record<string, string> = {
  emerald: 'text-emerald-300',
  amber: 'text-amber-300',
  rose: 'text-rose-300',
}
const toneCard: Record<string, string> = {
  emerald: 'border-emerald-900/70',
  amber: 'border-amber-900/70',
  rose: 'border-rose-900/70',
}

// Drawer 需要 Block 本体：点开引用时才按需 GET 两份版本的 blocks（只读）。
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

// 「比较修改效果」是唯一 POST 入口：两个 id 都选好、且不是同一份材料才发。
async function compare() {
  if (diffing.value || !canDiff.value) return
  if (sameSelection.value) {
    result.value = null
    diffError.value = '不能对照同一份材料，请选择两份不同的材料'
    return
  }
  diffing.value = true
  diffError.value = ''
  const payload: DiffRequest = { material_id_before: materialIdBefore.value, material_id_after: materialIdAfter.value }
  try {
    const response = await fetch('/api/v1/diffs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    result.value = body as DiffResponse
  } catch (cause) {
    result.value = null
    diffError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    diffing.value = false
  }
}

// 只陈述检测到的事实：同一度量词下数值不同，或需人工判断；不给结论。
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
  return material ? material.filename : (result.value?.filename_before ?? '')
})

async function ensureBlocks() {
  const missing = [materialIdBefore.value, materialIdAfter.value].filter((id) => id !== '' && !(id in blocksByMaterial.value))
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
        <h1 class="text-3xl font-semibold tracking-tight">修改前后少了什么问题</h1>
        <p class="mt-2 text-sm text-slate-400">看审查发现哪些已解决、哪些还在、哪些是新的。</p>
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
        <p class="text-sm text-slate-300">至少需要两份已保存的材料才能看修改前后的变化。</p>
        <UButton class="mt-4" size="sm" to="/materials/new" icon="i-lucide-plus">添加材料</UButton>
      </div>
      <div v-else>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="text-xs text-slate-400">
            修改前
            <select
              v-model="materialIdBefore"
              aria-label="修改前材料"
              class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            >
              <option value="">请选择材料</option>
              <option v-for="item in materials" :key="item.id" :value="item.id">{{ item.filename }}</option>
            </select>
          </label>
          <label class="text-xs text-slate-400">
            修改后
            <select
              v-model="materialIdAfter"
              aria-label="修改后材料"
              class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            >
              <option value="">请选择材料</option>
              <option v-for="item in materials" :key="item.id" :value="item.id">{{ item.filename }}</option>
            </select>
          </label>
        </div>
        <p class="mt-3 text-xs text-slate-500">只对照选中的两份版本；点引用可回看原文。</p>
        <div class="mt-4 flex flex-wrap items-center gap-3">
          <UButton icon="i-lucide-git-compare" :loading="diffing" :disabled="!canDiff" @click="compare">
            {{ diffing ? '对照中…' : '比较修改效果' }}
          </UButton>
          <span v-if="sameSelection" class="text-xs text-amber-300">不能对照同一份材料，请选择两份不同的材料</span>
        </div>
        <p v-if="diffError" class="mt-3 text-sm text-red-400" role="alert">{{ diffError }}</p>
      </div>
    </UCard>

    <!-- 变化结果：先给两个大数字（修改前 N 个待处理 → 修改后 M 个待处理），再按时间线摊开三组。 -->
    <section v-if="result" class="mt-6">
      <div class="rounded-xl border border-slate-800 bg-slate-900/40 px-6 py-5">
        <div class="flex flex-wrap items-center gap-x-8 gap-y-3">
          <div>
            <p class="text-xs text-slate-400">修改前</p>
            <p class="mt-1 flex items-baseline gap-1.5">
              <span class="text-4xl font-semibold leading-none tracking-tight text-slate-100">{{ beforeCount }}</span>
              <span class="text-xs text-slate-500">个待处理</span>
            </p>
          </div>
          <span class="text-2xl text-slate-600" aria-hidden="true">→</span>
          <div>
            <p class="text-xs text-slate-400">修改后</p>
            <p class="mt-1 flex items-baseline gap-1.5">
              <span
                class="text-4xl font-semibold leading-none tracking-tight"
                :class="afterCount < beforeCount ? 'text-emerald-300' : afterCount > beforeCount ? 'text-rose-300' : 'text-slate-100'"
              >{{ afterCount }}</span>
              <span class="text-xs text-slate-500">个待处理</span>
            </p>
          </div>
          <p class="ml-auto text-xs text-slate-500">{{ result.filename_before }} → {{ result.filename_after }}</p>
        </div>
        <p v-if="emptyResult" class="mt-3 text-sm text-slate-400">
          空结果合法，只说明这两份版本之间没有可对照的数值一致性差异。
        </p>
      </div>

      <!-- 变化时间线：已解决 → 仍存在 → 新增；每组一个大数字，空组也渲染（合法结果）。 -->
      <div class="relative mt-6 pl-10">
        <ol class="space-y-6">
          <li v-for="(group, index) in groups" :key="group.key" class="relative">
            <!-- 连线从本组圆点中心连到下一组圆点中心；最后一组不画，线止于最后一个节点。 -->
            <span
              v-if="index < groups.length - 1"
              class="absolute -left-[33px] top-[14px] h-[calc(100%_+_1.5rem)] w-[2px] bg-slate-800"
              aria-hidden="true"
            ></span>
            <span
              class="absolute -left-10 top-1.5 h-4 w-4 rounded-full border-2"
              :class="toneDot[group.tone]"
              aria-hidden="true"
            ></span>
            <div class="rounded-xl border bg-slate-900/30 p-4" :class="toneCard[group.tone]">
              <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h3 class="text-base font-semibold text-slate-100">{{ group.title }}</h3>
                <span class="text-3xl font-semibold leading-none tracking-tight" :class="toneCount[group.tone]">{{ group.findings.length }}</span>
                <span class="text-xs text-slate-500">条</span>
                <span class="ml-auto text-xs text-slate-500">{{ group.hint }}</span>
              </div>
              <p v-if="group.findings.length === 0" class="mt-2 text-xs text-slate-500">本组为空，这是合法结果。</p>
              <ul v-else class="mt-3 space-y-2">
                <li
                  v-for="finding in group.findings"
                  :key="`${finding.kind}:${finding.measure}:${finding.citations[0].block_id}:${finding.citations[0].start}`"
                  class="rounded-md border border-slate-800 bg-slate-900/40 p-3"
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
            </div>
          </li>
        </ol>
      </div>
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
