<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { MaterialSummary, Rubric, RubricDraft } from '../../types/contracts'
import { ApiFailure, reviewsApi } from '../../services/reviews'
import { criteriaBuilderApi, emptyManualDraft } from '../../services/criteriaSource'
import PageHeader from '../../components/review/PageHeader.vue'
import RubricDraftEditor from '../../components/review/RubricDraftEditor.vue'

// 开始新审查 Wizard：① 审哪些材料 → ② 按什么要求 → ③（草稿路径）编辑并确认标准 → ④ 确认开始。
// 用户只理解「材料 + 要求」；draft/publish/binding 都由这里按冻结契约接线，文案不出现内部术语。
// 模型不可用时草稿路径失败不卡死：随时可改走「手工创建」。
const router = useRouter()

interface Seat {
  materialId: string
  filename: string
  checked: boolean
  label: string
}

type CriteriaKind = 'existing' | 'paste' | 'upload' | 'manual'

const rubrics = ref<Rubric[]>([])
const materials = ref<MaterialSummary[]>([])
const loading = ref(true)
const loadError = ref('')

const seats = ref<Seat[]>([])
const criteriaKind = ref<CriteriaKind>('existing')
const rubricKey = ref('')
const pastedText = ref('')
const uploadFile = ref<File | null>(null)

const draft = ref<RubricDraft | null>(null)
const generating = ref(false)
const draftError = ref('')

// publish 非幂等：publishing 中禁止重复点击；网络层失败进入 unknown（响应不确定），
// 只允许用户手动「刷新标准列表」确认后再决定，绝不自动重试。
const publishing = ref(false)
const publishError = ref('')
const publishUnknown = ref(false)
const publishedRubric = ref<Rubric | null>(null)

const title = ref('')
const step = ref(0)

const submitting = ref(false)
const submitError = ref('')
const conflictMaterial = ref('')
// 冲突发生在 create 之后时，重试直接复用已建 Review，避免重复建单。
const createdReviewId = ref('')

async function loadRubrics() {
  const response = await fetch('/api/v1/rubrics')
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.message ?? `HTTP ${response.status}`)
  rubrics.value = Array.isArray(body) ? (body as Rubric[]) : []
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const materialResponse = await fetch('/api/v1/materials')
    const materialBody = await materialResponse.json().catch(() => null)
    if (!materialResponse.ok) throw new Error(materialBody?.message ?? `HTTP ${materialResponse.status}`)
    await loadRubrics()
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

const needsDraftStep = computed(() => criteriaKind.value !== 'existing')
const steps = computed(() =>
  needsDraftStep.value ? ['审哪些材料', '按什么要求', '确认标准', '确认开始'] : ['审哪些材料', '按什么要求', '确认开始'],
)
const draftStepIndex = 2
const confirmStepIndex = computed(() => (needsDraftStep.value ? 3 : 2))

const selectedRubric = computed(
  () => rubrics.value.find((rubric) => rubricKey.value === `${rubric.id}:${rubric.revision}`) ?? null,
)
const effectiveRubric = computed<Rubric | null>(() =>
  criteriaKind.value === 'existing' ? selectedRubric.value : publishedRubric.value,
)
const checkedSeats = computed(() => seats.value.filter((seat) => seat.checked))

const criteriaOptions: { kind: CriteriaKind; name: string; note: string }[] = [
  { kind: 'existing', name: '使用已有标准', note: '从已发布的审查标准中选择' },
  { kind: 'paste', name: '粘贴审查要求', note: '粘贴要求文本，生成可编辑的标准草稿' },
  { kind: 'upload', name: '上传要求文件', note: '支持 Markdown / TXT / 结构化标准 JSON' },
  { kind: 'manual', name: '手工创建', note: '不依赖模型，逐条编写审查要求' },
]

