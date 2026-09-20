<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Block, MaterialSummary } from '../../types/contracts'
import { reviewContextKey } from './reviewContext'
import { useSessionStore, type ReaderTarget } from '../../stores/session'
import EvidenceDrawer from '../../components/EvidenceDrawer.vue'
import EmptyState from '../../components/review/EmptyState.vue'
import { locatorLabel } from '../../utils/locatorLabel'
import { identityLine } from '../../utils/materialIdentity'

// 质询：对本次审查里选中的一份材料，生成可回到原文的针对性追问。打开只读材料库；POST 只由按钮触发。
// 快照 key = `${reviewId}:grill`；从 reader 返回或切页回来时恢复选择与追问。
// 恢复等 review.id 就绪（watch immediate）再执行，避免异步加载期间用空 reviewId 恢复/保存。
interface GrillQuestion {
  prompt: string
  quote: string
  block_id: string
  start: number
  end: number
}
interface GrillSnapshot {
  materialId: string
  questions: GrillQuestion[]
  generated: boolean
}

const context = inject(reviewContextKey)
if (!context) throw new Error('ReviewGrillView 必须在 ReviewWorkspaceView 内使用')
const { review } = context

const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const reviewId = computed(() => review.value?.id ?? '')
const reviewTitle = computed(() => review.value?.title ?? '')
const members = computed(() => review.value?.materials ?? [])
const basePath = computed(() => `/reviews/${reviewId.value}`)
const snapshotKey = computed(() => `${reviewId.value}:grill`)

const library = ref<MaterialSummary[]>([])
const loading = ref(true)
const loadError = ref('')

const materialId = ref('')

const generating = ref(false)
const error = ref<{ message: string; detail: string } | null>(null)
const questions = ref<GrillQuestion[]>([])
const generated = ref(false)
const emptyResult = computed(() => generated.value && questions.value.length === 0)

function labelOf(id: string) {
  return members.value.find((member) => member.material_id === id)?.label ?? filenameOf(id)
}

function filenameOf(id: string) {
  return library.value.find((item) => item.id === id)?.filename ?? '未知材料'
}

const blocks = ref<Block[]>([])
const blocksUnavailable = ref(false)

// 恢复/保存都等 review.id 就绪：review 由 inject 异步加载，setup 时可能为空，
// 用 watch(review.id, ..., { immediate: true }) 在 id 到达后恢复，避免空 reviewId key 恢复 miss。
let restoredReviewId = ''
// 恢复赋值时置位，让下面的 watch(materialId) 跳过清空；一次性，由该 watch 消费。
let skipMaterialClear = false

watch(
  () => review.value?.id,
  (id) => {
    if (!id || id === restoredReviewId) return
    restoredReviewId = id
    // 先重置到默认，再恢复该 review 的快照；只接受仍在成员里的 id。
    const previousMaterialId = materialId.value
    skipMaterialClear = false
    materialId.value = ''
    questions.value = []
    generated.value = false
    error.value = null
    blocks.value = []
    blocksUnavailable.value = false
    const restored = session.restoreCapability<GrillSnapshot>(`${id}:grill`)
    const memberIds = new Set(members.value.map((member) => member.material_id))
    if (restored && memberIds.has(restored.materialId)) {
      // 仅当 materialId 实际变化时置位，避免 net 无变化时标志残留。
      skipMaterialClear = previousMaterialId !== restored.materialId
      materialId.value = restored.materialId
      questions.value = restored.questions
      generated.value = restored.generated
    } else {
      materialId.value = members.value[0]?.material_id ?? ''
    }
  },
  { immediate: true },
)

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

function failureText(code: string, message: string): { message: string; detail: string } {
  if (code === 'llm_unconfigured') return { message: '质询服务暂未就绪。', detail: code }
  if (code === 'llm_timeout') return { message: '质询服务暂不可用，请稍后重试。', detail: code }
  if (code === 'material_not_found') return { message: '材料不存在，请重新选择。', detail: code }
  return { message: '质询服务暂不可用，请稍后重试。', detail: message !== '' ? `${code} · ${message}` : code }
}

