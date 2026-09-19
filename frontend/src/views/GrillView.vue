<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Block, MaterialSummary } from '../types/contracts'
import EvidenceDrawer from '../components/EvidenceDrawer.vue'
import PageHeader from '../components/review/PageHeader.vue'
import EmptyState from '../components/review/EmptyState.vue'
import { locatorLabel } from '../utils/locatorLabel'

// 质询（Grill）：把当前材料里已发现的问题摊成一副编号追问卡片；只读材料，不打分。
// 打开页面只 GET 材料列表；POST /api/v1/grill 只由「生成追问」按钮触发，绝不自动生成。
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
const error = ref('')
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

function failureText(code: string, message: string) {
  if (code === 'llm_unconfigured') return '后端未配置 LLM，配置后重试'
  if (code === 'llm_timeout') return '生成超时，可重试'
  if (code === 'material_not_found') return '材料不存在，请重新选择'
  return message || code
}

// 「生成追问」是唯一 POST 入口：选中一份材料才发；body 只含这一个 id。
async function generate() {
  if (generating.value || materialId.value === '') return
  generating.value = true
  error.value = ''
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
      throw new Error(failureText(code, body && body.message ? body.message : code))
    }
    questions.value = Array.isArray(body) ? (body as GrillQuestion[]) : []
    generated.value = true
  } catch (cause) {
    // 失败必须可见：写清原因，并留下「重试」按钮，不静默吞掉。
    error.value = cause instanceof Error ? cause.message : '未知错误'
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
  error.value = ''
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
    <PageHeader title="质询" subtitle="根据材料里已经发现的问题，列出评审可能追问的点">
      <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">材料库</UButton>
      <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
    </PageHeader>
    <!-- 小字说明：只列追问不打分；引用必须对上原文（对不上的已丢弃）。 -->
    <p class="mt-3 text-xs text-slate-500">只列可能被追问的点，不是打分；引用必须能在原文里对上，对不上的已丢弃。</p>

    <UCard class="mt-6">
      <p v-if="loading" class="text-sm text-slate-400">正在读取材料列表…</p>
      <div v-else-if="loadError">
        <p class="text-sm text-slate-400">请求失败：{{ loadError }}</p>
        <UButton class="mt-4" size="sm" icon="i-lucide-refresh-cw" @click="loadMaterials">重试</UButton>
      </div>
      <div v-else-if="materials.length === 0">
        <p class="text-sm text-slate-300">还没有已保存的材料，先添加一份再生成追问。</p>
        <UButton class="mt-4" size="sm" to="/materials/new" icon="i-lucide-plus">添加材料</UButton>
      </div>
      <div v-else>
        <label class="text-xs text-slate-400">
          材料
          <select
            v-model="materialId"
            aria-label="材料"
            class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
          >
            <option value="">请选择材料</option>
            <option v-for="item in materials" :key="item.id" :value="item.id">{{ item.filename }}</option>
          </select>
        </label>
        <p class="mt-3 text-xs text-slate-500">打开页面不会自动生成追问；范围：只追问选中的这一份材料，不会自动扫描材料库。</p>
        <div class="mt-4 flex flex-wrap items-center gap-3">
          <UButton icon="i-lucide-help-circle" :loading="generating" :disabled="materialId === ''" @click="generate">
            {{ generating ? '生成中…' : '生成追问' }}
          </UButton>
        </div>
        <p v-if="error" class="mt-3 text-sm text-red-400" role="alert">生成失败：{{ error }}</p>
        <div v-if="error && !generating" class="mt-2">
          <UButton size="xs" color="neutral" variant="subtle" icon="i-lucide-refresh-cw" @click="retry">重试</UButton>
        </div>
      </div>
    </UCard>

    <!-- 追问卡片：编号 + 追问点 + 依据（引用原文，点开回看）；空追问合法（引用站不住的一律丢弃）。 -->
    <section v-if="generated" class="mt-8">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h2 class="text-sm font-medium text-slate-200">追问清单</h2>
        <span class="text-xs text-slate-500">{{ questions.length }} 条 · 每条都引用材料原文</span>
      </div>
      <EmptyState
        v-if="emptyResult"
        class="mt-4"
        title="当前范围没有可引用的追问（空结果合法）"
        hint="引用对不上原文的追问已丢弃。"
      />
      <ol v-else class="mt-4 space-y-3">
        <li
          v-for="(question, index) in questions"
          :key="`${question.block_id}:${question.start}:${index}`"
          class="rounded-lg border border-slate-800 bg-slate-900/40 p-4"
        >
          <div class="flex gap-4">
            <span class="select-none font-mono text-2xl leading-none text-violet-400/80">{{ String(index + 1).padStart(2, '0') }}</span>
            <div class="min-w-0 flex-1">
              <p class="text-base leading-relaxed text-slate-100">{{ question.prompt }}</p>
              <p class="mt-3 text-xs text-slate-500">依据 · 针对已核对的原文</p>
              <button
                type="button"
                class="mt-1 w-full rounded-md border border-slate-800 bg-slate-950/40 px-3 py-2 text-left transition hover:border-violet-500/40 hover:bg-slate-800/60"
                @click="openQuestion(question)"
              >
                <span class="font-mono text-xs text-slate-300">“{{ question.quote }}”</span>
                <span class="ml-2 text-xs text-slate-500">{{ rowLocation(question.block_id) }}</span>
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