// —— 草稿生成 ——
async function generateDraft() {
  if (generating.value) return
  draftError.value = ''
  generating.value = true
  try {
    if (criteriaKind.value === 'manual') {
      draft.value = emptyManualDraft()
    } else if (criteriaKind.value === 'paste') {
      if (pastedText.value.trim() === '') return
      draft.value = await criteriaBuilderApi.draft({ text: pastedText.value, source_type: 'plain_text' })
    } else if (criteriaKind.value === 'upload') {
      if (!uploadFile.value) return
      const file = uploadFile.value
      // provenance 按真实扩展名：.txt→plain_text，.md/.markdown→markdown，.json→rubric_json；
      // 未知扩展不静默伪装成 markdown，明确拒绝。
      const extension = file.name.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1] ?? ''
      const sourceType =
        extension === 'txt'
          ? ('plain_text' as const)
          : extension === 'md' || extension === 'markdown'
            ? ('markdown' as const)
            : extension === 'json'
              ? ('rubric_json' as const)
              : null
      if (sourceType === null) {
        draftError.value = `暂不支持「${file.name}」这种格式，请使用 .md / .txt / .json 文件。`
        return
      }
      const text = await file.text()
      draft.value = await criteriaBuilderApi.draft({
        text,
        source_type: sourceType,
        source_name: file.name,
      })
    }
    if (draft.value) step.value = draftStepIndex
  } catch (cause) {
    // 模型失败不卡死：错误可见，可改走手工创建，输入内容保留。
    draftError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    generating.value = false
  }
}

function switchToManual() {
  criteriaKind.value = 'manual'
  draftError.value = ''
  draft.value = emptyManualDraft()
  step.value = draftStepIndex
}

const draftValid = computed(() => {
  const current = draft.value
  if (!current) return false
  if (current.title.trim() === '') return false
  if (current.criteria.length === 0) return false
  return current.criteria.every((criterion) => criterion.title.trim() !== '' && criterion.requirement.trim() !== '')
})

// —— 发布：只有用户显式确认才发生 ——
async function publish() {
  if (!draft.value || !draftValid.value || publishing.value || publishedRubric.value) return
  publishing.value = true
  publishError.value = ''
  publishUnknown.value = false
  try {
    publishedRubric.value = await criteriaBuilderApi.publish(draft.value)
  } catch (cause) {
    if (cause instanceof ApiFailure) {
      // 服务端明确拒绝（草稿不合法等）：标准未创建，修正后可由用户再次点击。
      publishError.value = cause.message
    } else {
      // 网络层失败：响应不确定，标准可能已创建——不自动重试，给用户诚实恢复路径。
      publishUnknown.value = true
    }
  } finally {
    publishing.value = false
  }
}

async function refreshRubricsAfterUnknown() {
  try {
    await loadRubrics()
  } catch {
    // 刷新失败保持 unknown 状态，下次再试。
  }
}

const canNext = computed(() => {
  if (step.value === 1) {
    if (criteriaKind.value === 'existing') return selectedRubric.value !== null
    return draft.value !== null
  }
  if (needsDraftStep.value && step.value === draftStepIndex) return publishedRubric.value !== null
  return true
})
const canSubmit = computed(() => !submitting.value && title.value.trim() !== '' && effectiveRubric.value !== null)

