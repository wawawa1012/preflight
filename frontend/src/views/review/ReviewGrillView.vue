<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { CoachSource, DetectedStatement, GrillQuestion, MaterialSummary } from '../../types/contracts'
import { reviewContextKey } from './reviewContext'
import { useSessionStore, type ReaderTarget } from '../../stores/session'
import EmptyState from '../../components/review/EmptyState.vue'
import ResponseCoachPanel from '../../components/review/ResponseCoachPanel.vue'
import { locatorLabel } from '../../utils/locatorLabel'
import { identityLine } from '../../utils/materialIdentity'
import { createRequestScope } from '../../utils/requestScope'
import {
  loadGrillSnapshot,
  saveGrillSnapshot,
  verifyRestoredQuestion,
  GRILL_RECOVERY_VERSION,
  type GrillRecoveryCoachDraft,
} from '../../utils/grillRecovery'

// 模拟评审 / 答辩演练（后台角色：Challenge Examiner）：对选中材料生成可回到原文的针对性追问。
// GrillQuestion 直接使用 generated 契约类型：trigger / why / preparation 由后端程序确定性生成，
// 前端只呈现，不自行推断「为什么可能被问」。
// 位置展示唯一规则：locatorLabel(question.locator)，question.locator 是后端复验过的权威定位；
// 禁止为了显示位置再从本地 blocks 推导。source identity 始终是 material + block + span + quote。
// 来源动作只有一个：「查看原文」，统一进入现有 Source Reader；本页不再维护第二套 Drawer。
// 延迟体验：模型生成期间先展示确定性准备材料（关键陈述信号），不是只有 spinner。
// stale guard：requestScope；换材料/重新生成后，迟到的旧响应直接丢弃。
// 刷新恢复：sessionStorage（utils/grillRecovery.ts）；恢复的问题必须逐条与当前原文复验，
// 复验通过前来源动作不可点；Coach 反馈永不恢复，只恢复回答草稿与来源勾选。
// 内存快照 key = `${reviewId}:grill`（本会话切页返回）；持久恢复由 grillRecovery 负责。
interface GrillSnapshot {
  materialId: string
  questions: GrillQuestion[]
  generated: boolean
  generatedAt: string
  // 本会话内导航往返直接可信（生成时已由服务端复验）；来自 sessionStorage 的恢复才需要复验。
  trusted: boolean
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
const generatedAt = ref('')
const emptyResult = computed(() => generated.value && questions.value.length === 0)

// 刷新恢复状态：restored = 问题来自 sessionStorage；trusted = 已与当前原文逐条复验。
// 复验是局部动作：失败只影响来源入口，绝不把整个 Grill 标成不可用，可单独重试。
const restored = ref(false)
const trusted = ref(false)
const verifying = ref(false)
const verifyError = ref('')
const droppedCount = ref(0)
// 复验通过后再写回 session 的 Coach 草稿（key = questionKey）；不含 feedback。
let recoveredCoachDrafts: Record<string, GrillRecoveryCoachDraft> = {}

// 来源动作的可信门槛：新生成的问题服务端已复验；恢复的问题必须等本地复验通过。
const sourceTrusted = computed(() => generated.value && (!restored.value || trusted.value))

// 模拟评审：request scope + 确定性准备材料（关键陈述信号）+ 练习回答展开态。
// 三条 scope 分开：信号拉取不得打断进行中的问题生成，复验拉取也独立。
const generateScope = createRequestScope()
const signalScope = createRequestScope()
const verifyScope = createRequestScope()
const signals = ref<DetectedStatement[]>([])
const signalsUnavailable = ref(false)
const coachOpenFor = ref('')

// Coach 草稿 key 需要区分「同一来源位置的两条不同问题」：backend 尚无稳定 question_id，
// 用 session-local 的确定性散列（问题文本 + 来源位置），不新增持久实体。
function questionKey(question: GrillQuestion): string {
  let hash = 2166136261
  for (let index = 0; index < question.prompt.length; index += 1) {
    hash ^= question.prompt.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `${question.block_id}:${question.start}:${(hash >>> 0).toString(36)}`
}

function toggleCoach(question: GrillQuestion) {
  const key = questionKey(question)
  coachOpenFor.value = coachOpenFor.value === key ? '' : key
}

function coachStorageKey(question: GrillQuestion): string {
  return `${reviewId.value}:${materialId.value}:${questionKey(question)}`
}

// 关键陈述信号是确定性 GET：选中材料即可见，模型等待期间用户有真实内容可看。
async function loadSignals(id: string) {
  if (id === '') return
  const ticket = signalScope.begin({ materialId: id, purpose: 'signals' as const })
  signalsUnavailable.value = false
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(id)}/statement-signals`)
    const body = await response.json().catch(() => null)
    ticket.commit(() => {
      if (!response.ok) {
        signalsUnavailable.value = true
        return
      }
      signals.value = Array.isArray(body) ? (body as DetectedStatement[]) : []
    })
  } catch {
    ticket.commit(() => {
      signalsUnavailable.value = true
    })
  }
}

function labelOf(id: string) {
  return members.value.find((member) => member.material_id === id)?.label ?? filenameOf(id)
}

function filenameOf(id: string) {
  return library.value.find((item) => item.id === id)?.filename ?? '未知材料'
}

// DOCX 可审查、可定位原文，但本期不承诺创建修改版（后端 400 format_not_editable）。
// 限制必须 inline 可见：tooltip 对键盘/触屏用户不是可靠信息渠道。
function isEditableFormat(id: string) {
  const format = library.value.find((item) => item.id === id)?.format
  return format !== 'docx'
}

// —— 持久恢复（sessionStorage）——
function currentRecoverySnapshot(): Parameters<typeof saveGrillSnapshot>[0] | null {
  const current = review.value
  if (!current || materialId.value === '' || !generated.value) return null
  const coachDrafts: Record<string, GrillRecoveryCoachDraft> = {}
  for (const question of questions.value) {
    const entry = session.coachDrafts[coachStorageKey(question)]
    if (entry && (entry.answer !== '' || entry.sourceExcluded)) {
      // feedback 永不入盘：旧判断不能在刷新后冒充当前判断。
      coachDrafts[questionKey(question)] = { answer: entry.answer, sourceExcluded: entry.sourceExcluded }
    }
  }
  return {
    version: GRILL_RECOVERY_VERSION,
    reviewId: current.id,
    rubricId: current.rubric_id,
    rubricRevision: current.rubric_revision,
    materialId: materialId.value,
    generatedAt: generatedAt.value,
    questions: questions.value,
    coachDrafts,
  }
}

function persistRecovery() {
  const snapshot = currentRecoverySnapshot()
  if (snapshot) saveGrillSnapshot(snapshot)
}

// 恢复问题的复验：quote == block.text[start:end]，与后端「复验通过才返回」同一语义。
// 对不上的条目丢弃；全部对不上时留空态，用户可重新生成。
async function verifyRecovered(id: string) {
  const ticket = verifyScope.begin({ reviewId: reviewId.value, materialId: id, purpose: 'verify' as const })
  verifying.value = true
  verifyError.value = ''
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(id)}`)
    const body = await response.json().catch(() => null)
    ticket.commit(() => {
      if (!response.ok) {
        verifyError.value = '无法读取材料原文来核对上次结果。'
        return
      }
      const blocks = Array.isArray(body?.blocks) ? (body.blocks as { id: string; text: string }[]) : []
      const kept = questions.value.filter((question) => verifyRestoredQuestion(question, blocks))
      droppedCount.value = questions.value.length - kept.length
      questions.value = kept
      // 复验通过的题目才恢复 Coach 草稿；被丢弃题目的草稿一并消失。
      for (const question of kept) {
        const draft = recoveredCoachDrafts[questionKey(question)]
        if (draft) session.saveCoachDraft(coachStorageKey(question), { ...draft, feedback: null })
      }
      recoveredCoachDrafts = {}
      trusted.value = true
      persistRecovery()
    })
  } catch {
    ticket.commit(() => {
      verifyError.value = '无法读取材料原文来核对上次结果。'
    })
  } finally {
    ticket.commit(() => {
      verifying.value = false
    })
  }
}

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
    // 切换 Review：作废在飞的生成、信号与复验响应，防止旧 Review 的迟到结果污染新上下文。
    generateScope.invalidate()
    signalScope.invalidate()
    verifyScope.invalidate()
    generating.value = false
    verifying.value = false
    // 先重置到默认，再恢复该 review 的快照；只接受仍在成员里的 id。
    const previousMaterialId = materialId.value
    skipMaterialClear = false
    materialId.value = ''
    questions.value = []
    generated.value = false
    generatedAt.value = ''
    error.value = null
    restored.value = false
    trusted.value = false
    verifyError.value = ''
    droppedCount.value = 0
    recoveredCoachDrafts = {}
    const memberIds = new Set(members.value.map((member) => member.material_id))
    // 优先本会话内存快照（切页返回，已可信）；否则尝试 sessionStorage 恢复（刷新场景）。
    const memory = session.restoreCapability<GrillSnapshot>(`${id}:grill`)
    if (memory && memberIds.has(memory.materialId)) {
      // 仅当 materialId 实际变化时置位，避免 net 无变化时标志残留。
      skipMaterialClear = previousMaterialId !== memory.materialId
      materialId.value = memory.materialId
      questions.value = memory.questions
      generated.value = memory.generated
      generatedAt.value = memory.generatedAt
      trusted.value = memory.trusted
      restored.value = !memory.trusted
      return
    }
    const current = review.value
    const recovered = current
      ? loadGrillSnapshot({ reviewId: id, rubricId: current.rubric_id, rubricRevision: current.rubric_revision })
      : null
    if (recovered && memberIds.has(recovered.materialId)) {
      skipMaterialClear = previousMaterialId !== recovered.materialId
      materialId.value = recovered.materialId
      questions.value = recovered.questions
      generated.value = true
      generatedAt.value = recovered.generatedAt
      restored.value = true
      trusted.value = false
      recoveredCoachDrafts = recovered.coachDrafts
      void verifyRecovered(recovered.materialId)
    } else {
      materialId.value = members.value[0]?.material_id ?? ''
    }
  },
  { immediate: true },
)

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
  if (code === 'llm_unconfigured') return { message: '模拟评审暂未就绪。', detail: code }
  if (code === 'llm_timeout') return { message: '模拟评审暂不可用，请稍后重试。', detail: code }
  if (code === 'material_not_found') return { message: '材料不存在，请重新选择。', detail: code }
  return { message: '模拟评审暂不可用，请稍后重试。', detail: message !== '' ? `${code} · ${message}` : code }
}