async function generate() {
  if (generating.value || materialId.value === '') return
  generating.value = true
  error.value = null
  questions.value = []
  generated.value = false
  try {
    const response = await fetch('/api/v1/grill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ material_id: materialId.value }),
    })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      const code = body?.code ? body.code : `HTTP ${response.status}`
      error.value = failureText(code, body?.message ? body.message : '')
      return
    }
    questions.value = Array.isArray(body) ? (body as GrillQuestion[]) : []
    generated.value = true
  } catch (cause) {
    error.value = { message: '质询服务暂不可用，请稍后重试。', detail: cause instanceof Error ? cause.message : '网络错误' }
  } finally {
    generating.value = false
  }
}

function retry() {
  void generate()
}

// 换材料后旧追问与旧原文一并作废；恢复快照时由 skipMaterialClear 跳过本次清空。
watch(materialId, () => {
  if (skipMaterialClear) {
    skipMaterialClear = false
    return
  }
  questions.value = []
  generated.value = false
  error.value = null
  blocks.value = []
  blocksUnavailable.value = false
})

watch([materialId, questions, generated], () => {
  if (reviewId.value === '') return
  session.saveCapability(snapshotKey.value, {
    materialId: materialId.value,
    questions: questions.value,
    generated: generated.value,
  } satisfies GrillSnapshot)
})

function blockById(blockId: string): Block | null {
  return blocks.value.find((block) => block.id === blockId) ?? null
}

function rowLocation(blockId: string): string {
  return locatorLabel(blockById(blockId)?.locator ?? null)
}

function blockAt(offset: number): Block | null {
  const index = blocks.value.findIndex((item) => item.id === drawerBlockId.value)
  if (index < 0) return null
  return blocks.value[index + offset] ?? null
}

const drawerBlock = computed(() => blockById(drawerBlockId.value))
const previousBlock = computed(() => blockAt(-1))
const nextBlock = computed(() => blockAt(1))
const drawerFilename = computed(() => filenameOf(materialId.value))

