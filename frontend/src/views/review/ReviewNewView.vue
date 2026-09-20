<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { MaterialSummary, Rubric } from '../../types/contracts'
import { ApiFailure, reviewsApi } from '../../services/reviews'
import { resolveCriteriaSource, type CriteriaSource } from '../../services/criteriaSource'
import PageHeader from '../../components/review/PageHeader.vue'

// 开始新审查 Wizard：① 审哪些材料 → ② 按什么要求 → ③ 确认开始。
// 用户心智只有这三步；Rubric/Binding/ID 等内部术语不出现在文案里。
// 标准来源当前只有「使用已有标准」可真正开始；粘贴/上传/手工是 Builder 的交互壳，
// 经 services/criteriaSource 适配边界解析，契约冻结前一律返回 unavailable。
const router = useRouter()

interface Seat {
  materialId: string
  filename: string
  checked: boolean
  label: string
}

const steps = ['审哪些材料', '按什么要求', '确认开始'] as const
const step = ref(0)

const rubrics = ref<Rubric[]>([])
const materials = ref<MaterialSummary[]>([])
const loading = ref(true)
const loadError = ref('')

const seats = ref<Seat[]>([])
const criteriaKind = ref<CriteriaSource['kind']>('existing')
const rubricKey = ref('')
const pastedRequirements = ref('')
const title = ref('')

