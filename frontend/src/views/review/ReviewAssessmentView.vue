<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { reviewContextKey } from './reviewContext'
import { useSessionStore } from '../../stores/session'
import { createRequestScope } from '../../utils/requestScope'
import {
  compareAssessments,
  generateAssessment,
  getAssessment,
  listAssessments,
} from '../../services/assessment'
import type {
  AssessmentComparisonVM,
  AssessmentListItemVM,
  AssessmentSnapshotVM,
  AssessmentSourceVM,
} from '../../types/assessment'
import { ASSESSMENT_TRUTH_NOTE } from '../../utils/assessmentFormat'
import EmptyState from '../../components/review/EmptyState.vue'
import AssessmentSummary from '../../components/review/assessment/AssessmentSummary.vue'
import AssessmentSnapshotMeta from '../../components/review/assessment/AssessmentSnapshotMeta.vue'
import CriterionAssessmentCard from '../../components/review/assessment/CriterionAssessmentCard.vue'
import AssessmentCompare from '../../components/review/assessment/AssessmentCompare.vue'

// 可解释评估（Assessment）host：一次审查在固定标准/材料范围/方法下的评估快照。
// 状态语义：快照列表（summary）/ 选中快照（detail 单独拉取）/ 前后对比，全部经过 request scope。
// 页面不算总分、不推断 comparable、不解释 locator.kind；来源统一打开现有 Source Reader。
const context = inject(reviewContextKey)
if (!context) throw new Error('ReviewAssessmentView 必须在 ReviewWorkspaceView 内使用')
const { review, rubricTitle } = context

const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const reviewId = computed(() => review.value?.id ?? '')

const loading = ref(false)
const loadError = ref('')
const summaries = ref<AssessmentListItemVM[]>([])
const currentId = ref('')

const detailLoading = ref(false)
const detailError = ref('')
const current = ref<AssessmentSnapshotVM | null>(null)

const generating = ref(false)
const actionError = ref('')

// 上一个快照：可比对的候选；是否真可比较由 backend 在 compare 响应里判定。
const previousId = computed(() => {
  const index = summaries.value.findIndex((summary) => summary.id === currentId.value)
  return index >= 0 ? (summaries.value[index + 1]?.id ?? null) : null
})

const comparing = ref(false)
const comparison = ref<AssessmentComparisonVM | null>(null)
const compareError = ref('')

const listScope = createRequestScope()
const detailScope = createRequestScope()
const actionScope = createRequestScope()
const compareScope = createRequestScope()

async function loadDetail(id: string) {
  if (id === '') {
    current.value = null
    return
  }
  const ticket = detailScope.begin({ reviewId: reviewId.value, snapshotId: id })
  detailLoading.value = true
  detailError.value = ''
  try {
    const snapshot = await getAssessment(ticket.context.snapshotId)
    ticket.commit(() => {
      current.value = snapshot
    })
  } catch (cause) {
    ticket.commit(() => {
      current.value = null
      detailError.value = cause instanceof Error ? cause.message : '未知错误'
    })
  } finally {
    ticket.commit(() => {
      detailLoading.value = false
    })
  }
}

async function load() {
  if (reviewId.value === '') return
  const ticket = listScope.begin({ reviewId: reviewId.value })
  loading.value = true
  loadError.value = ''
  try {
    const list = await listAssessments(ticket.context.reviewId)
    ticket.commit(() => {
      summaries.value = list
      currentId.value = list[0]?.id ?? ''
    })
    if (ticket.isCurrent()) await loadDetail(list[0]?.id ?? '')
  } catch (cause) {
    ticket.commit(() => {
      loadError.value = cause instanceof Error ? cause.message : '未知错误'
    })
  } finally {
    ticket.commit(() => {
      loading.value = false
    })
  }
}

// 生成/重新评估：产生新 Snapshot，绝不原地修改旧 Snapshot。
async function generate() {
  if (generating.value || reviewId.value === '') return
  const ticket = actionScope.begin({ reviewId: reviewId.value })
  generating.value = true
  actionError.value = ''
  try {
    const snapshot = await generateAssessment(ticket.context.reviewId)
    ticket.commit(() => {
      summaries.value = [{ id: snapshot.id, createdAt: snapshot.createdAt }, ...summaries.value]
      currentId.value = snapshot.id
      current.value = snapshot
      comparison.value = null
    })
  } catch (cause) {
    ticket.commit(() => {
      actionError.value = cause instanceof Error ? cause.message : '未知错误'
    })
  } finally {
    ticket.commit(() => {
      generating.value = false
    })
  }
}

async function compareWithPrevious() {
  const beforeId = previousId.value
  const afterId = currentId.value
  if (!beforeId || !afterId || comparing.value) return
  const ticket = compareScope.begin({ reviewId: reviewId.value, beforeId, afterId })
  comparing.value = true
  compareError.value = ''
  comparison.value = null
  try {
    const result = await compareAssessments(ticket.context.beforeId, ticket.context.afterId)
    ticket.commit(() => {
      comparison.value = result
    })
  } catch (cause) {
    ticket.commit(() => {
      compareError.value = cause instanceof Error ? cause.message : '未知错误'
    })
  } finally {
    ticket.commit(() => {
      comparing.value = false
    })
  }
}

