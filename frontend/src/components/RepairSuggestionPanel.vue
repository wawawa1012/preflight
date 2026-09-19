<script setup lang="ts">
import { ref, watch } from 'vue'
import type { ConsistencyCitation, ConsistencyFinding, RepairSuggestion } from '../types/contracts'

// 修复建议面板：收到一条待核对问题就调一次 LLM，只展示改稿方向；材料原文只读。
// POST 只在这里发生：报告页只负责选中哪一条问题，不搬 LLM 逻辑。
const props = defineProps<{ materialId: string; finding: ConsistencyFinding | null }>()
const emit = defineEmits<{
  (e: 'open-citation', citation: ConsistencyCitation): void
  (e: 'close'): void
}>()

const suggestion = ref<RepairSuggestion | null>(null)
const generating = ref(false)
const error = ref('')

function failureText(code: string, message: string) {
  if (code === 'llm_unconfigured') return '后端未配置 LLM，配置后重试'
  if (code === 'llm_timeout') return '生成超时，可重试'
  if (code === 'citation_mismatch') return '引用与材料原文对不上，未生成建议'
  return message || code
}

async function generate(finding: ConsistencyFinding) {
  if (generating.value) return
  generating.value = true
  error.value = ''
  suggestion.value = null
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(props.materialId)}/repair-suggestions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(finding),
    })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      const code = body && body.code ? body.code : `HTTP ${response.status}`
      throw new Error(failureText(code, body && body.message ? body.message : code))
    }
    suggestion.value = body as RepairSuggestion
  } catch (cause) {
    // 失败必须可见：写清原因，并留下「重试」按钮，不静默吞掉。
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    generating.value = false
  }
}

function retry() {
  if (props.finding) void generate(props.finding)
}

// 点「生成修复建议」→ 选中 finding → 这里发一次请求；打开页面时 finding 为空，不发请求。
watch(
  () => props.finding,
  (finding) => {
    if (finding) void generate(finding)
  },
  { immediate: true },
)
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
