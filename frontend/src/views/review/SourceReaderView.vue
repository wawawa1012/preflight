<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Block, SavedMaterial } from '../../types/contracts'
import { useSessionStore, type ReaderTarget } from '../../stores/session'
import { locatorLabel } from '../../utils/locatorLabel'
import { createRequestScope } from '../../utils/requestScope'

// Source Reader v1：阅读原文并定位依据。
// 结构围绕 material_id / block_id / span / server locator 设计（gutter 一律走 locatorLabel，
// 不写死行号）；定位失败明确提示，绝不猜位置。返回经 session store 回到来源页。
// 全部路由/会话输入都是响应式的：同组件复用（切材料、切引用、新 visit）会重算并重取。
const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const reviewId = computed(() => String(route.params.reviewId ?? ''))
const materialId = computed(() => String(route.params.materialId ?? ''))

const material = ref<SavedMaterial | null>(null)
const loading = ref(true)
const error = ref('')
// 切材料后迟到的旧材料响应不得落地。
const loadScope = createRequestScope()

// 引用序列：优先 session 里的 ReaderVisit（来自 Finding/Compare/Grill 的一组引用）；
// 否则退化为 query 参数指定的单条目标。
const queryTarget = computed<ReaderTarget | null>(() => {
  const blockId = String(route.query.b ?? '')
  if (!blockId) return null
  return {
    materialId: materialId.value,
    blockId,
    start: Number(route.query.s ?? 0),
    end: Number(route.query.e ?? 0),
  }
})

const visit = computed(() => session.readerVisit)
const visitMatches = computed(
  () =>
    visit.value !== null &&
    visit.value.reviewId === reviewId.value &&
    visit.value.targets.some((target) => target.materialId === materialId.value),
)

const targets = computed<ReaderTarget[]>(() => {
  if (visitMatches.value) return visit.value!.targets.filter((target) => target.materialId === materialId.value)
  return queryTarget.value ? [queryTarget.value] : []
})

// 当前引用下标：对齐 query 指定的 block，找不到则从第一条开始。
const activeIndex = ref(0)
const activeTarget = computed(() => targets.value[activeIndex.value] ?? null)

const origin = computed(() =>
  visitMatches.value
    ? visit.value!.origin
    : { fullPath: `/reviews/${reviewId.value}`, label: '审查概览' },
)

const materialName = computed(() => {
  if (visitMatches.value && visit.value!.materialLabel) return visit.value!.materialLabel
  return material.value?.filename ?? ''
})