async function generate() {
  if (generating.value || materialId.value === '') return
  const ticket = generateScope.begin({ reviewId: reviewId.value, materialId: materialId.value, purpose: 'generate' as const })
  generating.value = true
  error.value = null
  questions.value = []
  generated.value = false
  try {
    const response = await fetch('/api/v1/grill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ material_id: ticket.context.materialId }),
    })
    const body = await response.json().catch(() => null)
    // 迟到响应：用户已换材料或重新运行，直接丢弃。
    if (!ticket.isCurrent()) return
    if (!response.ok) {
      const code = body?.code ? body.code : `HTTP ${response.status}`
      ticket.commit(() => {
        error.value = failureText(code, body?.message ? body.message : '')
      })
      return
    }
    ticket.commit(() => {
      questions.value = Array.isArray(body) ? (body as GrillQuestion[]) : []
      generated.value = true
      generatedAt.value = new Date().toISOString()
      // 新生成已由服务端复验：脱离「上次恢复」状态，来源动作立即可信。
      restored.value = false
      trusted.value = false
      verifyError.value = ''
      droppedCount.value = 0
      recoveredCoachDrafts = {}
      persistRecovery()
    })
  } catch (cause) {
    ticket.commit(() => {
      error.value = { message: '模拟评审暂不可用，请稍后重试。', detail: cause instanceof Error ? cause.message : '网络错误' }
    })
  } finally {
    ticket.commit(() => {
      generating.value = false
    })
  }
}

