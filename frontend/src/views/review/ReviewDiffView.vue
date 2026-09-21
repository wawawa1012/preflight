<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Block, ConsistencyFinding, MaterialSummary } from '../../types/contracts'
import { reviewContextKey } from './reviewContext'
import { useSessionStore, type ReaderTarget } from '../../stores/session'
import EvidenceDrawer from '../../components/EvidenceDrawer.vue'
import EmptyState from '../../components/review/EmptyState.vue'
import { locatorLabel } from '../../utils/locatorLabel'
import { materialIdentity, identityLine } from '../../utils/materialIdentity'

// 修改效果：在本次审查的成员里选「修改前 / 修改后」两份材料，看一致性待核对项的变化。
// 快照 key = `${reviewId}:diff`；从 reader 返回或切页回来时恢复选择与结果。
// 恢复等 review.id 就绪（watch immediate）再执行，避免异步加载期间用空 reviewId 恢复/保存。
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
interface DiffSnapshot {
  materialIdBefore: string
  materialIdAfter: string
  result: DiffResponse | null
}

const context = inject(reviewContextKey)
if (!context) throw new Error('ReviewDiffView 必须在 ReviewWorkspaceView 内使用')
const { review } = context

const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const reviewId = computed(() => review.value?.id ?? '')
const reviewTitle = computed(() => review.value?.title ?? '')
const members = computed(() => review.value?.materials ?? [])
const basePath = computed(() => `/reviews/${reviewId.value}`)
const snapshotKey = computed(() => `${reviewId.value}:diff`)

const library = ref<MaterialSummary[]>([])
const loading = ref(true)
const loadError = ref('')

const materialIdBefore = ref('')
const materialIdAfter = ref('')

const diffing = ref(false)
const diffError = ref('')
const result = ref<DiffResponse | null>(null)

function labelOf(materialId: string) {
  return members.value.find((member) => member.material_id === materialId)?.label ?? filenameOf(materialId)
}

function filenameOf(materialId: string) {
  return library.value.find((item) => item.id === materialId)?.filename ?? '未知材料'
}

// 版本标题的身份去重：label == filename 只显示一次。
function sideIdentity(materialId: string) {
  return materialIdentity(labelOf(materialId), filenameOf(materialId))
}

// 恢复/保存都等 review.id 就绪：review 由 inject 异步加载，setup 时可能为空，
// 用 watch(review.id, ..., { immediate: true }) 在 id 到达后恢复，避免空 reviewId key 恢复 miss。
let restoredReviewId = ''

watch(
  () => review.value?.id,
  (id) => {
    if (!id || id === restoredReviewId) return
    restoredReviewId = id
    // 先重置到默认，再恢复该 review 的快照；只接受仍在成员里的 id，否则回落到默认前两名。
    materialIdBefore.value = ''
    materialIdAfter.value = ''
    result.value = null
    const restored = session.restoreCapability<DiffSnapshot>(`${id}:diff`)
    const memberIds = new Set(members.value.map((member) => member.material_id))
    if (restored && memberIds.has(restored.materialIdBefore) && memberIds.has(restored.materialIdAfter)) {
      materialIdBefore.value = restored.materialIdBefore
      materialIdAfter.value = restored.materialIdAfter
      result.value = restored.result
    } else {
      materialIdBefore.value = members.value[0]?.material_id ?? ''
      materialIdAfter.value = members.value[1]?.material_id ?? ''
    }
  },
  { immediate: true },
)

watch([materialIdBefore, materialIdAfter, result], () => {
  if (reviewId.value === '') return
  session.saveCapability(snapshotKey.value, {
    materialIdBefore: materialIdBefore.value,
    materialIdAfter: materialIdAfter.value,
    result: result.value,
  } satisfies DiffSnapshot)
})

const sameSelection = computed(() => materialIdBefore.value !== '' && materialIdBefore.value === materialIdAfter.value)
const canDiff = computed(() => materialIdBefore.value !== '' && materialIdAfter.value !== '')

const beforeCount = computed(() => (result.value ? result.value.resolved.length + result.value.unchanged.length : 0))
const afterCount = computed(() => (result.value ? result.value.unchanged.length + result.value.new.length : 0))

