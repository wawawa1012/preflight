<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Block, MaterialSummary } from '../types/contracts'
import EvidenceDrawer from '../components/EvidenceDrawer.vue'
import PageHeader from '../components/review/PageHeader.vue'
import EmptyState from '../components/review/EmptyState.vue'
import { locatorLabel } from '../utils/locatorLabel'

// 质询（Grill）：把当前材料里已暴露的薄弱点摊成一副编号追问卡；只读材料，不打分。
// 打开页面只 GET 材料列表；POST /api/v1/grill 只由「开始质询」按钮触发，绝不自动生成。
// 追问里的 quote/start/end 已由后端逐条复验（quote == block.text[start:end]），前端只渲染。
interface GrillQuestion {
  prompt: string
  quote: string
  block_id: string
  start: number
  end: number
}

const materials = ref<MaterialSummary[]>([])
const loading = ref(true)
const loadError = ref('')

const materialId = ref('')

const generating = ref(false)
// 失败主文案说人话；code/HTTP 状态码这类机器串放 detail，页面上低权重展示。
const error = ref<{ message: string; detail: string } | null>(null)
const questions = ref<GrillQuestion[]>([])
// 空追问是合法结果：生成完成但没有任何引用站得住的追问。
const generated = ref(false)
const emptyResult = computed(() => generated.value && questions.value.length === 0)

// Drawer 需要 Block 本体：点开引用时才按需 GET 选中材料的 blocks（只读）。
const blocks = ref<Block[]>([])
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

function failureText(code: string, message: string): { message: string; detail: string } {
  if (code === 'llm_unconfigured') return { message: '质询服务暂未就绪。', detail: code }
  if (code === 'llm_timeout') return { message: '质询服务暂不可用，请稍后重试。', detail: code }
  if (code === 'material_not_found') return { message: '材料不存在，请重新选择。', detail: code }
  // 未知错误主文案固定为人话；原始 message 与内部码降级进技术细节，不上主句。
  return { message: '质询服务暂不可用，请稍后重试。', detail: message !== '' ? `${code} · ${message}` : code }
}

// 「开始质询」是唯一 POST 入口：选中一份材料才发；body 只含这一个 id。
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
      const code = body && body.code ? body.code : `HTTP ${response.status}`
      // 失败必须可见：主文案可操作，机器串降级，并保留「重试」。
      error.value = failureText(code, body && body.message ? body.message : '')
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

// 换材料后旧追问与旧原文一并作废：等下一次显式生成。
watch(materialId, () => {
  questions.value = []
  generated.value = false
  error.value = null
  blocks.value = []
  blocksUnavailable.value = false
})

function blockById(blockId: string): Block | null {
  return blocks.value.find((block) => block.id === blockId) ?? null
}

// 引用行只说位置：Block 到手用它的 Locator；未到手不猜编号。
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
const drawerFilename = computed(() => materials.value.find((item) => item.id === materialId.value)?.filename ?? '')

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

// 点依据：按需取原文 blocks；高亮只落在已复验的 [start, end) 上，位置来自 Block 的 Locator。
async function openQuestion(question: GrillQuestion) {
  drawerBlockId.value = question.block_id
  drawerOpen.value = true
  highlight.value = null
  await ensureBlocks()
  const block = blockById(question.block_id)
  if (block) {
    highlight.value = { line_number: block.locator.index, start: question.start, end: question.end }
  }
}

// 首次进入只读：唯一加载是 GET /api/v1/materials。
loadMaterials()
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-10">
    <PageHeader title="质询" subtitle="针对已暴露的薄弱点，提前列出评审席的针对性追问">
      <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">材料库</UButton>
      <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
    </PageHeader>

    <!-- 材料选择保持一行：不占页面主体，主视觉留给下方的追问卡组。 -->
    <section class="mt-6" aria-label="选择材料">
      <p v-if="loading" class="text-sm text-slate-400">正在读取材料列表…</p>
      <div v-else-if="loadError">
        <p class="text-sm text-slate-300">材料列表读取失败，请重试。</p>
        <p class="mt-0.5 text-xs text-slate-500">技术细节：{{ loadError }}</p>
        <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="loadMaterials">重试</UButton>
      </div>
      <div v-else-if="materials.length === 0">
        <p class="text-sm text-slate-300">还没有已保存的材料，先添加一份再开始质询。</p>
        <UButton class="mt-3" size="sm" to="/materials/new" icon="i-lucide-plus">添加材料</UButton>
      </div>
      <div v-else class="flex flex-wrap items-center gap-3">
        <select
          v-model="materialId"
          aria-label="选择材料"
          class="w-full max-w-md rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
        >
          <option value="">选择材料</option>
          <option v-for="item in materials" :key="item.id" :value="item.id">{{ item.filename }}</option>
        </select>
        <UButton icon="i-lucide-crosshair" :loading="generating" :disabled="materialId === ''" @click="generate">
          {{ generating ? '正在质询…' : '开始质询' }}
        </UButton>
      </div>

      <!-- 失败主文案可操作；HTTP 状态码这类机器串只在低权重小字里出现。 -->
      <div v-if="error" class="mt-4" role="alert">
        <p class="text-sm text-red-400">{{ error.message }}</p>
        <p v-if="error.detail" class="mt-0.5 text-xs text-slate-500">技术细节：{{ error.detail }}</p>
        <UButton v-if="!generating" class="mt-3" size="sm" color="neutral" variant="subtle" icon="i-lucide-refresh-cw" @click="retry">重试</UButton>
      </div>
    </section>

    <!-- 追问卡组：编号 + 问题正文（最醒目）+ 触发依据（可点回原文）。 -->
    <section v-if="generated" class="mt-10">
      <div class="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-800 pb-3">
        <h2 class="text-sm font-medium tracking-wide text-slate-200">针对性追问</h2>
        <span class="text-xs text-slate-500">{{ questions.length }} 条 · 仅展示能够回到原文的追问</span>
      </div>
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
              <button
                type="button"
                class="group mt-1.5 flex w-full items-center justify-between gap-4 rounded-md border border-slate-800 bg-slate-950/40 px-3 py-2.5 text-left transition hover:border-violet-500/40 hover:bg-slate-800/60"
                @click="openQuestion(question)"
              >
                <span class="min-w-0 text-sm leading-relaxed text-slate-300">“{{ question.quote }}”</span>
                <span class="flex shrink-0 items-center gap-3">
                  <span class="text-xs text-slate-500">{{ rowLocation(question.block_id) }}</span>
                  <span class="text-xs text-violet-300/90 transition group-hover:text-violet-200">查看原文 →</span>
                </span>
              </button>
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
  </main>
</template>