function retry() {
  void generate()
}

// 换材料后旧追问与旧原文一并作废；恢复快照时由 skipMaterialClear 跳过本次清空。
watch(materialId, (id, previousId) => {
  generateScope.invalidate()
  verifyScope.invalidate()
  signalScope.invalidate()
  // 发起时的生成 scope 已作废，其 finally 复位会被拒；这里负责把 loading 复位回新上下文。
  generating.value = false
  verifying.value = false
  coachOpenFor.value = ''
  signals.value = []
  signalsUnavailable.value = false
  if (id) void loadSignals(id)
  if (skipMaterialClear) {
    skipMaterialClear = false
    return
  }
  questions.value = []
  generated.value = false
  generatedAt.value = ''
  error.value = null
  restored.value = false
  trusted.value = false
  verifyError.value = ''
  droppedCount.value = 0
  recoveredCoachDrafts = {}
})

watch([materialId, questions, generated, trusted], () => {
  if (reviewId.value === '') return
  session.saveCapability(snapshotKey.value, {
    materialId: materialId.value,
    questions: questions.value,
    generated: generated.value,
    generatedAt: generatedAt.value,
    trusted: trusted.value || !restored.value,
  } satisfies GrillSnapshot)
})

// Coach 草稿变化（回答/来源勾选）同步入 sessionStorage，刷新后可恢复；feedback 不入盘。
watch(
  () => session.coachDrafts,
  () => persistRecovery(),
  { deep: true },
)

