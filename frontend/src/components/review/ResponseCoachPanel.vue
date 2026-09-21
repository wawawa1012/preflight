<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CoachClaim, CoachSource, CoachSourceRef } from '../../types/contracts'
import { useSessionStore } from '../../stores/session'
import { ApiFailure } from '../../services/reviews'
import { checkAnswer, coachFingerprint } from '../../services/responseCoach'

// 练习回答（Response Coach）：用户先写出回答，系统检查这条回答能否由带入的来源支持。
// 状态存 session（草稿/来源勾选/最近反馈），页面内切换不丢；session-only，不伪装长期保存。
// 旧反馈用 fingerprint 比对当前问题+回答+来源，不一致就不渲染，绝不冒充当前结果。
const props = defineProps<{
  storageKey: string
  question: string
  materialId: string
  reviewId: string
  sourceRef: { block_id: string; quote: string }
}>()

const emit = defineEmits<{ 'open-source': [source: CoachSource] }>()

const session = useSessionStore()

const answer = computed({
  get: () => session.coachDrafts[props.storageKey]?.answer ?? '',
  set: (value: string) => session.saveCoachDraft(props.storageKey, { answer: value }),
})

const sourceExcluded = computed(() => session.coachDrafts[props.storageKey]?.sourceExcluded ?? false)

function toggleSource() {
  session.saveCoachDraft(props.storageKey, { sourceExcluded: !sourceExcluded.value })
}

// 本期面板只有 1 条触发来源；取消带入后发送空数组（不是省略字段）。
const sourceRefs = computed<CoachSourceRef[]>(() =>
  sourceExcluded.value ? [] : [{ block_id: props.sourceRef.block_id, quote: props.sourceRef.quote }],
)

const fingerprint = computed(() =>
  coachFingerprint({ question: props.question, answer: answer.value, sourceRefs: sourceRefs.value }),
)

const feedback = computed(() => session.coachDrafts[props.storageKey]?.feedback ?? null)
const currentFeedback = computed(() =>
  feedback.value !== null && feedback.value.fingerprint === fingerprint.value ? feedback.value.response : null,
)
const stale = computed(() => feedback.value !== null && feedback.value.fingerprint !== fingerprint.value)

const checking = ref(false)
const error = ref('')

function errorMessage(cause: unknown): string {
  const code = cause instanceof ApiFailure ? cause.code : ''
  if (code === 'llm_unconfigured') return '回答检查暂未就绪。'
  if (code === 'llm_timeout') return '回答检查暂不可用，请稍后重试。'
  return '回答检查暂不可用，请稍后重试。'
}

async function check() {
  if (checking.value || answer.value.trim() === '') return
  const requestFingerprint = fingerprint.value
  checking.value = true
  error.value = ''
  try {
    const response = await checkAnswer({
      materialId: props.materialId,
      reviewId: props.reviewId,
      question: props.question,
      answer: answer.value,
      sourceRefs: sourceRefs.value,
    })
    // 存的是发起时的 fingerprint：请求期间回答被改动，反馈自然变 stale，不冒充当前结果。
    session.saveCoachDraft(props.storageKey, { feedback: { fingerprint: requestFingerprint, response } })
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    checking.value = false
  }
}

// 每条 supported claim 的 source_ids 由后端白名单回填；这里只按 id 找到程序回填的来源。
function sourcesFor(claim: CoachClaim): CoachSource[] {
  const response = currentFeedback.value
  if (!response) return []
  const ids = claim.source_ids as readonly string[]
  return response.sources.filter((source) => ids.includes(source.source_id))
}

function openSource(source: CoachSource) {
  emit('open-source', source)
}
</script>