const submitting = ref(false)
const submitError = ref('')
const conflictMaterial = ref('')
// 冲突发生在 create 之后时，重试直接复用已建 Review，避免重复建单。
const createdReviewId = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [rubricResponse, materialResponse] = await Promise.all([
      fetch('/api/v1/rubrics'),
      fetch('/api/v1/materials'),
    ])
    const rubricBody = await rubricResponse.json().catch(() => null)
    const materialBody = await materialResponse.json().catch(() => null)
    if (!rubricResponse.ok) throw new Error(rubricBody?.message ?? `HTTP ${rubricResponse.status}`)
    if (!materialResponse.ok) throw new Error(materialBody?.message ?? `HTTP ${materialResponse.status}`)
    rubrics.value = Array.isArray(rubricBody) ? (rubricBody as Rubric[]) : []
    materials.value = Array.isArray(materialBody) ? (materialBody as MaterialSummary[]) : []
    seats.value = materials.value.map((material) => ({
      materialId: material.id,
      filename: material.filename,
      checked: false,
      label: '',
    }))
  } catch (cause) {
    loadError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

const criteriaSource = computed<CriteriaSource>(() => {
  if (criteriaKind.value === 'paste') return { kind: 'paste', text: pastedRequirements.value }
  return { kind: 'existing', rubricKey: rubricKey.value }
})
const resolution = computed(() => resolveCriteriaSource(criteriaSource.value, rubrics.value))
const resolvedRubric = computed(() => {
  const resolved = resolution.value
  if (resolved.status !== 'ready') return null
  return rubrics.value.find((rubric) => rubric.id === resolved.rubricId && rubric.revision === resolved.rubricRevision) ?? null
})
const checkedSeats = computed(() => seats.value.filter((seat) => seat.checked))

const canNext = computed(() => {
  if (step.value === 1) return resolution.value.status === 'ready'
  return true
})
const canSubmit = computed(() => !submitting.value && title.value.trim() !== '' && resolution.value.status === 'ready')

const criteriaOptions = [
  { kind: 'existing' as const, name: '使用已有标准', note: '从已发布的审查标准中选择' },
  { kind: 'paste' as const, name: '粘贴审查要求', note: '即将开放：粘贴要求文本，生成标准草稿后确认' },
  { kind: 'upload' as const, name: '上传要求文件', note: '即将开放：上传 Markdown 要求文件' },
  { kind: 'manual' as const, name: '手工创建', note: '即将开放：逐条编写审查要求' },
]

async function submit() {
  if (!canSubmit.value || resolution.value.status !== 'ready') return
  const resolved = resolution.value
  submitting.value = true
  submitError.value = ''
  conflictMaterial.value = ''
  try {
    let reviewId = createdReviewId.value
    if (reviewId === '') {
      const review = await reviewsApi.create({
        title: title.value.trim(),
        rubric_id: resolved.rubricId,
        rubric_revision: resolved.rubricRevision,
      })
      reviewId = review.id
      createdReviewId.value = reviewId
    }
    for (const seat of checkedSeats.value) {
      try {
        const seatLabel = seat.label.trim()
        await reviewsApi.upsertMaterial(reviewId, seat.materialId, seatLabel === '' ? {} : { label: seatLabel })
      } catch (cause) {
        if (cause instanceof ApiFailure && cause.code === 'binding_conflict') {
          conflictMaterial.value = seat.filename
        }
        throw cause
      }
    }
    router.replace(`/reviews/${reviewId}`)
  } catch (cause) {
    submitError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    submitting.value = false
  }
}

load()
</script>

<template>
  <main class="mx-auto max-w-3xl px-6 py-10">
    <PageHeader title="开始新审查" subtitle="三步：选材料、定要求、确认开始。">
      <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">返回</UButton>
    </PageHeader>

    <!-- 步骤条 -->
    <ol class="mt-6 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs" aria-label="创建步骤">
      <template v-for="(name, index) in steps" :key="name">
        <li class="flex items-center gap-2" :class="index === step ? 'text-slate-100' : index < step ? 'text-slate-400' : 'text-slate-600'">
          <span
            class="flex size-5 items-center justify-center rounded-full font-mono text-[10px]"
            :class="index === step ? 'bg-violet-500/20 text-violet-300 ring-1 ring-violet-500/40' : index < step ? 'bg-emerald-500/15 text-emerald-300' : 'bg-slate-800 text-slate-500'"
          >{{ index + 1 }}</span>
          <span>{{ name }}</span>
        </li>
        <li v-if="index < steps.length - 1" aria-hidden="true" class="text-slate-700">→</li>
      </template>
    </ol>

    <p v-if="loading" class="mt-8 text-sm text-slate-400">正在读取材料与标准…</p>

    <div v-else-if="loadError" class="mt-8 rounded-xl bg-slate-950/40 px-5 py-4">
      <p class="text-sm text-red-400" role="alert">无法加载表单数据：{{ loadError }}</p>
      <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="load">重试</UButton>
    </div>

    <template v-else>
      <!-- 第一步：审哪些材料 -->
      <section v-if="step === 0" class="mt-8">
        <div class="flex items-baseline justify-between gap-3">
          <h2 class="text-sm font-medium text-slate-200">这次审哪些材料？</h2>
          <span class="text-[11px] text-slate-600">可不选；创建后也能在审查里添加</span>
        </div>
        <p v-if="materials.length === 0" class="mt-3 text-xs text-slate-500">
          材料库还没有材料，可以先创建审查，稍后在「材料」页上传并加入。
        </p>
        <ul v-else class="mt-3 divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800">
          <li v-for="seat in seats" :key="seat.materialId" class="flex flex-wrap items-start gap-3 px-4 py-3">
            <input
              v-model="seat.checked"
              type="checkbox"
              class="mt-1 size-4 shrink-0 accent-violet-500"
              :aria-label="`选择材料 ${seat.filename}`"
            />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm text-slate-200">{{ seat.filename }}</span>
            </span>
            <label class="flex shrink-0 flex-col text-[11px] text-slate-500">
              <span>在本次审查中的名称</span>
              <input
                v-model="seat.label"
                type="text"
                placeholder="技术方案 · 初稿 / 性能测试报告 / 答辩稿"
                :disabled="!seat.checked"
                class="mt-0.5 w-48 rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-50"
              />
              <span class="mt-0.5 text-slate-600">留空则使用原文件名</span>
            </label>
          </li>
        </ul>
      </section>

      <!-- 第二步：按什么要求 -->
      <section v-else-if="step === 1" class="mt-8">
        <h2 class="text-sm font-medium text-slate-200">按什么要求审？</h2>
        <div class="mt-3 grid gap-3 sm:grid-cols-2">
          <button
            v-for="option in criteriaOptions"
            :key="option.kind"
            type="button"
            class="rounded-xl border p-4 text-left transition"
            :class="criteriaKind === option.kind
              ? 'border-violet-500/60 bg-violet-950/20'
              : 'border-slate-800 hover:border-slate-700'"
            @click="criteriaKind = option.kind"
          >
            <p class="text-sm font-medium text-slate-200">{{ option.name }}</p>
            <p class="mt-1 text-xs leading-relaxed text-slate-500">{{ option.note }}</p>
          </button>
        </div>

        <div v-if="criteriaKind === 'existing'" class="mt-4">
          <select
            v-model="rubricKey"
            aria-label="审查标准"
            :disabled="rubrics.length === 0"
            class="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
          >
            <option value="">请选择审查标准</option>
            <option v-for="rubric in rubrics" :key="`${rubric.id}:${rubric.revision}`" :value="`${rubric.id}:${rubric.revision}`">
              {{ rubric.title }} · v{{ rubric.revision }}
            </option>
          </select>
          <p v-if="rubrics.length === 0" class="mt-2 rounded-md bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
            还没有已发布的审查标准，暂时无法创建审查。
          </p>
        </div>

        <div v-else-if="criteriaKind === 'paste'" class="mt-4">
          <textarea
            v-model="pastedRequirements"
            rows="6"
            placeholder="把审查要求粘贴在这里，例如：&#10;1. 所有性能数字必须给出测试条件&#10;2. 与摘要矛盾的表述需要标注"
            class="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
          ></textarea>
          <p class="mt-2 rounded-md bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
            从要求生成审查标准的能力还在接入中。内容会保留，但目前请改用「使用已有标准」开始审查。
          </p>
        </div>

        <p v-else class="mt-4 rounded-md bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
          这种方式还在接入中，目前请改用「使用已有标准」开始审查。
        </p>
      </section>

      <!-- 第三步：确认开始 -->
      <section v-else class="mt-8">
        <h2 class="text-sm font-medium text-slate-200">确认这次审查</h2>
        <dl class="mt-3 space-y-2 rounded-xl border border-slate-800 p-4 text-sm">
          <div class="flex gap-3">
            <dt class="w-20 shrink-0 text-xs text-slate-500">审查材料</dt>
            <dd class="text-slate-300">
              <template v-if="checkedSeats.length > 0">
                {{ checkedSeats.map((seat) => (seat.label.trim() !== '' ? seat.label.trim() : seat.filename)).join('、') }}
              </template>
              <span v-else class="text-slate-500">暂不选择，创建后再添加</span>
            </dd>
          </div>
          <div class="flex gap-3">
            <dt class="w-20 shrink-0 text-xs text-slate-500">审查标准</dt>
            <dd class="text-slate-300">
              <template v-if="resolvedRubric">
                {{ resolvedRubric.title }}
                <span class="text-xs text-slate-500">· v{{ resolvedRubric.revision }}</span>
              </template>
              <span v-else class="text-amber-300">尚未选定可用标准，请返回上一步</span>
            </dd>
          </div>
        </dl>

        <label class="mt-4 block">
          <span class="text-xs text-slate-500">给这次审查起个名字</span>
          <input
            v-model="title"
            type="text"
            placeholder="例如：2026 春季项目申报材料终审"
            class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
          />
        </label>

        <div v-if="submitError" class="mt-4 rounded-xl bg-slate-950/40 px-5 py-4" role="alert">
          <p v-if="conflictMaterial" class="text-sm text-amber-300">
            材料「{{ conflictMaterial }}」已绑定其他审查标准版本，无法加入本次审查。
          </p>
          <p class="mt-1 text-sm text-red-400">{{ submitError }}</p>
        </div>
      </section>

      <!-- 导航 -->
      <div class="mt-8 flex flex-wrap items-center gap-3">
        <UButton v-if="step > 0" color="neutral" variant="subtle" icon="i-lucide-arrow-left" @click="step -= 1">
          上一步
        </UButton>
        <UButton v-if="step < steps.length - 1" icon="i-lucide-arrow-right" :disabled="!canNext" @click="step += 1">
          下一步
        </UButton>
        <UButton v-else type="button" icon="i-lucide-check" :loading="submitting" :disabled="!canSubmit" @click="submit">
          {{ submitting ? '正在创建…' : '开始审查' }}
        </UButton>
      </div>
    </template>
  </main>
</template>
