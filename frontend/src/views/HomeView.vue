<script setup lang="ts">
import { ref } from 'vue'
import type { MaterialSummary } from '../types/contracts'
import type { Review } from '../types/review'
import { reviewsApi } from '../services/reviews'
import { formatSavedAt } from '../utils/format'
import EmptyState from '../components/review/EmptyState.vue'

// Home：审查的入口与延续。Hero 只说用户价值（冻结文案），
// 工作流压缩成一条低权重 strip；完整角色状态只属于 Review Overview。
const reviews = ref<Review[]>([])
const materials = ref<MaterialSummary[]>([])
const loading = ref(true)
const error = ref('')

// 工作流 strip：一句话说清产品怎么运转，不承担导航、不占主层级。
const workflow = ['上传材料', '创建审查', '核对依据', '发现不一致', '准备质询', '修改后重新验证']

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [reviewList, materialList] = await Promise.all([
      reviewsApi.list(),
      fetch('/api/v1/materials').then(async (response) => {
        const body = await response.json().catch(() => null)
        if (!response.ok) throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
        return (Array.isArray(body) ? body : []) as MaterialSummary[]
      }),
    ])
    reviews.value = reviewList
    materials.value = materialList
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

load()
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 pb-16">
    <!-- Hero：冻结文案，只说用户价值；无卡片框，靠排版与留白建立层级。 -->
    <section class="py-14">
      <h1 class="max-w-2xl text-4xl font-semibold leading-tight tracking-tight text-slate-100">
        把材料审清楚，<br class="hidden sm:block">再把结论说清楚。
      </h1>
      <p class="mt-4 max-w-xl text-sm leading-relaxed text-slate-400">
        按你的审查标准核对依据、发现不一致、准备质询，并在修改后重新验证。每个结论都能回到原文。
      </p>
      <div class="mt-8 flex flex-wrap items-center gap-3">
        <UButton to="/reviews/new" size="lg" icon="i-lucide-plus">开始新审查</UButton>
        <UButton to="/materials/new" size="lg" color="neutral" variant="subtle" icon="i-lucide-upload">添加材料</UButton>
      </div>

      <!-- 工作流 strip：一条低权重说明带，不是角色展板。 -->
      <ol class="mt-10 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500" aria-label="审查工作流">
        <template v-for="(step, index) in workflow" :key="step">
          <li class="flex items-center gap-2">
            <span class="font-mono text-[10px] text-slate-600">{{ index + 1 }}</span>
            <span>{{ step }}</span>
          </li>
          <li v-if="index < workflow.length - 1" aria-hidden="true" class="text-slate-700">→</li>
        </template>
      </ol>
    </section>

    <div class="grid gap-10 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)]">
      <!-- 继续审查：Review 是产品的一等实体。 -->
      <section>
        <div class="flex items-baseline justify-between gap-3">
          <h2 class="text-xs font-medium uppercase tracking-wider text-slate-500">继续审查</h2>
          <span class="text-[11px] text-slate-600">{{ reviews.length }} 次审查</span>
        </div>

        <div v-if="loading" class="mt-4 rounded-xl bg-slate-950/40 px-5 py-4">
          <p class="text-sm text-slate-400">正在读取审查…</p>
        </div>
        <div v-else-if="error" class="mt-4 rounded-xl bg-slate-950/40 px-5 py-4">
          <p class="text-sm text-red-400" role="alert">无法加载审查：{{ error }}</p>
          <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="load">重试</UButton>
        </div>
        <EmptyState
          v-else-if="reviews.length === 0"
          class="mt-4 rounded-xl bg-slate-950/40"
          title="还没有进行中的审查"
          hint="上传材料后创建一次审查，之后随时从这里继续。"
        >
          <UButton to="/reviews/new" icon="i-lucide-plus">开始第一次审查</UButton>
        </EmptyState>

        <div v-else class="mt-4 divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800">
          <RouterLink
            v-for="review in reviews"
            :key="review.id"
            :to="`/reviews/${review.id}`"
            class="group flex items-center justify-between gap-4 px-5 py-4 transition hover:bg-slate-800/40"
          >
            <div class="min-w-0">
              <p class="truncate text-sm font-medium text-slate-100">{{ review.title }}</p>
              <p class="mt-1 text-xs text-slate-500">更新于 {{ formatSavedAt(review.updated_at) }}</p>
            </div>
            <UIcon name="i-lucide-chevron-right" class="size-4 shrink-0 text-slate-600 transition group-hover:text-violet-300" />
          </RouterLink>
        </div>
      </section>

      <!-- 材料库：次级入口，不与审查抢层级。 -->
      <aside class="self-start rounded-xl bg-slate-950/40 p-5">
        <h2 class="text-xs font-medium uppercase tracking-wider text-slate-500">材料库</h2>
        <p class="mt-3 text-sm text-slate-300">
          {{ loading ? '…' : `${materials.length} 份已保存材料` }}
        </p>
        <p class="mt-1 text-xs leading-relaxed text-slate-500">
          材料是审查的事实源；同一份材料可以属于多次审查，并在每次审查里有自己的名字。
        </p>
        <div class="mt-4 flex flex-wrap gap-2">
          <UButton to="/materials" color="neutral" variant="subtle" size="sm" icon="i-lucide-folder-open">打开材料库</UButton>
          <UButton to="/materials/new" color="neutral" variant="ghost" size="sm" icon="i-lucide-upload">上传</UButton>
        </div>
      </aside>
    </div>
  </main>
</template>