const emptyResult = computed(
  () =>
    result.value !== null &&
    result.value.resolved.length === 0 &&
    result.value.unchanged.length === 0 &&
    result.value.new.length === 0,
)

const deltaSentence = computed(() => {
  if (!result.value || emptyResult.value) return ''
  const before = beforeCount.value
  const after = afterCount.value
  if (after < before) return `比修改前少了 ${before - after} 个待核对项。`
  if (after > before) return `比修改前多了 ${after - before} 个待核对项，请重点查看「新增」。`
  return '待核对项数量没有变化。'
})

const groups = computed(() =>
  result.value === null
    ? []
    : [
        { key: 'resolved', title: '本次未再检出', tone: 'emerald', hint: '修改前有、这次修改后不再出现。', findings: result.value.resolved },
        { key: 'unchanged', title: '仍存在', tone: 'amber', hint: '修改前后都在，还没有消失。', findings: result.value.unchanged },
        { key: 'new', title: '新增', tone: 'rose', hint: '修改前没有、修改后新出现。', findings: result.value.new },
      ],
)

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
  emerald: 'bg-emerald-950/30',
  amber: 'bg-amber-950/30',
  rose: 'bg-rose-950/30',
}

const blocksByMaterial = ref<Record<string, Block[]>>({})
const blocksUnavailable = ref(false)

const drawerOpen = ref(false)
const drawerBlockId = ref('')
const highlight = ref<{ line_number: number; start: number; end: number } | null>(null)

async function loadLibrary() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetch('/api/v1/materials')
    const body = await response.json().catch(() => null)
    if (!response.ok) throw new Error(body?.message ?? `HTTP ${response.status}`)
    library.value = Array.isArray(body) ? (body as MaterialSummary[]) : []
  } catch (cause) {
    loadError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function diff() {
  if (diffing.value || !canDiff.value) return
  if (sameSelection.value) {
    result.value = null
    diffError.value = '两份材料不能相同，请选择两份不同的材料'
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
    if (!response.ok) throw new Error(body?.message ?? `HTTP ${response.status}`)
    result.value = body as DiffResponse
  } catch (cause) {
    result.value = null
    diffError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    diffing.value = false
  }
}

function findingLabel(kind: ConsistencyFinding['kind']) {
  return { numeric_inconsistency: '数值不一致', needs_review: '待人工判断' }[kind]
}

const allBlocks = computed(() => Object.values(blocksByMaterial.value).flat())

function blockById(blockId: string): Block | null {
  return allBlocks.value.find((block) => block.id === blockId) ?? null
}

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
  return materialId ? filenameOf(materialId) : (result.value?.filename_before ?? '')
})

async function ensureBlocks() {
  // result 的 citations 冻结于 result.material_id_*；下拉可能已切换，必须以结果里的 id 为准。
  const ids = result.value
    ? [result.value.material_id_before, result.value.material_id_after]
    : [materialIdBefore.value, materialIdAfter.value]
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
  await ensureBlocks()
}

async function openInReader(finding: ConsistencyFinding, citation: ConsistencyFinding['citations'][number]) {
  const compared = result.value
  if (!compared) return
  await ensureBlocks()
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
    origin: { fullPath: route.fullPath, label: '修改效果' },
  })
  await router.push(
    `/reviews/${reviewId.value}/reader/${clickedBlock.document_id}?b=${citation.block_id}&s=${citation.start}&e=${citation.end}`,
  )
}

loadLibrary()
</script>