// —— 提交：建 Review → 加材料 ——
// B1：PUT membership 由后端在同一事务内完成首次绑定/同标准幂等/冲突 409，
// 前端不重复显式绑定调用，也不复制绑定规则，只呈现结果。
async function submit() {
  const rubric = effectiveRubric.value
  if (!canSubmit.value || !rubric) return
  submitting.value = true
  submitError.value = ''
  conflictMaterial.value = ''
  try {
    let reviewId = createdReviewId.value
    if (reviewId === '') {
      const review = await reviewsApi.create({
        title: title.value.trim(),
        rubric_id: rubric.id,
        rubric_revision: rubric.revision,
      })
      reviewId = review.id
      createdReviewId.value = reviewId
    }
    for (const seat of checkedSeats.value) {
      try {
        const seatLabel = seat.label.trim()
        // 加入成员即完成绑定语义：未绑定→后端首次绑定；同标准→幂等；已绑定其他标准→409 binding_conflict。
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
    <PageHeader title="开始新审查" subtitle="选材料、定要求、确认开始。">
      <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">返回</UButton>
    </PageHeader>

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
            @click="criteriaKind = option.kind; draft = null; publishedRubric = null; draftError = ''"
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
            还没有已发布的审查标准，可以改用粘贴或手工创建。
          </p>
        </div>

        <div v-else-if="criteriaKind === 'paste'" class="mt-4">
          <textarea
            v-model="pastedText"
            rows="6"
            placeholder="把审查要求粘贴在这里，例如：&#10;1. 所有性能数字必须给出测试条件&#10;2. 与摘要矛盾的表述需要标注"
            class="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
          ></textarea>
        </div>

        <div v-else-if="criteriaKind === 'upload'" class="mt-4">
          <input
            type="file"
            accept=".md,.markdown,.txt,.json,text/markdown,text/plain,application/json"
            class="block w-full text-sm text-slate-400 file:mr-3 file:rounded-md file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-sm file:text-slate-200"
            @change="uploadFile = ($event.target as HTMLInputElement).files?.[0] ?? null"
          />
        </div>

        <p v-else class="mt-4 text-xs text-slate-500">从一份空白标准开始，逐条写下你的审查要求。</p>

        <div v-if="criteriaKind !== 'existing'" class="mt-4 flex flex-wrap items-center gap-3">
          <UButton
            icon="i-lucide-wand-2"
            :loading="generating"
            :disabled="generating || (criteriaKind === 'paste' && pastedText.trim() === '') || (criteriaKind === 'upload' && !uploadFile)"
            @click="generateDraft"
          >
            {{ generating ? '正在生成草稿…' : draft ? '重新生成草稿' : '生成标准草稿' }}
          </UButton>
          <span v-if="generating" class="text-xs text-slate-500">模型正在起草，通常需要几秒钟；你的输入不会丢失。</span>
        </div>
        <div v-if="draftError" class="mt-3 rounded-xl bg-slate-950/40 px-5 py-4" role="alert">
          <p class="text-sm text-red-400">生成草稿失败：{{ draftError }}</p>
          <UButton class="mt-3" size="sm" color="neutral" variant="subtle" icon="i-lucide-pencil" @click="switchToManual">
            改为手工创建
          </UButton>
        </div>
      </section>

      <!-- 第三步（草稿路径）：编辑并确认标准 -->
      <section v-else-if="needsDraftStep && step === draftStepIndex && draft" class="mt-8">
        <h2 class="text-sm font-medium text-slate-200">确认标准内容</h2>
        <p class="mt-1 text-xs text-slate-500">草稿可以修改、删除、排序；确认发布后标准不可更改。</p>
        <div class="mt-4">
          <RubricDraftEditor v-model="draft" :disabled="publishing || publishedRubric !== null" />
        </div>

        <div class="mt-5 rounded-xl border border-slate-800 p-4">
          <template v-if="publishedRubric">
            <p class="text-sm text-emerald-300">
              标准已发布：{{ publishedRubric.title }} · v{{ publishedRubric.revision }}
            </p>
            <p class="mt-1 text-xs text-slate-500">发布后不可更改；下一步确认开始审查。</p>
          </template>
          <template v-else-if="publishUnknown">
            <p class="text-sm text-amber-300">发布请求的结果未知——标准可能已经创建。</p>
            <p class="mt-1 text-xs leading-relaxed text-slate-500">
              为避免重复创建，请先刷新标准列表：如果列表里已出现这份标准，回到上一步改用「使用已有标准」；确认没有创建后再重新发布。
            </p>
            <UButton class="mt-3" size="sm" color="neutral" variant="subtle" icon="i-lucide-refresh-cw" @click="refreshRubricsAfterUnknown">
              刷新标准列表
            </UButton>
          </template>
          <template v-else>
            <p v-if="publishError" class="mb-2 text-sm text-red-400" role="alert">发布被拒绝：{{ publishError }}</p>
            <UButton icon="i-lucide-check" :loading="publishing" :disabled="!draftValid || publishing" @click="publish">
              {{ publishing ? '正在发布…' : '确认并发布标准' }}
            </UButton>
            <p v-if="!draftValid" class="mt-2 text-xs text-amber-300">标准需要名称，且每条要求都有标题与内容。</p>
          </template>
        </div>
      </section>

      <!-- 最后一步：确认开始 -->
      <section v-else-if="step === confirmStepIndex" class="mt-8">
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
              <template v-if="effectiveRubric">
                {{ effectiveRubric.title }}
                <span class="text-xs text-slate-500">· v{{ effectiveRubric.revision }}</span>
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
            材料「{{ conflictMaterial }}」已绑定其他审查标准版本，无法加入本次审查，其原绑定未被改动。
          </p>
          <p class="mt-1 text-sm text-red-400">{{ submitError }}</p>
        </div>
      </section>

      <!-- 导航 -->
      <div class="mt-8 flex flex-wrap items-center gap-3">
        <UButton v-if="step > 0" color="neutral" variant="subtle" icon="i-lucide-arrow-left" @click="step -= 1">
          上一步
        </UButton>
        <UButton v-if="step < confirmStepIndex" icon="i-lucide-arrow-right" :disabled="!canNext" @click="step += 1">
          下一步
        </UButton>
        <UButton v-else type="button" icon="i-lucide-check" :loading="submitting" :disabled="!canSubmit" @click="submit">
          {{ submitting ? '正在创建…' : '开始审查' }}
        </UButton>
      </div>
    </template>
  </main>
</template>