<template>
  <div class="mt-4 rounded-lg border border-violet-800/40 bg-slate-950/40 p-4">
    <p class="text-xs font-medium text-violet-300">练习回答</p>
    <p class="mt-1 text-[11px] text-slate-600">回答只保留在本次会话，不会被长期保存；系统不会替你写答案。</p>

    <textarea
      v-model="answer"
      rows="4"
      placeholder="用自己的话写下回答……"
      class="mt-2 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
    ></textarea>

    <div class="mt-3 rounded-md border border-slate-800 bg-slate-900/40 px-3 py-2.5">
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0 flex-1">
          <p class="text-[11px] tracking-widest text-slate-500">带入的来源</p>
          <p v-if="!sourceExcluded" class="mt-1 line-clamp-2 text-sm leading-relaxed text-slate-300">“{{ sourceRef.quote }}”</p>
          <p v-else class="mt-1 text-sm text-slate-400">已取消带入当前问题的触发来源。</p>
        </div>
        <button
          type="button"
          class="shrink-0 text-[11px] text-slate-500 transition hover:text-violet-300"
          @click="toggleSource"
        >
          {{ sourceExcluded ? '重新带入' : '取消带入' }}
        </button>
      </div>
      <p v-if="sourceRefs.length === 0" class="mt-1.5 text-[11px] text-amber-300/90">不带来源检查时，教练可能无法判断。</p>
    </div>

    <div class="mt-3 flex flex-wrap items-center gap-3">
      <UButton
        size="sm"
        icon="i-lucide-check-check"
        :loading="checking"
        :disabled="checking || answer.trim() === ''"
        @click="check"
      >
        {{ checking ? '正在检查回答…' : '检查我的回答' }}
      </UButton>
    </div>

    <div v-if="error" class="mt-3 rounded-md border border-red-900/50 bg-red-950/20 px-3 py-2.5" role="alert">
      <p class="text-sm text-red-400">{{ error }}</p>
      <UButton
        class="mt-2"
        size="xs"
        color="neutral"
        variant="subtle"
        icon="i-lucide-refresh-cw"
        :disabled="checking"
        @click="check"
      >
        重试
      </UButton>
    </div>

    <p v-else-if="stale" class="mt-3 text-xs text-slate-500">回答已修改，之前的检查结果不再适用。</p>

    <template v-else-if="currentFeedback">
      <p
        v-if="currentFeedback.status === 'abstain'"
        class="mt-3 rounded-md border border-amber-800/50 bg-amber-950/20 px-3 py-2.5 text-sm text-amber-200"
      >
        {{ currentFeedback.abstain_reason ?? '教练这次没有给出检查结论。' }}
      </p>

      <p
        v-else-if="currentFeedback.status === 'insufficient_context'"
        class="mt-3 rounded-md border border-amber-800/50 bg-amber-950/20 px-3 py-2.5 text-sm text-amber-200"
      >
        当前来源不足以检查这条回答。可以先重新带入来源，再检查一次。
      </p>

      <div v-else class="mt-4 space-y-4">
        <section v-if="currentFeedback.answered_aspects.length > 0">
          <p class="text-xs font-medium text-slate-300">已回应的部分</p>
          <ul class="mt-1.5 space-y-1">
            <li
              v-for="(aspect, index) in currentFeedback.answered_aspects"
              :key="`aspect-${index}`"
              class="text-sm leading-relaxed text-slate-400"
            >
              {{ aspect }}
            </li>
          </ul>
        </section>

        <section>
          <p class="text-xs font-medium text-slate-300">有材料支持的陈述</p>
          <ul v-if="currentFeedback.supported_claims.length > 0" class="mt-1.5 space-y-2">
            <li
              v-for="(claim, index) in currentFeedback.supported_claims"
              :key="`supported-${index}`"
              class="rounded-md border border-slate-800 bg-slate-900/40 px-3 py-2"
            >
              <p class="text-sm leading-relaxed text-slate-200">{{ claim.text }}</p>
              <p v-if="claim.note" class="mt-1 text-xs text-slate-500">{{ claim.note }}</p>
              <div v-if="sourcesFor(claim).length > 0" class="mt-2 flex flex-wrap gap-3">
                <button
                  v-for="source in sourcesFor(claim)"
                  :key="source.source_id"
                  type="button"
                  class="text-[11px] text-violet-300/90 transition hover:text-violet-200"
                  @click="openSource(source)"
                >
                  查看原文 →
                </button>
              </div>
            </li>
          </ul>
          <p v-else class="mt-1.5 text-sm text-slate-500">本次没有找到有材料支持的陈述。</p>
        </section>

        <section>
          <p class="text-xs font-medium text-slate-300">当前找不到依据的陈述</p>
          <template v-if="currentFeedback.unsupported_claims.length > 0">
            <ul class="mt-1.5 space-y-2">
              <li
                v-for="(claim, index) in currentFeedback.unsupported_claims"
                :key="`unsupported-${index}`"
                class="rounded-md border border-slate-800 bg-slate-900/40 px-3 py-2"
              >
                <p class="text-sm leading-relaxed text-slate-200">{{ claim.text }}</p>
                <p v-if="claim.note" class="mt-1 text-xs text-slate-500">{{ claim.note }}</p>
              </li>
            </ul>
            <p class="mt-1.5 text-[11px] text-slate-600">这些说法在带入的来源里暂时找不到对应，可以补充出处或调整表述。</p>
          </template>
          <p v-else class="mt-1.5 text-sm text-slate-500">没有发现需要补充出处的陈述。</p>
        </section>

        <section v-if="currentFeedback.missing_conditions.length > 0">
          <p class="text-xs font-medium text-slate-300">还缺什么条件</p>
          <ul class="mt-1.5 space-y-1">
            <li
              v-for="(condition, index) in currentFeedback.missing_conditions"
              :key="`condition-${index}`"
              class="text-sm leading-relaxed text-slate-400"
            >
              {{ condition }}
            </li>
          </ul>
        </section>

        <section v-if="currentFeedback.follow_up_questions.length > 0">
          <p class="text-xs font-medium text-slate-300">可能的继续追问</p>
          <ul class="mt-1.5 space-y-1">
            <li
              v-for="(question, index) in currentFeedback.follow_up_questions"
              :key="`followup-${index}`"
              class="text-sm leading-relaxed text-slate-400"
            >
              {{ question }}
            </li>
          </ul>
        </section>

        <p v-if="currentFeedback.overall_note" class="border-t border-slate-800 pt-3 text-xs leading-relaxed text-slate-500">
          {{ currentFeedback.overall_note }}
        </p>
      </div>
    </template>
  </div>
</template>