function selectSnapshot(id: string) {
  if (id === currentId.value) return
  currentId.value = id
  comparison.value = null
  compareError.value = ''
  void loadDetail(id)
}

// 来源统一进入现有 Source Reader；返回经 session.readerVisit 的 origin 回到本页。
function openSource(source: AssessmentSourceVM) {
  session.openReader({
    reviewId: reviewId.value,
    reviewTitle: review.value?.title ?? '',
    materialId: source.materialId,
    materialLabel: source.materialLabel,
    materialFilename: source.materialLabel,
    targets: [
      {
        materialId: source.materialId,
        blockId: source.blockId,
        start: source.start,
        end: source.end,
        quote: source.quote,
      },
    ],
    index: 0,
    origin: { fullPath: route.fullPath, label: '评估' },
  })
  void router.push(
    `/reviews/${reviewId.value}/reader/${source.materialId}?b=${source.blockId}&s=${source.start}&e=${source.end}`,
  )
}

watch(
  () => review.value?.id,
  (id) => {
    listScope.invalidate()
    detailScope.invalidate()
    actionScope.invalidate()
    compareScope.invalidate()
    loading.value = false
    detailLoading.value = false
    generating.value = false
    comparing.value = false
    summaries.value = []
    currentId.value = ''
    current.value = null
    comparison.value = null
    if (id) void load()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  listScope.invalidate()
  detailScope.invalidate()
  actionScope.invalidate()
  compareScope.invalidate()
})
</script>

<template>
  <div class="space-y-8">
    <section>
      <h2 class="text-sm font-medium tracking-wide text-slate-200">评估</h2>
      <p class="mt-1 text-xs text-slate-500">
        按「{{ rubricTitle || '当前标准' }}」与已确认的材料依据生成可解释评估；每条结论都能回到原文。
      </p>
    </section>

    <p v-if="loading" class="text-sm text-slate-400">正在读取评估…</p>

    <div v-else-if="loadError" class="rounded-xl bg-slate-950/40 px-5 py-4">
      <p class="text-sm text-red-400" role="alert">无法读取评估：{{ loadError }}</p>
      <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="load">重试</UButton>
    </div>

    <template v-else>
      <EmptyState
        v-if="summaries.length === 0"
        class="rounded-xl bg-slate-950/40"
        title="尚未生成评估"
        hint="按当前标准与已确认的材料依据生成逐条评估；你可以看到每个结论为什么成立、还缺什么。"
      >
        <UButton icon="i-lucide-clipboard-check" :loading="generating" @click="generate">
          {{ generating ? '正在评估…' : '生成可解释评估' }}
        </UButton>
      </EmptyState>

      <template v-else>
        <div class="flex flex-wrap items-center gap-3">
          <select
            :value="currentId"
            aria-label="选择评估快照"
            class="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
            @change="selectSnapshot(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="summary in summaries" :key="summary.id" :value="summary.id">
              {{ summary.createdAt }}
            </option>
          </select>
          <UButton color="neutral" variant="subtle" icon="i-lucide-refresh-cw" :loading="generating" @click="generate">
            {{ generating ? '正在评估…' : '重新评估' }}
          </UButton>
          <UButton
            v-if="previousId"
            color="neutral"
            variant="subtle"
            icon="i-lucide-git-compare"
            :loading="comparing"
            @click="compareWithPrevious"
          >
            与上次评估对比
          </UButton>
        </div>
        <p v-if="actionError" class="text-sm text-red-400" role="alert">评估失败：{{ actionError }}</p>

        <p v-if="detailLoading" class="text-sm text-slate-400">正在读取评估快照…</p>
        <div v-else-if="detailError" class="rounded-xl bg-slate-950/40 px-5 py-4">
          <p class="text-sm text-red-400" role="alert">无法读取评估快照：{{ detailError }}</p>
          <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="loadDetail(currentId)">重试</UButton>
        </div>

        <template v-else-if="current">
          <AssessmentSnapshotMeta :snapshot="current" />
          <AssessmentSummary :total="current.total" />

          <ol class="space-y-4">
            <li v-for="item in current.criteria" :key="item.criterionId">
              <CriterionAssessmentCard :item="item" @open-source="openSource" />
            </li>
          </ol>

          <div v-if="compareError" class="rounded-xl bg-slate-950/40 px-5 py-4">
            <p class="text-sm text-red-400" role="alert">无法对比：{{ compareError }}</p>
          </div>
          <AssessmentCompare v-if="comparison" :comparison="comparison" @open-source="openSource" />
        </template>
      </template>
    </template>

    <p class="border-t border-slate-800 pt-3 text-xs leading-relaxed text-slate-600">{{ ASSESSMENT_TRUTH_NOTE }}</p>
  </div>
</template>