<template>
  <div class="space-y-8">
    <section>
      <h2 class="text-sm font-medium tracking-wide text-slate-200">修改效果</h2>
      <p class="mt-1 text-xs text-slate-500">比较本次检测结果：未再检出不代表风险已解决，删除陈述也可能使问题消失。每份材料最多检查前 20 条信号。</p>

      <EmptyState
        v-if="members.length < 2"
        class="mt-4 rounded-xl bg-slate-950/40"
        title="本次审查的材料不足两份"
        hint="先在材料页加入至少两份材料，再看修改前后的变化。"
      >
        <UButton :to="`${basePath}/members`" icon="i-lucide-files">管理材料</UButton>
      </EmptyState>

      <p v-else-if="loading" class="mt-4 text-sm text-slate-400">正在读取材料库…</p>

      <div v-else-if="loadError" class="mt-4 rounded-xl bg-slate-950/40 px-5 py-4">
        <p class="text-sm text-red-400" role="alert">无法加载材料库：{{ loadError }}</p>
        <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="loadLibrary">重试</UButton>
      </div>

      <div v-else class="mt-4 rounded-xl bg-slate-950/40 px-5 py-4">
        <div class="flex flex-wrap items-end gap-x-5 gap-y-3">
          <label class="text-xs text-slate-500">
            修改前
            <select
              v-model="materialIdBefore"
              aria-label="修改前材料"
              class="mt-1 block w-56 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            >
              <option value="">请选择材料</option>
              <option v-for="member in members" :key="member.material_id" :value="member.material_id">
                {{ identityLine(member.label, filenameOf(member.material_id)) }}
              </option>
            </select>
          </label>
          <span class="pb-2.5 text-lg text-slate-600" aria-hidden="true">→</span>
          <label class="text-xs text-slate-500">
            修改后
            <select
              v-model="materialIdAfter"
              aria-label="修改后材料"
              class="mt-1 block w-56 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            >
              <option value="">请选择材料</option>
              <option v-for="member in members" :key="member.material_id" :value="member.material_id">
                {{ identityLine(member.label, filenameOf(member.material_id)) }}
              </option>
            </select>
          </label>
          <UButton class="mb-0.5" icon="i-lucide-arrow-right-left" :loading="diffing" :disabled="!canDiff" @click="diff">
            {{ diffing ? '比较中…' : '比较修改效果' }}
          </UButton>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-3">
          <span v-if="sameSelection" class="text-xs text-amber-300">两份材料不能相同，请选择两份不同的材料</span>
          <span v-else class="text-xs text-slate-500">只比较你选中的这两份材料；点结果里的引用可回看原文。</span>
        </div>
        <p v-if="diffError" class="mt-3 text-sm text-red-400" role="alert">{{ diffError }}</p>
      </div>
    </section>

    <section v-if="result && members.length >= 2">
      <div class="rounded-xl bg-slate-950/40 px-6 py-6">
        <div class="flex flex-wrap items-end gap-x-10 gap-y-4">
          <div>
            <p class="text-xs text-slate-500">修改前</p>
            <p class="mt-1.5 flex items-baseline gap-1.5">
              <span class="text-5xl font-semibold leading-none tracking-tight text-slate-100">{{ beforeCount }}</span>
              <span class="text-sm text-slate-500">个一致性待核对项</span>
            </p>
          </div>
          <span class="pb-1.5 text-3xl leading-none text-slate-600" aria-hidden="true">→</span>
          <div>
            <p class="text-xs text-slate-500">修改后</p>
            <p class="mt-1.5 flex items-baseline gap-1.5">
              <span
                class="text-5xl font-semibold leading-none tracking-tight"
                :class="afterCount < beforeCount ? 'text-emerald-300' : afterCount > beforeCount ? 'text-rose-300' : 'text-slate-100'"
              >{{ afterCount }}</span>
              <span class="text-sm text-slate-500">个一致性待核对项</span>
            </p>
          </div>
          <p v-if="deltaSentence" class="ml-auto max-w-xs pb-1.5 text-sm text-slate-300">{{ deltaSentence }}</p>
        </div>
        <p class="mt-4 text-xs text-slate-500">{{ sideIdentity(result.material_id_before).primary }} → {{ sideIdentity(result.material_id_after).primary }}</p>
        <p v-if="sideIdentity(result.material_id_before).secondary || sideIdentity(result.material_id_after).secondary" class="font-mono text-[11px] text-slate-600">{{ result.filename_before }} → {{ result.filename_after }}</p>
      </div>

      <EmptyState
        v-if="emptyResult"
        class="mt-2"
        title="这两份材料之间没有发现一致性待核对项的变化。"
        :hint="`比较的是 ${labelOf(result.material_id_before)} 和 ${labelOf(result.material_id_after)}；换一组版本再看。`"
      />

      <div v-else class="relative mt-6 pl-10">
        <ol class="space-y-6">
          <li v-for="(group, index) in groups" :key="group.key" class="relative">
            <span
              v-if="index < groups.length - 1"
              class="absolute -left-[33px] top-[14px] h-[calc(100%_+_1.5rem)] w-[2px] bg-slate-800"
              aria-hidden="true"
            ></span>
            <span class="absolute -left-10 top-1.5 h-4 w-4 rounded-full border-2" :class="toneDot[group.tone]" aria-hidden="true"></span>
            <div class="rounded-xl p-4" :class="toneCard[group.tone]">
              <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h3 class="text-base font-semibold text-slate-100">{{ group.title }}</h3>
                <span class="text-2xl font-semibold leading-none tracking-tight" :class="toneCount[group.tone]">{{ group.findings.length }}</span>
                <span class="text-xs text-slate-500">条</span>
                <span class="ml-auto text-xs text-slate-500">{{ group.hint }}</span>
              </div>
              <p v-if="group.findings.length === 0" class="mt-2 text-xs text-slate-500">这一组目前没有条目。</p>
              <!-- 显示单位是 Finding/metric：先说清哪条问题、两版各自的数值说法；引用折叠为二级。 -->
              <ul v-else class="mt-3 divide-y divide-slate-800/70">
                <li
                  v-for="finding in group.findings"
                  :key="`${finding.kind}:${finding.measure}:${finding.citations[0].block_id}:${finding.citations[0].start}`"
                  class="py-3"
                >
                  <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span class="text-sm font-medium text-slate-200">{{ finding.measure || '同一指标' }}</span>
                    <UBadge :color="finding.kind === 'numeric_inconsistency' ? 'warning' : 'neutral'" variant="subtle" size="sm">
                      {{ findingLabel(finding.kind) }}
                    </UBadge>
                  </div>
                  <p v-if="group.key === 'unchanged'" class="mt-1.5 text-sm">
                    <span class="text-slate-500">修改前后均存在：</span>
                    <span class="font-mono text-amber-300/90">{{ finding.values.join(' / ') }}</span>
                  </p>
                  <template v-else>
                    <p class="mt-1.5 text-sm">
                      <span class="text-slate-500">{{ sideIdentity(result!.material_id_before).primary }}：</span>
                      <span v-if="group.key === 'resolved'" class="font-mono text-amber-300/90">{{ finding.values.join(' / ') }}</span>
                      <span v-else class="text-slate-500">未出现该问题</span>
                    </p>
                    <p class="mt-0.5 text-sm">
                      <span class="text-slate-500">{{ sideIdentity(result!.material_id_after).primary }}：</span>
                      <span v-if="group.key === 'resolved'" class="text-emerald-300/90">本次未再检出</span>
                      <span v-else class="font-mono text-rose-300/90">{{ finding.values.join(' / ') }}</span>
                    </p>
                  </template>
                  <details class="mt-2">
                    <summary class="cursor-pointer select-none text-xs text-slate-500 transition hover:text-slate-300">
                      原文引用（{{ finding.citations.length }} 处）
                    </summary>
                    <ul class="mt-2 space-y-1">
                      <li v-for="citation in finding.citations" :key="`${citation.block_id}:${citation.start}`">
                        <div class="flex flex-wrap items-baseline gap-x-2 rounded-md px-2 py-1.5 transition hover:bg-slate-800/60">
                          <button type="button" class="group flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 text-left" @click="openCitation(citation)">
                            <span class="text-sm text-slate-300">“{{ citation.quote }}”</span>
                            <span class="font-mono text-xs text-slate-500">{{ rowLocation(citation.block_id, citation.line_number) }}</span>
                            <span class="ml-auto text-[11px] text-slate-600 transition group-hover:text-violet-300">查看原文</span>
                          </button>
                          <button type="button" class="shrink-0 text-[11px] text-slate-500 transition hover:text-violet-300" @click="openInReader(finding, citation)">在材料中打开</button>
                        </div>
                      </li>
                    </ul>
                  </details>
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
  </div>
</template>
