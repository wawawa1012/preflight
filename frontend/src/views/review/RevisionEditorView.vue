<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import type { SavedMaterial } from '../../types/contracts'
import type { RevisionAdvice } from '../../stores/session'
import { useSessionStore } from '../../stores/session'
import { revisionsApi } from '../../services/revisions'
import { ApiFailure } from '../../services/reviews'
import { materialIdentity } from '../../utils/materialIdentity'

// 修订稿编辑器：旧 Material 永远不可变，保存 = 以当前材料为 parent 创建一份全新 Material。
// Review 模式（路由带 reviewId）：保存时传 review_id，child 自动加入本次审查，随后预选进修改效果。
// 独立模式（/materials/:id/revise）：child 继承 parent 绑定，不属于任何 Review。
const route = useRoute()
const router = useRouter()
const session = useSessionStore()

const reviewId = computed(() => String(route.params.reviewId ?? ''))
const materialId = computed(() => String(route.params.materialId ?? ''))
const inReview = computed(() => reviewId.value !== '')

const parent = ref<SavedMaterial | null>(null)
const loading = ref(true)
const loadError = ref('')
// DOCX 等非行格式请求 editable-source 会 400 format_not_editable：单独状态，不显示编辑器。
const notEditable = ref(false)

const originalText = ref('')
const text = ref('')
const filename = ref('')
const label = ref('')

const saving = ref(false)
const saveError = ref('')
// 保存期间冻结提交快照：请求在飞时用户继续编辑，也不影响已提交内容。
const submittedText = ref('')
const saved = ref<SavedMaterial | null>(null)

// Repair 建议上下文：只展示，不自动改任何内容；进入编辑器时消费一次。
const advice = ref<RevisionAdvice | null>(null)

const parentIdentity = computed(() => {
  // ReaderVisit 现在带 materialId：同名文件下也能准确取到这次审查里的 label。
  const visit = session.readerVisit
  const visitLabel = visit && visit.materialId === materialId.value ? visit.materialLabel : ''
  return materialIdentity(visitLabel, parent.value?.filename ?? '')
})
const childName = computed(() => (label.value.trim() !== '' ? label.value.trim() : filename.value))
const dirty = computed(() => saved.value === null && text.value !== originalText.value)
const canSave = computed(
  () => !saving.value && saved.value === null && filename.value.trim() !== '' && dirty.value,
)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [source, detailResponse] = await Promise.all([
      revisionsApi.editableSource(materialId.value),
      fetch(`/api/v1/materials/${encodeURIComponent(materialId.value)}`),
    ])
    const detailBody = await detailResponse.json().catch(() => null)
    if (!detailResponse.ok) throw new Error(detailBody?.message ?? `HTTP ${detailResponse.status}`)
    parent.value = detailBody as SavedMaterial
    originalText.value = source.text
    text.value = source.text
    filename.value = parent.value.filename
    advice.value = session.takeRevisionAdvice(materialId.value)
  } catch (cause) {
    if (cause instanceof ApiFailure && cause.code === 'format_not_editable') {
      notEditable.value = true
    } else {
      loadError.value = cause instanceof Error ? cause.message : '未知错误'
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  saveError.value = ''
  submittedText.value = text.value
  try {
    const trimmedLabel = label.value.trim()
    const created = await revisionsApi.create(materialId.value, {
      text: submittedText.value,
      filename: filename.value.trim(),
      ...(inReview.value ? { review_id: reviewId.value } : {}),
      ...(inReview.value && trimmedLabel !== '' ? { label: trimmedLabel } : {}),
    })
    saved.value = created.material
  } catch (cause) {
    // 保存失败：编辑内容保留，错误可见，可修正后重试。
    saveError.value =
      cause instanceof ApiFailure
        ? cause.message
        : cause instanceof Error
          ? cause.message
          : '未知错误'
  } finally {
    saving.value = false
  }
}

// 第一动作：把 parent/child 预选进修改效果，由 Diff 视图自己决定何时运行。
function viewDiff() {
  if (!saved.value || !inReview.value) return
  session.saveCapability(`${reviewId.value}:diff`, {
    materialIdBefore: materialId.value,
    materialIdAfter: saved.value.id,
    result: null,
  })
  void router.push(`/reviews/${reviewId.value}/diff`)
}

function goBack() {
  if (inReview.value) {
    void router.push(`/reviews/${reviewId.value}/reader/${materialId.value}`)
  } else {
    void router.push(`/materials/${materialId.value}`)
  }
}

function onBeforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) event.preventDefault()
}

onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', onBeforeUnload))
onBeforeRouteLeave(() => {
  if (dirty.value && !window.confirm('修订稿有未保存的修改，离开后将丢失。确定离开吗？')) return false
})

load()
</script>

