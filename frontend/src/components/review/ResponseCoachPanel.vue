<script setup lang="ts">
import { computed, ref } from 'vue'
import { useSessionStore } from '../../stores/session'
import { checkAnswer } from '../../services/responseCoach'

// Response Coach 交互壳（RC1 契约冻结前）：
// 已定型——你的回答（session-only 草稿）、检查入口、结果四段式结构（已回应/有依据/找不到依据/还缺什么）。
// 未定型——检查本身：checkAnswer 目前一律返回 unavailable，UI 诚实呈现，不模拟任何评估结果。
const props = defineProps<{
  storageKey: string
  question: string
  materialId: string
}>()

const session = useSessionStore()

const answer = computed({
  get: () => session.coachDrafts[props.storageKey]?.answer ?? '',
  set: (value: string) => session.saveCoachDraft(props.storageKey, value),
})

const checking = ref(false)
const unavailable = ref(false)

async function check() {
  if (checking.value || answer.value.trim() === '') return
  checking.value = true
  try {
    const result = await checkAnswer({ question: props.question, answer: answer.value, materialId: props.materialId })
    if (result.status === 'unavailable') unavailable.value = true
  } finally {
    checking.value = false
  }
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
    <div class="mt-2 flex flex-wrap items-center gap-3">
      <UButton size="sm" icon="i-lucide-check-check" :loading="checking" :disabled="answer.trim() === ''" @click="check">
        检查我的回答
      </UButton>
      <span v-if="unavailable" class="text-xs text-amber-300">
        回答检查（Response Coach）还在接入中；你的回答已保留在本次会话，可以先对照触发依据自查。
      </span>
    </div>
  </div>
</template>
