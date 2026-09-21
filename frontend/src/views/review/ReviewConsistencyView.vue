<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Block, ConsistencyFinding, CrossCompareRequest, CrossCompareResponse, MaterialSummary } from '../../types/contracts'
import { reviewContextKey } from './reviewContext'
import { useSessionStore, type ReaderTarget } from '../../stores/session'
import EvidenceDrawer from '../../components/EvidenceDrawer.vue'
import EmptyState from '../../components/review/EmptyState.vue'
import { locatorLabel } from '../../utils/locatorLabel'
import { materialIdentity, identityLine } from '../../utils/materialIdentity'
import { createRequestScope } from '../../utils/requestScope'

// 一致性：在本次审查的成员里显式选两份材料做数值对照。打开只读材料库；POST 只由按钮触发。
// 快照 key = `${reviewId}:consistency`；从 reader 返回或切页回来时恢复选择与结果。
// 恢复等 review.id 就绪（watch immediate）再执行，避免异步加载期间用空 reviewId 恢复/保存。
interface ConsistencySnapshot {
  materialIdA: string
  materialIdB: string
  result: CrossCompareResponse | null
}

const context = inject(reviewContextKey)
if (!context) throw new Error('ReviewConsistencyView 必须在 ReviewWorkspaceView 内使用')
const { review } = context

const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const reviewId = computed(() => review.value?.id ?? '')
const reviewTitle = computed(() => review.value?.title ?? '')
const members = computed(() => review.value?.materials ?? [])
const basePath = computed(() => `/reviews/${reviewId.value}`)
const snapshotKey = computed(() => `${reviewId.value}:consistency`)

const library = ref<MaterialSummary[]>([])
const loading = ref(true)
const loadError = ref('')

const materialIdA = ref('')
const materialIdB = ref('')

const checking = ref(false)
const compareError = ref('')
const result = ref<CrossCompareResponse | null>(null)

// 材料身份：label 来自成员关系，filename 来自材料库。
function labelOf(materialId: string) {
  return members.value.find((member) => member.material_id === materialId)?.label ?? filenameOf(materialId)
}

function filenameOf(materialId: string) {
  return library.value.find((item) => item.id === materialId)?.filename ?? '未知材料'
}

// 侧标题的身份去重：label == filename 只显示一次。
function sideIdentity(materialId: string) {
  return materialIdentity(labelOf(materialId), filenameOf(materialId))
}

// 恢复/保存都等 review.id 就绪：review 由 inject 异步加载，setup 时可能为空，
// 用 watch(review.id, ..., { immediate: true }) 在 id 到达后恢复，避免空 reviewId key 恢复 miss。
let restoredReviewId = ''
// 三个独立 scope：比较动作、材料库加载、blocks 拉取，互不作废。
const compareScope = createRequestScope()
const loadScope = createRequestScope()
const blocksScope = createRequestScope()

watch(
  () => review.value?.id,
  (id) => {
    if (!id || id === restoredReviewId) return
    restoredReviewId = id
    // 切换 Review：作废在飞比较/加载/blocks 响应，防止旧 Review 的结果落进新上下文。
    compareScope.invalidate()
    blocksScope.invalidate()
    // 发起时 scope 已作废，其 finally 复位会被拒；这里把 loading 复位回新上下文。
    checking.value = false
    // 先重置到默认，再恢复该 review 的快照；只接受仍在成员里的 id，否则回落到默认前两名。
    materialIdA.value = ''
    materialIdB.value = ''
    result.value = null
    const restored = session.restoreCapability<ConsistencySnapshot>(`${id}:consistency`)
    const memberIds = new Set(members.value.map((member) => member.material_id))
    if (restored && memberIds.has(restored.materialIdA) && memberIds.has(restored.materialIdB)) {
      materialIdA.value = restored.materialIdA
      materialIdB.value = restored.materialIdB
      result.value = restored.result
    } else {
      materialIdA.value = members.value[0]?.material_id ?? ''
      materialIdB.value = members.value[1]?.material_id ?? ''
    }
  },
  { immediate: true },
)

watch([materialIdA, materialIdB, result], () => {
  if (reviewId.value === '') return
  session.saveCapability(snapshotKey.value, {
    materialIdA: materialIdA.value,
    materialIdB: materialIdB.value,
    result: result.value,
  } satisfies ConsistencySnapshot)
})