// 「查看原文」：唯一来源动作，统一进入现有 Source Reader。
// 本页所有问题同属当前选中材料：material identity 直接取 materialId，无需本地 blocks。
function openInReader(question: GrillQuestion) {
  if (!sourceTrusted.value) return
  const targets = questions.value.map(
    (item): ReaderTarget => ({
      materialId: materialId.value,
      blockId: item.block_id,
      start: item.start,
      end: item.end,
      quote: item.quote,
    }),
  )
  const index = targets.findIndex((target) => target.blockId === question.block_id && target.start === question.start)
  session.openReader({
    reviewId: reviewId.value,
    reviewTitle: reviewTitle.value,
    materialId: materialId.value,
    materialLabel: labelOf(materialId.value),
    materialFilename: filenameOf(materialId.value),
    targets,
    index: index < 0 ? 0 : index,
    origin: { fullPath: route.fullPath, label: '模拟评审' },
  })
  void router.push(
    `/reviews/${reviewId.value}/reader/${materialId.value}?b=${question.block_id}&s=${question.start}&e=${question.end}`,
  )
}

// Coach「查看原文」：来源统一进入现有 Reader 上下文，返回后回到本题。
// Coach 反馈永不恢复，能走到这里的来源必然来自本次会话的实时响应，无需复验门禁。
function openCoachSource(source: CoachSource) {
  session.openReader({
    reviewId: reviewId.value,
    reviewTitle: reviewTitle.value,
    materialId: materialId.value,
    materialLabel: labelOf(materialId.value),
    materialFilename: filenameOf(materialId.value),
    targets: [{ materialId: materialId.value, blockId: source.block_id, start: source.start, end: source.end, quote: source.quote }],
    index: 0,
    origin: { fullPath: route.fullPath, label: '模拟评审' },
  })
  void router.push(
    `/reviews/${reviewId.value}/reader/${materialId.value}?b=${source.block_id}&s=${source.start}&e=${source.end}`,
  )
}

const generatedAtText = computed(() => {
  if (generatedAt.value === '') return ''
  const time = new Date(generatedAt.value)
  if (Number.isNaN(time.getTime())) return ''
  return time.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
})

