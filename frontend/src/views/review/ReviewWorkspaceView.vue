<script setup lang="ts">
import { computed, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { ReviewDetail } from '../../types/review'
import type { Rubric } from '../../types/contracts'
import { ApiFailure, reviewsApi } from '../../services/reviews'
import { useSessionStore } from '../../stores/session'
import { formatSavedAt } from '../../utils/format'
import { reviewContextKey } from './reviewContext'
import EmptyState from '../../components/review/EmptyState.vue'

// Review Workspace shell：context bar（这是哪一次审查）+ 左侧 rail（同一次审查的不同视角）。
// ReviewDetail 只在这里加载一次，经 provide 下发；能力视图不各自重取。
// 标准显示用 rubric.title · v{revision}；内部 rubric_id 只留在 debug tooltip，不进正常 UI。
const route = useRoute()
const session = useSessionStore()

const review = ref<ReviewDetail | null>(null)
const loading = ref(true)
const notFound = ref(false)
const error = ref('')

const reviewId = computed(() => String(route.params.reviewId ?? ''))

// 评分标准文件仓：一次性拉取，(id, revision) → title；取不到时回退 rev 号，不展示内部 id。
const rubrics = ref<Rubric[]>([])

const rubricTitle = computed(() => {
  const current = review.value
  if (!current) return ''
  const found = rubrics.value.find(
    (item) => item.id === current.rubric_id && item.revision === current.rubric_revision,
  )
  return found ? found.title : ''
})

const rubricBadge = computed(() => {
  const current = review.value
  if (!current) return ''
  const name = rubricTitle.value
  return name ? `${name} · v${current.rubric_revision}` : `审查标准 · v${current.rubric_revision}`
})

async function load() {
  if (!reviewId.value) return
  loading.value = true
  notFound.value = false
  error.value = ''
  try {
    review.value = await reviewsApi.get(reviewId.value)
    session.currentReviewId = reviewId.value
  } catch (cause) {
    review.value = null
    if (cause instanceof ApiFailure && cause.status === 404) {
      notFound.value = true
    } else {
      error.value = cause instanceof Error ? cause.message : '未知错误'
    }
  } finally {
    loading.value = false
  }
}

provide(reviewContextKey, { review, rubricTitle, refresh: load })

watch(reviewId, load, { immediate: true })

// 标准名录只读拉取一次；失败不阻塞工作区（badge 回退为「审查标准 · vN」）。
fetch('/api/v1/rubrics')
  .then(async (response) => {
    const body = await response.json().catch(() => null)
    rubrics.value = response.ok && Array.isArray(body) ? (body as Rubric[]) : []
  })
  .catch(() => {
    rubrics.value = []
  })

// rail：同一次审查的五个视角；概览用精确匹配，其余按子路径前缀。
const views = [
  { key: '', label: '概览', icon: 'i-lucide-layout-dashboard' },
  { key: 'evidence', label: '依据', icon: 'i-lucide-scan-search' },
  { key: 'consistency', label: '一致性', icon: 'i-lucide-git-compare' },
  { key: 'diff', label: '修改效果', icon: 'i-lucide-git-compare-arrows' },
  { key: 'grill', label: '模拟评审', icon: 'i-lucide-messages-square' },
  { key: 'members', label: '材料', icon: 'i-lucide-files' },
] as const

const basePath = computed(() => `/reviews/${reviewId.value}`)

function isActive(key: string) {
  if (key === '') return route.path === basePath.value || route.path === `${basePath.value}/`
  return route.path.startsWith(`${basePath.value}/${key}`)
}
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 pb-16">
    <div v-if="loading" class="py-10">
      <p class="text-sm text-slate-400">正在打开审查…</p>
    </div>

    <EmptyState
      v-else-if="notFound"
      class="py-16"
      title="找不到这次审查"
      hint="它可能已被删除；回到首页选择其他审查。"
    >
      <UButton to="/" icon="i-lucide-arrow-left">返回审查</UButton>
    </EmptyState>

    <div v-else-if="error" class="py-10">
      <p class="text-sm text-red-400" role="alert">无法打开审查：{{ error }}</p>
      <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="load">重试</UButton>
    </div>

    <template v-else-if="review">
      <!-- Context bar：始终回答「我在审哪一次、按什么标准、有哪些材料」。 -->
      <div class="sticky top-0 z-10 -mx-6 border-b border-slate-800 bg-slate-950/85 px-6 backdrop-blur">
        <div class="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
          <RouterLink to="/" class="text-xs text-slate-500 transition hover:text-slate-300">审查</RouterLink>
          <span class="text-xs text-slate-700">/</span>
          <h1 class="truncate text-sm font-semibold text-slate-100">{{ review.title }}</h1>
          <UBadge color="primary" variant="subtle" size="sm" :title="`标准 ID：${review.rubric_id}`">
            {{ rubricBadge }}
          </UBadge>
          <span class="text-xs text-slate-500">材料 {{ review.materials.length }} 份</span>
          <span class="ml-auto hidden text-[11px] text-slate-600 sm:inline">更新于 {{ formatSavedAt(review.updated_at) }}</span>
        </div>
      </div>

      <div class="mt-8 grid gap-8 lg:grid-cols-[176px_minmax(0,1fr)]">
        <!-- Rail：视角切换，不是五个独立产品。 -->
        <aside class="lg:sticky lg:top-16 lg:self-start">
          <nav class="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible" aria-label="审查视角">
            <UButton
              v-for="view in views"
              :key="view.key"
              :to="view.key === '' ? basePath : `${basePath}/${view.key}`"
              :icon="view.icon"
              color="neutral"
              :variant="isActive(view.key) ? 'soft' : 'ghost'"
              size="sm"
              class="shrink-0 justify-start lg:w-full"
            >
              {{ view.label }}
            </UButton>
          </nav>
        </aside>

        <section class="min-w-0">
          <RouterView />
        </section>
      </div>
    </template>
  </main>
</template>