const sameSelection = computed(() => materialIdA.value !== '' && materialIdA.value === materialIdB.value)
const canCompare = computed(() => materialIdA.value !== '' && materialIdB.value !== '')
const emptyResult = computed(() => result.value !== null && result.value.findings.length === 0)

const blocksByMaterial = ref<Record<string, Block[]>>({})
const blocksUnavailable = ref(false)

const drawerOpen = ref(false)
const drawerBlockId = ref('')
const highlight = ref<{ start: number; end: number } | null>(null)

async function loadLibrary() {
  const ticket = loadScope.begin({ reviewId: reviewId.value, purpose: 'load' as const })
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetch('/api/v1/materials')
    const body = await response.json().catch(() => null)
    if (!response.ok) throw new Error(body?.message ?? `HTTP ${response.status}`)
    ticket.commit(() => {
      library.value = Array.isArray(body) ? (body as MaterialSummary[]) : []
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

async function compare() {
  if (checking.value || !canCompare.value) return
  if (sameSelection.value) {
    result.value = null
    compareError.value = '两份材料不能相同，请选择两份不同的材料'
    return
  }
  // request scope：运行期间切换 Review 或再次运行时，迟到响应直接丢弃。
  const ticket = compareScope.begin({ reviewId: reviewId.value, purpose: 'compare' as const })
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
    if (!response.ok) throw new Error(body?.message ?? `HTTP ${response.status}`)
    const compared = body as CrossCompareResponse
    await ensureBlocks([compared.material_id_a, compared.material_id_b])
    ticket.commit(() => {
      result.value = compared
    })
  } catch (cause) {
    ticket.commit(() => {
      result.value = null
      compareError.value = cause instanceof Error ? cause.message : '未知错误'
    })
  } finally {
    ticket.commit(() => {
      checking.value = false
    })
  }
}

function findingLabel(kind: ConsistencyFinding['kind']) {
  return { numeric_inconsistency: '数值集合不同', needs_review: '待人工判断' }[kind]
}

function findingHeadline(finding: ConsistencyFinding): string {
  const subject = finding.measure ? `「${finding.measure}」` : '同一指标'
  if (finding.kind === 'numeric_inconsistency') return `两份材料在已提取范围内的${subject}数值集合不同。`
  return `两份材料都提到${subject}，需要人工判断说法是否一致。`
}

const allBlocks = computed(() => Object.values(blocksByMaterial.value).flat())

function blockById(blockId: string): Block | null {
  return allBlocks.value.find((block) => block.id === blockId) ?? null
}

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

function unsidedCitations(finding: ConsistencyFinding) {
  return finding.citations.filter((citation) => citationSide(citation) === null)
}

// 每侧的全部不同说法（value+unit，按首次出现去重）：
// 主视觉必须展示 variants（如 88% / 93%），绝不取第一条 citation 冒充整侧结论。
function sideVariants(finding: ConsistencyFinding, side: 'a' | 'b'): string[] {
  const seen = new Set<string>()
  const variants: string[] = []
  for (const citation of sideCitations(finding, side)) {
    const display = citation.unit ? `${citation.value}${citation.unit}` : citation.value
    if (!display || seen.has(display)) continue
    seen.add(display)
    variants.push(display)
  }
  return variants
}

// 两侧展示字符串的集合相同时，标题仍写「不一致」会误导；给出诚实说明。
function sameVariantSets(finding: ConsistencyFinding): boolean {
  const a = sideVariants(finding, 'a')
  const b = sideVariants(finding, 'b')
  if (a.length !== b.length) return false
  const other = new Set(b)
  return a.every((variant) => other.has(variant))
}

// 位置以引用自带的 Locator 为准（kind 决定行 / 段 / 表格单元格）；
// 旧快照无 locator 时才退回 line_number，且为 null 时不显示。
function rowLocation(citation: ConsistencyFinding['citations'][number]): string {
  if (citation.locator) return locatorLabel(citation.locator)
  if (typeof citation.line_number === 'number') return locatorLabel({ kind: 'line', index: citation.line_number })
  return ''
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
  return materialId ? filenameOf(materialId) : (result.value?.filename_a ?? '')
})

async function ensureBlocks(ids: string[]) {
  const missing = ids.filter((id) => id !== '' && !(id in blocksByMaterial.value))
  if (missing.length === 0 || blocksUnavailable.value) return
  const ticket = blocksScope.begin({ reviewId: reviewId.value, purpose: 'blocks' as const })
  for (const id of missing) {
    try {
      const response = await fetch(`/api/v1/materials/${encodeURIComponent(id)}`)
      const body = await response.json().catch(() => null)
      if (!response.ok) {
        ticket.commit(() => {
          blocksUnavailable.value = true
        })
        return
      }
      ticket.commit(() => {
        blocksByMaterial.value = {
          ...blocksByMaterial.value,
          [id]: Array.isArray(body?.blocks) ? (body.blocks as Block[]) : [],
        }
      })
    } catch {
      ticket.commit(() => {
        blocksUnavailable.value = true
      })
      return
    }
  }
}

async function openCitation(citation: ConsistencyFinding['citations'][number]) {
  highlight.value = { start: citation.start, end: citation.end }
  drawerBlockId.value = citation.block_id
  drawerOpen.value = true
  await ensureBlocks(result.value ? [result.value.material_id_a, result.value.material_id_b] : [])
}

// 「在材料中打开」：把该 finding 的全部引用映射成 ReaderTarget，materialId 取 block.document_id（与 drawer 判侧同源）。
async function openInReader(finding: ConsistencyFinding, citation: ConsistencyFinding['citations'][number]) {
  const compared = result.value
  if (!compared) return
  await ensureBlocks([compared.material_id_a, compared.material_id_b])
  const clickedBlock = blockById(citation.block_id)
  if (!clickedBlock) {
    blocksUnavailable.value = true
    return
  }
  const targets = finding.citations
    .map((item): ReaderTarget | null => {
      const block = blockById(item.block_id)
      return block
        ? { materialId: block.document_id, blockId: item.block_id, start: item.start, end: item.end, quote: item.quote }
        : null
    })
    .filter((target): target is ReaderTarget => target !== null)
  const index = targets.findIndex((target) => target.blockId === citation.block_id && target.start === citation.start)
  session.openReader({
    reviewId: reviewId.value,
    reviewTitle: reviewTitle.value,
    materialId: clickedBlock.document_id,
    materialLabel: labelOf(clickedBlock.document_id),
    materialFilename: filenameOf(clickedBlock.document_id),
    targets,
    index: index < 0 ? 0 : index,
    origin: { fullPath: route.fullPath, label: '一致性检查' },
  })
  await router.push(
    `/reviews/${reviewId.value}/reader/${clickedBlock.document_id}?b=${citation.block_id}&s=${citation.start}&e=${citation.end}`,
  )
}

onBeforeUnmount(() => {
  compareScope.invalidate()
  loadScope.invalidate()
  blocksScope.invalidate()
})

loadLibrary()
</script>

<template>
  <div class="space-y-8">
    <section>
      <h2 class="text-sm font-medium tracking-wide text-slate-200">一致性检查</h2>
      <p class="mt-1 text-xs text-slate-500">检查本次审查中两份材料是否对同一指标使用了不同数值。</p>

      <EmptyState
        v-if="members.length < 2"
        class="mt-4 rounded-xl bg-slate-950/40"
        title="本次审查的材料不足两份"
        hint="先在材料页加入至少两份材料，再回来做一致性检查。"
      >
        <UButton :to="`${basePath}/members`" icon="i-lucide-files">管理材料</UButton>
      </EmptyState>

      <p v-else-if="loading" class="mt-4 text-sm text-slate-400">正在读取材料库…</p>

      <div v-else-if="loadError" class="mt-4 rounded-xl bg-slate-950/40 px-5 py-4">
        <p class="text-sm text-red-400" role="alert">无法加载材料库：{{ loadError }}</p>
        <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="loadLibrary">重试</UButton>
      </div>

      <div v-else class="mt-4 rounded-xl bg-slate-950/40 px-5 py-4">
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="text-xs text-slate-500">
            主材料
            <select
              v-model="materialIdA"
              aria-label="主材料"
              class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            >
              <option value="">请选择材料</option>
              <option v-for="member in members" :key="member.material_id" :value="member.material_id">
                {{ identityLine(member.label, filenameOf(member.material_id)) }}
              </option>
            </select>
          </label>
          <label class="text-xs text-slate-500">
            对照材料
            <select
              v-model="materialIdB"
              aria-label="对照材料"
              class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            >
              <option value="">请选择材料</option>
              <option v-for="member in members" :key="member.material_id" :value="member.material_id">
                {{ identityLine(member.label, filenameOf(member.material_id)) }}
              </option>
            </select>
          </label>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-3">
          <UButton icon="i-lucide-git-compare" :loading="checking" :disabled="!canCompare" @click="compare">
            {{ checking ? '检查中…' : '检查一致性' }}
          </UButton>
          <span v-if="sameSelection" class="text-xs text-amber-300">两份材料不能相同，请选择两份不同的材料</span>
          <span v-else class="text-xs text-slate-500">只检查你选中的这两份材料；点结果里的引用可回看原文。</span>
        </div>
        <p v-if="compareError" class="mt-3 text-sm text-red-400" role="alert">{{ compareError }}</p>
      </div>
    </section>

    <section v-if="result && members.length >= 2">
      <EmptyState
        v-if="emptyResult"
        title="当前没有发现两份材料对同一指标使用不同数值。"
        :hint="`检查了 ${labelOf(result.material_id_a)} 和 ${labelOf(result.material_id_b)}；换个对照材料可以再查一次。`"
      />
      <template v-else>
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <h2 class="text-lg font-semibold text-slate-100">发现 {{ result.findings.length }} 处待核对项</h2>
          <span class="text-xs text-slate-500">{{ sideIdentity(result.material_id_a).primary }} · {{ sideIdentity(result.material_id_b).primary }}</span>
        </div>
        <p v-if="sideIdentity(result.material_id_a).secondary || sideIdentity(result.material_id_b).secondary" class="mt-1 font-mono text-[11px] text-slate-600">{{ result.filename_a }} · {{ result.filename_b }}</p>
        <p class="mt-1 text-xs text-slate-500">仅比较每份材料前 20 条关键陈述信号，不判断实验条件相同或任何一方正确。</p>

        <div class="mt-4 space-y-6">
          <article
            v-for="finding in result.findings"
            :key="`${finding.kind}:${finding.measure}:${finding.citations[0].block_id}:${finding.citations[0].start}`"
            class="rounded-xl bg-slate-950/40 p-5"
          >
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h3 class="text-base font-semibold text-slate-100">{{ finding.measure || '同一指标' }}</h3>
              <UBadge :color="finding.kind === 'numeric_inconsistency' ? 'warning' : 'neutral'" variant="subtle" size="sm">
                {{ findingLabel(finding.kind) }}
              </UBadge>
            </div>
            <p class="mt-1 text-sm text-slate-400">{{ findingHeadline(finding) }}</p>
            <p v-if="sameVariantSets(finding)" class="mt-1 text-xs text-slate-500">当前来源集合相同，请重新运行检查以更新结果。</p>

            <div class="relative mt-4 grid gap-x-10 gap-y-4 sm:grid-cols-2">
              <span class="absolute left-1/2 top-1/2 hidden -translate-x-1/2 -translate-y-1/2 font-mono text-xl text-slate-600 sm:block" aria-hidden="true">↔</span>
              <div>
                <p class="text-xs text-slate-500">主材料 · {{ sideIdentity(result.material_id_a).primary }}</p>
                <p v-if="sideIdentity(result.material_id_a).secondary" class="font-mono text-[10px] text-slate-600">{{ sideIdentity(result.material_id_a).secondary }}</p>
                <!-- 主视觉是这一侧的全部不同说法（variants），不是第一条引用的值。 -->
                <div v-if="sideVariants(finding, 'a').length > 0" class="mt-2">
                  <p class="font-mono text-2xl font-semibold leading-snug tracking-tight text-amber-300">{{ sideVariants(finding, 'a').join(' / ') }}</p>
                  <p v-if="sideVariants(finding, 'a').length > 1" class="mt-1 text-[11px] text-slate-500">这一侧有 {{ sideVariants(finding, 'a').length }} 种说法</p>
                </div>
                <p v-else-if="sideCitations(finding, 'a').length > 0" class="mt-2 text-sm leading-relaxed text-slate-300">“{{ sideCitations(finding, 'a')[0].quote }}”</p>
                <p v-else class="mt-2 text-sm text-slate-500">需人工核对</p>
                <ul class="mt-3 space-y-1">
                  <li v-for="citation in sideCitations(finding, 'a')" :key="`a:${citation.block_id}:${citation.start}`">
                    <div class="flex flex-wrap items-baseline gap-x-2 rounded-md px-2 py-1.5 transition hover:bg-slate-800/60">
                      <button type="button" class="group flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 text-left" @click="openCitation(citation)">
                        <span class="text-sm text-slate-300">“{{ citation.quote }}”</span>
                        <span class="font-mono text-xs text-slate-500">{{ rowLocation(citation) }}</span>
                        <span class="ml-auto text-[11px] text-slate-600 transition group-hover:text-violet-300">查看原文</span>
                      </button>
                      <button type="button" class="shrink-0 text-[11px] text-slate-500 transition hover:text-violet-300" @click="openInReader(finding, citation)">在材料中打开</button>
                    </div>
                  </li>
                </ul>
                <p v-if="sideCitations(finding, 'a').length === 0" class="mt-2 px-2 text-xs text-slate-600">这一侧没有对应的原文引用。</p>
              </div>
              <div>
                <p class="text-xs text-slate-500">对照材料 · {{ sideIdentity(result.material_id_b).primary }}</p>
                <p v-if="sideIdentity(result.material_id_b).secondary" class="font-mono text-[10px] text-slate-600">{{ sideIdentity(result.material_id_b).secondary }}</p>
                <div v-if="sideVariants(finding, 'b').length > 0" class="mt-2">
                  <p class="font-mono text-2xl font-semibold leading-snug tracking-tight text-amber-300">{{ sideVariants(finding, 'b').join(' / ') }}</p>
                  <p v-if="sideVariants(finding, 'b').length > 1" class="mt-1 text-[11px] text-slate-500">这一侧有 {{ sideVariants(finding, 'b').length }} 种说法</p>
                </div>
                <p v-else-if="sideCitations(finding, 'b').length > 0" class="mt-2 text-sm leading-relaxed text-slate-300">“{{ sideCitations(finding, 'b')[0].quote }}”</p>
                <p v-else class="mt-2 text-sm text-slate-500">需人工核对</p>
                <ul class="mt-3 space-y-1">
                  <li v-for="citation in sideCitations(finding, 'b')" :key="`b:${citation.block_id}:${citation.start}`">
                    <div class="flex flex-wrap items-baseline gap-x-2 rounded-md px-2 py-1.5 transition hover:bg-slate-800/60">
                      <button type="button" class="group flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 text-left" @click="openCitation(citation)">
                        <span class="text-sm text-slate-300">“{{ citation.quote }}”</span>
                        <span class="font-mono text-xs text-slate-500">{{ rowLocation(citation) }}</span>
                        <span class="ml-auto text-[11px] text-slate-600 transition group-hover:text-violet-300">查看原文</span>
                      </button>
                      <button type="button" class="shrink-0 text-[11px] text-slate-500 transition hover:text-violet-300" @click="openInReader(finding, citation)">在材料中打开</button>
                    </div>
                  </li>
                </ul>
                <p v-if="sideCitations(finding, 'b').length === 0" class="mt-2 px-2 text-xs text-slate-600">这一侧没有对应的原文引用。</p>
              </div>
            </div>

            <template v-if="unsidedCitations(finding).length > 0">
              <p class="mt-4 text-xs text-slate-600">以下引用暂无法确定所属材料，请人工核对。</p>
              <ul class="mt-1 space-y-1">
                <li v-for="citation in unsidedCitations(finding)" :key="`u:${citation.block_id}:${citation.start}`">
                  <div class="flex flex-wrap items-baseline gap-x-2 rounded-md px-2 py-1.5 transition hover:bg-slate-800/60">
                    <button type="button" class="group flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 text-left" @click="openCitation(citation)">
                      <span class="text-sm text-slate-300">“{{ citation.quote }}”</span>
                      <span class="font-mono text-xs text-slate-500">{{ rowLocation(citation) }}</span>
                      <span class="ml-auto text-[11px] text-slate-600 transition group-hover:text-violet-300">查看原文</span>
                    </button>
                    <button type="button" class="shrink-0 text-[11px] text-slate-500 transition hover:text-violet-300" @click="openInReader(finding, citation)">在材料中打开</button>
                  </div>
                </li>
              </ul>
            </template>

            <p class="mt-4 text-xs text-slate-500">{{ finding.explanation }}</p>
          </article>
        </div>
      </template>
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
  </div>
</template>