async function loadMaterial() {
  const ticket = loadScope.begin({ materialId: materialId.value })
  loading.value = true
  error.value = ''
  material.value = null
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(ticket.context.materialId)}`)
    const body = await response.json().catch(() => null)
    if (!response.ok) throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    ticket.commit(() => {
      material.value = body as SavedMaterial
    })
  } catch (cause) {
    ticket.commit(() => {
      error.value = cause instanceof Error ? cause.message : '未知错误'
    })
  } finally {
    ticket.commit(() => {
      loading.value = false
    })
  }
}

const blocks = computed<Block[]>(() => material.value?.blocks ?? [])

const activeBlock = computed(() => {
  const target = activeTarget.value
  return target ? (blocks.value.find((block) => block.id === target.blockId) ?? null) : null
})
// 定位失败必须显式：Block 不存在时不猜位置，只展示完整文档并提示。
const locateFailed = computed(() => !loading.value && activeTarget.value !== null && activeBlock.value === null)

// Unicode：Array.from 对齐 Python 的 code point start/end（与 EvidenceDrawer 同一约定）。
// 强校验：越界或 span 文本与冻结 quote 不一致时返回 null，绝不 clamp 猜测位置。
const highlightSegments = computed(() => {
  const block = activeBlock.value
  const target = activeTarget.value
  if (!block || !target) return null
  const chars = Array.from(block.text)
  if (target.start < 0 || target.end > chars.length || target.start >= target.end) return null
  const slice = chars.slice(target.start, target.end).join('')
  if (target.quote !== undefined && slice !== target.quote) return null
  return [
    { text: chars.slice(0, target.start).join(''), mark: false },
    { text: slice, mark: true },
    { text: chars.slice(target.end).join(''), mark: false },
  ].filter((part) => part.text.length > 0)
})

// 有目标、有 Block、加载结束，但 span 校验失败：显式提示，不猜位置。
const spanFailed = computed(
  () => !loading.value && activeTarget.value !== null && activeBlock.value !== null && highlightSegments.value === null,
)

function isTarget(block: Block) {
  return activeBlock.value?.id === block.id
}

function anchorId(block: Block) {
  return `reader-block-${block.id}`
}

async function scrollToActive() {
  await nextTick()
  const block = activeBlock.value
  if (!block) return
  document.getElementById(anchorId(block))?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function goToCitation(delta: number) {
  const next = activeIndex.value + delta
  if (next < 0 || next >= targets.value.length) return
  activeIndex.value = next
  void scrollToActive()
}

function goBack() {
  void router.push(origin.value.fullPath)
}

// 材料切换：重取全文；加载完成后 scroll watch 负责定位。
watch(materialId, () => void loadMaterial(), { immediate: true })

// 引用序列或 query 变化：重新对齐下标（优先 query 指定的 block）。
watch([targets, queryTarget], () => {
  const list = targets.value
  if (list.length === 0) {
    activeIndex.value = 0
    return
  }
  const found = queryTarget.value ? list.findIndex((target) => target.blockId === queryTarget.value!.blockId) : -1
  activeIndex.value = found >= 0 ? found : 0
})

// 定位目标就绪后滚动（材料加载完成 / 下标对齐 / 返回本页再次进入）。
watch([activeBlock, loading], () => {
  if (!loading.value && activeBlock.value) void scrollToActive()
})

onBeforeUnmount(() => loadScope.invalidate())

onUnmounted(() => session.closeReader())
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 pb-24">
    <!-- 顶条：返回来源 · 材料身份 · 当前定位 · 引用翻页。 -->
    <div class="sticky top-0 z-10 -mx-6 border-b border-slate-800 bg-slate-950/85 px-6 backdrop-blur">
      <div class="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
        <UButton color="neutral" variant="ghost" size="sm" icon="i-lucide-arrow-left" @click="goBack">
          返回{{ origin.label }}
        </UButton>
        <div class="min-w-0">
          <p class="truncate text-sm font-medium text-slate-100">{{ materialName }}</p>
          <p v-if="material && materialName !== material.filename" class="truncate font-mono text-[11px] text-slate-500">
            {{ material.filename }}
          </p>
        </div>
        <UBadge v-if="activeBlock" color="neutral" variant="subtle" size="sm">
          {{ locatorLabel(activeBlock.locator) }}
        </UBadge>
        <!-- DOCX 本期只能审查与查看原文：编辑入口如实说明限制，不暗示可保留 Word 格式。 -->
        <UButton
          v-if="material && material.format === 'docx'"
          color="neutral"
          variant="subtle"
          size="xs"
          icon="i-lucide-pencil-line"
          disabled
          title="Word 文档暂不支持创建修改版；可以审查与查看原文"
        >
          编辑为修订稿
        </UButton>
        <UButton
          v-else
          color="neutral"
          variant="subtle"
          size="xs"
          icon="i-lucide-pencil-line"
          :to="`/reviews/${reviewId}/reader/${materialId}/revise`"
        >
          编辑为修订稿
        </UButton>
        <div v-if="targets.length > 1" class="ml-auto flex items-center gap-2">
          <span class="text-xs text-slate-500">引用 {{ activeIndex + 1 }} / {{ targets.length }}</span>
          <UButton color="neutral" variant="subtle" size="xs" icon="i-lucide-chevron-up" :disabled="activeIndex === 0" aria-label="上一个引用" @click="goToCitation(-1)" />
          <UButton color="neutral" variant="subtle" size="xs" icon="i-lucide-chevron-down" :disabled="activeIndex >= targets.length - 1" aria-label="下一个引用" @click="goToCitation(1)" />
        </div>
        <!-- DOCX 编辑限制不依赖 hover：给键盘/触屏也始终可见的说明。 -->
        <p
          v-if="material && material.format === 'docx'"
          class="w-full text-[11px] leading-relaxed text-slate-500"
        >
          Word 材料可以审查和查看来源，暂不支持在此创建修改版。请在原编辑器中修改后重新上传；重新上传的文件不会自动建立修改前后的关系。
        </p>
      </div>
    </div>

    <p v-if="loading" class="py-10 text-sm text-slate-400">正在读取原文…</p>
    <div v-else-if="error" class="py-10">
      <p class="text-sm text-red-400" role="alert">无法读取材料：{{ error }}</p>
      <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="loadMaterial">重试</UButton>
    </div>

    <template v-else-if="material">
      <div v-if="locateFailed" class="mt-6 rounded-lg border border-amber-800/50 bg-amber-950/30 px-4 py-3" role="alert">
        <p class="text-sm text-amber-200">无法定位到指定的原文位置（材料内容可能已变化）。以下为完整材料，未做任何位置猜测。</p>
      </div>
      <div v-if="spanFailed" class="mt-6 rounded-lg border border-amber-800/50 bg-amber-950/30 px-4 py-3" role="alert">
        <p class="text-sm text-amber-200">原文位置与当前材料内容不一致，未做位置猜测。以下为完整材料。</p>
      </div>

      <!-- 连续文档流：gutter 是 server locator，目标 Block 居中 + span 精确高亮。 -->
      <article class="mt-6">
        <div
          v-for="block in blocks"
          :id="anchorId(block)"
          :key="block.id"
          class="flex gap-4 rounded-lg px-3 py-2 transition-colors"
          :class="isTarget(block) ? 'bg-amber-950/20 ring-1 ring-amber-500/40' : ''"
        >
          <span class="min-w-14 max-w-36 shrink-0 select-none pt-0.5 text-right font-mono text-[11px] leading-5" :class="isTarget(block) ? 'text-amber-300/80' : 'text-slate-700'">
            {{ locatorLabel(block.locator) }}
          </span>
          <p class="whitespace-pre-wrap break-words text-sm leading-6" :class="isTarget(block) ? 'text-slate-100' : 'text-slate-300'">
            <template v-if="isTarget(block) && highlightSegments">
              <template v-for="(part, index) in highlightSegments" :key="index">
                <mark v-if="part.mark" class="rounded bg-amber-500/30 px-0.5 text-amber-100">{{ part.text }}</mark>
                <span v-else>{{ part.text }}</span>
              </template>
            </template>
            <template v-else>{{ block.text }}</template>
          </p>
        </div>
      </article>
    </template>
  </main>
</template>