<template>
  <main class="mx-auto max-w-4xl px-6 pb-24">
    <div class="sticky top-0 z-10 -mx-6 border-b border-slate-800 bg-slate-950/85 px-6 backdrop-blur">
      <div class="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
        <UButton color="neutral" variant="ghost" size="sm" icon="i-lucide-arrow-left" @click="goBack">
          {{ inReview ? '返回原文' : '返回材料' }}
        </UButton>
        <div class="min-w-0 text-xs text-slate-500">
          <span>基于：{{ parentIdentity.primary }}</span>
          <span class="mx-2 text-slate-700">→</span>
          <span class="text-slate-300">正在创建：{{ childName }}</span>
        </div>
        <UBadge v-if="dirty" color="warning" variant="subtle" size="sm">未保存</UBadge>
      </div>
    </div>

    <p v-if="loading" class="mt-8 text-sm text-slate-400">正在读取可编辑原文…</p>

    <div v-else-if="loadError" class="mt-8 rounded-xl bg-slate-950/40 px-5 py-4">
      <p class="text-sm text-red-400" role="alert">无法读取材料：{{ loadError }}</p>
      <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="load">重试</UButton>
    </div>

    <!-- DOCX 不承诺原格式编辑：明确说出限制与适用范围，不显示编辑器。 -->
    <section v-else-if="notEditable" class="mt-8 rounded-xl border border-slate-800 bg-slate-950/40 p-6">
      <h1 class="text-lg font-semibold text-slate-100">这份 Word 文档不能创建修改版</h1>
      <p class="mt-2 text-sm leading-relaxed text-slate-300">修改版只支持 Markdown 与纯文本材料。</p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton color="neutral" variant="subtle" icon="i-lucide-arrow-left" @click="goBack">
          {{ inReview ? '返回原文' : '返回材料' }}
        </UButton>
      </div>
    </section>

    <!-- 保存成功：明确说出「创建了新材料」，原稿没有被修改。 -->
    <section v-else-if="saved" class="mt-8 rounded-xl border border-emerald-800/50 bg-emerald-950/20 p-6">
      <h1 class="text-lg font-semibold text-slate-100">修改版已创建</h1>
      <p class="mt-2 text-sm leading-relaxed text-slate-300">
        「{{ materialIdentity('', saved.filename).primary }}」已保存为一份全新的材料{{
          inReview ? '，并已加入本次审查' : ''
        }}。原稿未被修改。
      </p>
      <div class="mt-6 flex flex-wrap gap-3">
        <UButton v-if="inReview" icon="i-lucide-git-compare" @click="viewDiff">查看修改效果</UButton>
        <UButton
          :color="inReview ? 'neutral' : 'primary'"
          :variant="inReview ? 'subtle' : 'solid'"
          icon="i-lucide-scan-search"
          :to="`/materials/${saved.id}`"
        >
          重新审查修改版
        </UButton>
        <UButton v-if="inReview" color="neutral" variant="ghost" :to="`/reviews/${reviewId}`">留在本次审查</UButton>
      </div>
    </section>

    <template v-else>
      <!-- Repair 建议上下文：建议不是补丁，不自动选择数值、不改事实。 -->
      <section v-if="advice" class="mt-6 rounded-xl border border-violet-800/50 bg-violet-950/20 p-5">
        <div class="flex items-center justify-between gap-3">
          <h2 class="text-sm font-medium text-violet-200">按此建议编辑</h2>
          <span class="text-[11px] text-slate-500">来自：{{ advice.sourceLabel }}</span>
        </div>
        <p class="mt-2 text-sm text-slate-200">{{ advice.findingSummary }}</p>
        <p class="mt-2 text-xs leading-relaxed text-slate-400">{{ advice.suggestion }}</p>
        <p class="mt-1 text-xs text-violet-300">建议动作：{{ advice.action }}</p>
        <p class="mt-3 text-[11px] leading-relaxed text-slate-500">
          建议不是补丁：系统不会自动选择任何数值或改动事实，请回到原文确认后手动编辑。
        </p>
      </section>

      <section class="mt-6 rounded-xl border border-slate-800 p-5">
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="block">
            <span class="text-xs text-slate-500">文件名</span>
            <input
              v-model="filename"
              type="text"
              :disabled="saving"
              class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
            />
          </label>
          <label v-if="inReview" class="block">
            <span class="text-xs text-slate-500">在本次审查中的名称</span>
            <input
              v-model="label"
              type="text"
              placeholder="例如：技术方案 · 修改版"
              :disabled="saving"
              class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
            />
            <span class="mt-1 block text-[11px] text-slate-600">留空则显示文件名</span>
          </label>
        </div>

        <textarea
          v-model="text"
          rows="18"
          :disabled="saving"
          aria-label="修订稿正文"
          class="mt-4 w-full rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 font-mono text-sm leading-6 text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
        ></textarea>

        <p v-if="saveError" class="mt-3 text-sm text-red-400" role="alert">
          保存失败（编辑内容已保留）：{{ saveError }}
        </p>

        <div class="mt-4 flex flex-wrap items-center gap-3">
          <UButton icon="i-lucide-save" :loading="saving" :disabled="!canSave" @click="save">
            {{ saving ? '正在保存…' : inReview ? '保存为新材料并加入本次审查' : '保存为新材料' }}
          </UButton>
          <p class="text-xs leading-relaxed text-slate-600">
            保存会创建一份全新材料，原稿不会被修改。
          </p>
        </div>
      </section>
    </template>
  </main>
</template>