onBeforeUnmount(() => {
  generateScope.invalidate()
  signalScope.invalidate()
  verifyScope.invalidate()
})

loadLibrary()
</script>

<template>
  <div class="space-y-8">
    <section>
      <h2 class="text-sm font-medium tracking-wide text-slate-200">模拟评审 · 答辩演练</h2>
      <p class="mt-1 text-xs text-slate-500">从材料原文触发评审席最可能的追问；每道题都能回到出处，也可以直接练习回答。</p>

      <EmptyState
        v-if="members.length < 1"
        class="mt-4 rounded-xl bg-slate-950/40"
        title="本次审查还没有材料"
        hint="先在材料页加入至少一份材料，再开始模拟评审。"
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
          {{ generating ? '正在生成评审问题…' : generated ? '重新生成评审问题' : '开始模拟评审' }}
        </UButton>
      </div>

      <!-- DOCX 限制 inline 可见：不靠 hover tooltip 传达关键能力边界。 -->
      <p v-if="materialId !== '' && !isEditableFormat(materialId)" class="mt-3 rounded-md bg-slate-950/40 px-3 py-2 text-xs leading-relaxed text-slate-400">
        Word 材料可以审查和查看来源，暂不支持在此创建修改版。请在原编辑器中修改后重新上传；重新上传的文件不会自动建立修改前后的关系。
      </p>

      <!-- 延迟体验：模型生成期间先看确定性准备材料，不是只有 spinner。 -->
      <div v-if="generating && signals.length > 0" class="mt-4 rounded-xl border border-slate-800 p-4">
        <p class="text-xs font-medium text-slate-300">等待评审问题时，可以先核对这份材料的关键陈述</p>
        <ul class="mt-2 space-y-1.5">
          <li v-for="signal in signals.slice(0, 5)" :key="`${signal.block_id}:${signal.start}`" class="flex items-baseline gap-2 text-sm">
            <span class="shrink-0 font-mono text-[10px] text-slate-600">{{ locatorLabel(signal.locator) }}</span>
            <span class="min-w-0 flex-1 truncate text-slate-300">“{{ signal.quote }}”</span>
          </li>
        </ul>
        <p v-if="signals.length > 5" class="mt-2 text-[11px] text-slate-600">共 {{ signals.length }} 条，其余在材料报告里。</p>
      </div>
      <p v-else-if="generating" class="mt-4 text-xs text-slate-500">正在生成评审问题，通常需要几秒钟…</p>

      <div v-if="error" class="mt-4" role="alert">
        <p class="text-sm text-red-400">{{ error.message }}</p>
        <p v-if="error.detail" class="mt-0.5 text-xs text-slate-500">技术细节：{{ error.detail }}</p>
        <UButton v-if="!generating" class="mt-3" size="sm" color="neutral" variant="subtle" icon="i-lucide-refresh-cw" @click="retry">重试</UButton>
      </div>
    </section>

    <section v-if="generated && members.length >= 1">
      <div class="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-800 pb-3">
        <h2 class="text-sm font-medium tracking-wide text-slate-200">针对性追问</h2>
        <span class="text-xs text-slate-500">
          <template v-if="restored && generatedAtText">上次生成 · {{ generatedAtText }} · </template>
          {{ questions.length }} 条 · 仅展示能够回到原文的追问
        </span>
      </div>
      <p class="mt-1 text-xs text-slate-500">{{ identityLine(labelOf(materialId), filenameOf(materialId)) }}</p>

      <!-- 恢复复验状态：局部提示 + 局部重试，绝不把整个 Grill 标成不可用。 -->
      <p v-if="restored && verifying" class="mt-3 text-xs text-slate-500">正在核对上次结果与当前原文…</p>
      <div v-else-if="restored && verifyError" class="mt-3 flex flex-wrap items-center gap-3 rounded-md border border-amber-800/50 bg-amber-950/20 px-3 py-2.5">
        <p class="text-xs text-amber-200">{{ verifyError }} 核对通过前「查看原文」暂不可用。</p>
        <UButton size="xs" color="neutral" variant="subtle" icon="i-lucide-refresh-cw" @click="verifyRecovered(materialId)">重新核对</UButton>
      </div>
      <p v-else-if="restored && trusted && droppedCount > 0" class="mt-3 text-xs text-slate-500">
        已核对上次结果与当前原文；{{ droppedCount }} 条未能对上，已隐藏。
      </p>

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

              <!-- 为什么可能被问：后端程序按来源特征确定性生成的人话映射，前端只呈现。 -->
              <p v-if="question.why" class="mt-2 text-sm leading-relaxed text-slate-400">
                <span class="text-xs tracking-widest text-slate-500">为什么可能被问　</span>{{ question.why }}
              </p>

              <p class="mt-5 text-xs tracking-widest text-slate-500">触发依据</p>
              <button
                type="button"
                class="group mt-1.5 flex w-full flex-wrap items-center justify-between gap-4 rounded-md border border-slate-800 bg-slate-950/40 px-3 py-2.5 text-left disabled:cursor-not-allowed"
                :disabled="!sourceTrusted"
                @click="openInReader(question)"
              >
                <span class="min-w-0 flex-1 text-sm leading-relaxed text-slate-300">“{{ question.quote }}”</span>
                <span class="flex shrink-0 items-center gap-3">
                  <!-- 位置唯一来源：question.locator（后端复验过的权威定位），不经本地 blocks 推导。 -->
                  <span class="text-xs text-slate-500">{{ locatorLabel(question.locator) }}</span>
                  <span v-if="sourceTrusted" class="text-xs text-violet-300/90 transition group-hover:text-violet-200">查看原文 →</span>
                  <span v-else class="text-xs text-slate-600">核对原文中…</span>
                </span>
              </button>

              <!-- 你需要准备什么：确定性 checklist，是准备方向，不是答案。 -->
              <div v-if="question.preparation.length > 0" class="mt-3">
                <p class="text-xs tracking-widest text-slate-500">你需要准备什么</p>
                <ul class="mt-1.5 space-y-1">
                  <li v-for="(item, itemIndex) in question.preparation" :key="itemIndex" class="flex items-baseline gap-2 text-sm text-slate-300">
                    <span aria-hidden="true" class="shrink-0 text-slate-600">·</span>
                    <span class="min-w-0">{{ item }}</span>
                  </li>
                </ul>
              </div>

              <!-- 动作：回到触发依据确认出处，必要时改稿，或直接练习回答。 -->
              <div class="mt-3 flex flex-wrap items-center gap-2">
                <UButton size="xs" color="neutral" variant="subtle" icon="i-lucide-book-open" :disabled="!sourceTrusted" @click="openInReader(question)">查看原文</UButton>
                <UButton
                  v-if="isEditableFormat(materialId)"
                  size="xs"
                  color="neutral"
                  variant="subtle"
                  icon="i-lucide-pencil-line"
                  :to="`${basePath}/reader/${materialId}/revise`"
                >开始修改</UButton>
                <UButton
                  size="xs"
                  :color="coachOpenFor === questionKey(question) ? 'primary' : 'neutral'"
                  variant="subtle"
                  icon="i-lucide-mic"
                  @click="toggleCoach(question)"
                >
                  {{ coachOpenFor === questionKey(question) ? '收起练习' : '练习回答' }}
                </UButton>
              </div>
              <ResponseCoachPanel
                v-if="coachOpenFor === questionKey(question)"
                :storage-key="coachStorageKey(question)"
                :question="question.prompt"
                :material-id="materialId"
                :review-id="reviewId"
                :source-ref="{ block_id: question.block_id, quote: question.quote }"
                @open-source="openCoachSource"
              />
            </div>
          </div>
        </li>
      </ol>
    </section>
  </div>
</template>
