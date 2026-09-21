<script setup lang="ts">
import { getCurrentInstance, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { ConsistencyCitation, ConsistencyFinding, RepairSuggestion } from '../types/contracts'
import { useSessionStore } from '../stores/session'
import { createAsyncGuard } from '../utils/asyncGuard'
import { failureFromResponse, toUserFacingError } from '../utils/userFacingError'

// 修复建议面板：收到一条待核对问题就调一次 LLM，只展示改稿方向；材料原文只读。
// POST 只在这里发生：报告页只负责选中哪一条问题，不搬 LLM 逻辑。
// onStatus 把运行/成功/失败如实回报给宿主，宿主计数只认成功结果，不把「选中」当「已生成」。
const props = defineProps<{
  materialId: string
  materialLabel?: string
  finding: ConsistencyFinding | null
  onStatus?: (state: 'running' | 'succeeded' | 'failed') => void
}>()
const emit = defineEmits<{
  (e: 'open-citation', citation: ConsistencyCitation): void
  (e: 'close'): void
}>()

const router = useRouter()
const session = useSessionStore()

const suggestion = ref<RepairSuggestion | null>(null)
const generating = ref(false)
const error = ref('')

// 迟到响应守卫：切换 finding / 材料或组件卸载后，旧响应一律丢弃——不写状态、不报成功。
const guard = createAsyncGuard()

function reportStatus(state: 'running' | 'succeeded' | 'failed') {
  props.onStatus?.(state)
}

async function generate(finding: ConsistencyFinding) {
  const token = guard.next()
  generating.value = true
  error.value = ''
  suggestion.value = null
  reportStatus('running')
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(props.materialId)}/repair-suggestions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(finding),
    })
    const body = await response.json().catch(() => null)
    if (!guard.isCurrent(token)) return
    if (!response.ok) throw failureFromResponse(response.status, body)
    suggestion.value = body as RepairSuggestion
    reportStatus('succeeded')
  } catch (cause) {
    if (!guard.isCurrent(token)) return
    // 失败必须可见：写清原因，并留下「重试」按钮，不静默吞掉。
    error.value = toUserFacingError(cause, '生成修复建议失败，请重试').message
    reportStatus('failed')
  } finally {
    if (guard.isCurrent(token)) generating.value = false
  }
}

function retry() {
  if (props.finding) void generate(props.finding)
}

// 「按此建议编辑」：打开修订稿编辑器并带上建议上下文。建议不是补丁——编辑器只展示它。
function startEditing() {
  if (!props.finding || !suggestion.value) return
  session.setRevisionAdvice({
    materialId: props.materialId,
    sourceLabel: props.materialLabel ?? '',
    findingSummary: props.finding.explanation,
    suggestion: suggestion.value.suggestion,
    action: suggestion.value.action,
  })
  void router.push(`/materials/${encodeURIComponent(props.materialId)}/revise`)
}

// 点「生成修复建议」→ 选中 finding → 这里发一次请求；打开页面时 finding 为空，不发请求。
watch(
  [() => props.materialId, () => props.finding],
  ([, finding]) => {
    guard.invalidate()
    if (finding) {
      void generate(finding)
    } else {
      suggestion.value = null
      error.value = ''
      generating.value = false
    }
  },
  { immediate: true },
)

// 组件卸载即作废在途响应；getCurrentInstance 守卫让 setup 也可在无实例的检查里直接调用。
if (getCurrentInstance()) onBeforeUnmount(() => guard.invalidate())
</script>

<template>
  <section v-if="finding" class="rounded-lg border border-violet-900/60 bg-slate-900/40 p-4" aria-live="polite">
    <div class="flex flex-wrap items-start justify-between gap-2">
      <div>
        <h3 class="text-sm font-medium text-slate-200">修复建议</h3>
        <p class="mt-1 text-xs text-slate-500">只给改稿方向，不会改动材料原文。</p>
      </div>
      <UButton size="xs" color="neutral" variant="ghost" icon="i-lucide-x" @click="emit('close')">关闭</UButton>
    </div>

    <p v-if="generating" class="mt-3 text-xs text-slate-400">正在生成修复建议…</p>
    <p v-else-if="error" class="mt-3 text-xs text-red-400" role="alert">生成失败：{{ error }}</p>
    <div v-else-if="suggestion" class="mt-3 space-y-2">
      <p class="text-sm text-slate-200">{{ suggestion.suggestion }}</p>
      <p class="text-xs text-violet-300">建议动作：{{ suggestion.action }}</p>
      <UButton size="xs" color="neutral" variant="subtle" icon="i-lucide-pencil-line" @click="startEditing">
        按此建议编辑
      </UButton>
    </div>
    <div v-if="error && !generating" class="mt-2">
      <UButton size="xs" color="neutral" variant="subtle" icon="i-lucide-refresh-cw" @click="retry">重试</UButton>
    </div>

    <div class="mt-3">
      <p class="text-xs text-slate-500">原文引用（点回原文）</p>
      <ul class="mt-1 space-y-1">
        <li v-for="citation in finding.citations" :key="`${citation.block_id}:${citation.start}`">
          <button
            type="button"
            class="w-full rounded-md bg-slate-900/60 p-2 text-left transition hover:bg-slate-800/60"
            @click="emit('open-citation', citation)"
          >
            <span class="font-mono text-xs text-slate-300">“{{ citation.quote }}”</span>
          </button>
        </li>
      </ul>
    </div>
  </section>
</template>