async function ensureBlocks() {
  if (blocks.value.length > 0 || blocksUnavailable.value || materialId.value === '') return
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId.value)}`)
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      blocksUnavailable.value = true
      return
    }
    blocks.value = Array.isArray(body?.blocks) ? (body.blocks as Block[]) : []
  } catch {
    blocksUnavailable.value = true
  }
}

async function openQuestion(question: GrillQuestion) {
  drawerBlockId.value = question.block_id
  drawerOpen.value = true
  highlight.value = null
  await ensureBlocks()
  const block = blockById(question.block_id)
  if (block) highlight.value = { line_number: block.locator.index, start: question.start, end: question.end }
}

// 「在材料中打开」：该材料的全部追问映射成 ReaderTarget；materialId 取 block.document_id。
async function openInReader(question: GrillQuestion) {
  await ensureBlocks()
  const clickedBlock = blockById(question.block_id)
  if (!clickedBlock) {
    blocksUnavailable.value = true
    return
  }
  const targets = questions.value
    .map((item): ReaderTarget | null => {
      const block = blockById(item.block_id)
      return block
        ? { materialId: block.document_id, blockId: item.block_id, start: item.start, end: item.end, quote: item.quote }
        : null
    })
    .filter((target): target is ReaderTarget => target !== null)
  const index = targets.findIndex((target) => target.blockId === question.block_id && target.start === question.start)
  session.openReader({
    reviewId: reviewId.value,
    reviewTitle: reviewTitle.value,
    materialLabel: labelOf(clickedBlock.document_id),
    materialFilename: filenameOf(clickedBlock.document_id),
    targets,
    index: index < 0 ? 0 : index,
    origin: { fullPath: route.fullPath, label: '质询' },
  })
  await router.push(
    `/reviews/${reviewId.value}/reader/${clickedBlock.document_id}?b=${question.block_id}&s=${question.start}&e=${question.end}`,
  )
}

loadLibrary()
</script>

<template>
  <div class="space-y-8">
    <section>
      <h2 class="text-sm font-medium tracking-wide text-slate-200">质询</h2>
      <p class="mt-1 text-xs text-slate-500">针对已暴露的薄弱点，提前列出评审席的针对性追问。</p>

      <EmptyState
        v-if="members.length < 1"
        class="mt-4 rounded-xl bg-slate-950/40"
        title="本次审查还没有材料"
        hint="先在材料页加入至少一份材料，再开始质询。"
      >
        <UButton :to="`${basePath}/members`" icon="i-lucide-files">管理材料</UButton>
      </EmptyState>

      <p v-else-if="loading" class="mt-4 text-sm text-slate-400">正在读取材料库…</p>

      <div v-else-if="loadError" class="mt-4 rounded-xl bg-slate-950/40 px-5 py-4">
        <p class="text-sm text-red-400" role="alert">无法加载材料库：{{ loadError }}</p>
        <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="loadLibrary">重试</UButton>
      </div>

      <div v-else class="mt-4 flex flex-wrap items-center gap-3">
        <select
          v-model="materialId"
          aria-label="选择材料"
          class="w-full max-w-md rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
        >
          <option value="">选择材料</option>
          <option v-for="member in members" :key="member.material_id" :value="member.material_id">
            {{ identityLine(member.label, filenameOf(member.material_id)) }}
          </option>
        </select>
        <UButton icon="i-lucide-crosshair" :loading="generating" :disabled="materialId === ''" @click="generate">
          {{ generating ? '正在质询…' : '开始质询' }}
        </UButton>
      </div>

      <div v-if="error" class="mt-4" role="alert">
        <p class="text-sm text-red-400">{{ error.message }}</p>
        <p v-if="error.detail" class="mt-0.5 text-xs text-slate-500">技术细节：{{ error.detail }}</p>
        <UButton v-if="!generating" class="mt-3" size="sm" color="neutral" variant="subtle" icon="i-lucide-refresh-cw" @click="retry">重试</UButton>
      </div>
    </section>

    <section v-if="generated && members.length >= 1">
      <div class="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-800 pb-3">
        <h2 class="text-sm font-medium tracking-wide text-slate-200">针对性追问</h2>
        <span class="text-xs text-slate-500">{{ questions.length }} 条 · 仅展示能够回到原文的追问</span>
      </div>
      <p class="mt-1 text-xs text-slate-500">{{ identityLine(labelOf(materialId), filenameOf(materialId)) }}</p>
      <EmptyState
        v-if="emptyResult"
        class="mt-4"
        title="当前材料没有生成可追溯的针对性追问。"
        hint="可以先完成审查，或更换材料后再试。"
      />
      <ol v-else class="mt-5 space-y-4">
        <li
          v-for="(question, index) in questions"
          :key="`${question.block_id}:${question.start}:${index}`"
          class="rounded-lg border border-slate-800 bg-slate-900/40 p-5"
        >
          <div class="flex gap-5">
            <span aria-hidden="true" class="w-10 shrink-0 select-none text-right font-mono text-3xl leading-tight text-violet-400/70">{{ String(index + 1).padStart(2, '0') }}</span>
            <div class="min-w-0 flex-1">
              <p class="text-lg font-medium leading-relaxed text-slate-100">{{ question.prompt }}</p>

              <p class="mt-5 text-xs tracking-widest text-slate-500">触发依据</p>
              <div class="mt-1.5 flex flex-wrap items-center gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-3 py-2.5">
                <button type="button" class="group flex min-w-0 flex-1 items-center justify-between gap-4 text-left" @click="openQuestion(question)">
                  <span class="min-w-0 text-sm leading-relaxed text-slate-300">“{{ question.quote }}”</span>
                  <span class="flex shrink-0 items-center gap-3">
                    <span class="text-xs text-slate-500">{{ rowLocation(question.block_id) }}</span>
                    <span class="text-xs text-violet-300/90 transition group-hover:text-violet-200">查看原文 →</span>
                  </span>
                </button>
                <button type="button" class="shrink-0 text-[11px] text-slate-500 transition hover:text-violet-300" @click="openInReader(question)">在材料中打开</button>
              </div>
            </div>
          </div>
        </li>
      </ol>
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
