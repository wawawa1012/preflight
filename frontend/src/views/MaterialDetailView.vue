<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import type {
  Block,
  CriterionEvidenceLink,
  EvidenceAnnotation,
  Rubric,
  RubricBinding,
  SavedMaterial,
} from '../types/contracts'
import BlockList from '../components/BlockList.vue'
import MaterialHeader from '../components/MaterialHeader.vue'
import { formatSavedAt } from '../utils/format'

const route = useRoute()
const materialId = String(route.params.materialId)

const material = ref<SavedMaterial | null>(null)
const loading = ref(true)
const notFound = ref(false)
const error = ref('')

// —— 证据标注（identity 层：只表示引用了真实原文） ——
const annotations = ref<EvidenceAnnotation[]>([])
const annotationsLoading = ref(false)
const annotationsError = ref('')
const selectedBlock = ref<Block | null>(null)
const quoteInput = ref('')
const noteInput = ref('')
const savingAnnotation = ref(false)
const annotationError = ref('')
const annotationNotice = ref('')
const deletingAnnotationId = ref('')
const deleteAnnotationError = ref('')
const confirmDeleteId = ref('')

// —— 评分标准绑定与人工关联（adjudication 层：只表示“人判断它相关”） ——
const rubrics = ref<Rubric[]>([])
const rubricsLoading = ref(false)
const rubricsError = ref('')
const binding = ref<RubricBinding | null>(null)
const bindingLoading = ref(false)
const bindingError = ref('')
const bindingNotice = ref('')
const bindingBusy = ref(false)
const links = ref<CriterionEvidenceLink[]>([])
const linksLoading = ref(false)
const linksError = ref('')
const linkAnnotation = ref<EvidenceAnnotation | null>(null)
const linkCriterionId = ref('')
const linkRationale = ref('')
const savingLink = ref(false)
const linkError = ref('')
const linkNotice = ref('')
const deletingLinkId = ref('')

// —— 锚点导航 ——
const highlightedBlockId = ref('')
const anchorNotice = ref('')

// 统一互斥：任一写操作进行中都不再开始另一个，防止重复提交与旧响应覆盖。
const busy = computed(
  () =>
    savingAnnotation.value ||
    savingLink.value ||
    bindingBusy.value ||
    deletingAnnotationId.value !== '' ||
    deletingLinkId.value !== '',
)

const boundRubric = computed(() => {
  const current = binding.value
  if (!current) return null
  return rubrics.value.find(item => item.id === current.rubric_id && item.revision === current.rubric_revision) ?? null
})

const annotatedCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const item of annotations.value) {
    counts[item.block_id] = (counts[item.block_id] ?? 0) + 1
  }
  return counts
})

async function requestJson(path: string, options: RequestInit = {}) {
  const response = await fetch(path, options)
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const code = body && body.code ? body.code : String(response.status)
    throw new Error(body && body.message ? `${body.message}（${code}）` : `HTTP ${response.status}`)
  }
  return body
}

async function loadMaterial() {
  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}`)
    const body = await response.json().catch(() => null)
    if (response.status === 404) {
      // 未知 ID 明确报“找不到”，不回退任何本地 mock。
      notFound.value = true
      return
    }
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    material.value = body as SavedMaterial
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function loadAnnotations() {
  annotationsLoading.value = true
  annotationsError.value = ''
  try {
    annotations.value = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/evidence-annotations`,
    )) as EvidenceAnnotation[]
  } catch (cause) {
    annotationsError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    annotationsLoading.value = false
  }
}

async function loadRubrics() {
  rubricsLoading.value = true
  rubricsError.value = ''
  try {
    rubrics.value = (await requestJson('/api/v1/rubrics')) as Rubric[]
  } catch (cause) {
    rubricsError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    rubricsLoading.value = false
  }
}

async function loadBinding() {
  bindingLoading.value = true
  bindingError.value = ''
  try {
    binding.value = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/rubric-binding`,
    )) as RubricBinding | null
  } catch (cause) {
    bindingError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    bindingLoading.value = false
  }
}

async function loadLinks() {
  linksLoading.value = true
  linksError.value = ''
  try {
    links.value = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/criterion-evidence-links`,
    )) as CriterionEvidenceLink[]
  } catch (cause) {
    linksError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    linksLoading.value = false
  }
}

async function bindRubric(rubric: Rubric) {
  if (busy.value) return
  bindingBusy.value = true
  bindingError.value = ''
  bindingNotice.value = ''
  try {
    const created = (await requestJson(`/api/v1/materials/${encodeURIComponent(materialId)}/rubric-binding`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rubric_id: rubric.id, rubric_revision: rubric.revision }),
    })) as RubricBinding
    binding.value = created
    bindingNotice.value = `已绑定 ${rubric.title}（rev${rubric.revision}）`
  } catch (cause) {
    bindingError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    bindingBusy.value = false
  }
}

// —— 证据标注操作 ——

function selectBlock(block: Block) {
  if (busy.value) return
  selectedBlock.value = block
  quoteInput.value = block.text
  noteInput.value = ''
  annotationError.value = ''
  annotationNotice.value = ''
}

function cancelSelection() {
  if (busy.value) return
  selectedBlock.value = null
  quoteInput.value = ''
  noteInput.value = ''
  annotationError.value = ''
}

async function saveAnnotation() {
  if (busy.value) return
  const block = selectedBlock.value
  if (!block) {
    annotationError.value = '请先在 Block 行选择“标注”'
    return
  }
  savingAnnotation.value = true
  annotationError.value = ''
  annotationNotice.value = ''
  try {
    // 只提交 block_id + quote + note；material_id/span 由服务端校验并派生。
    const created = (await requestJson('/api/v1/evidence-annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ block_id: block.id, quote: quoteInput.value, note: noteInput.value || null }),
    })) as EvidenceAnnotation
    annotations.value = [...annotations.value, created]
    // 成功路径直接清空（此时 saving 仍为 true，不能走带 guard 的 cancelSelection）。
    selectedBlock.value = null
    quoteInput.value = ''
    noteInput.value = ''
    annotationNotice.value = '已保存证据标注'
  } catch (cause) {
    annotationError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    savingAnnotation.value = false
  }
}

function askDeleteAnnotation(annotation: EvidenceAnnotation) {
  if (busy.value) return
  confirmDeleteId.value = annotation.id
  deleteAnnotationError.value = ''
}

function cancelDeleteAnnotation() {
  if (busy.value) return
  confirmDeleteId.value = ''
}

async function deleteAnnotation(annotation: EvidenceAnnotation) {
  if (busy.value) return
  deletingAnnotationId.value = annotation.id
  deleteAnnotationError.value = ''
  try {
    const response = await fetch(
      `/api/v1/materials/${encodeURIComponent(materialId)}/evidence-annotations/${encodeURIComponent(annotation.id)}`,
      { method: 'DELETE' },
    )
    if (response.status !== 204) {
      const body = await response.json().catch(() => null)
      const code = body && body.code ? body.code : String(response.status)
      throw new Error(body && body.message ? `${body.message}（${code}）` : `HTTP ${response.status}`)
    }
    annotations.value = annotations.value.filter(item => item.id !== annotation.id)
    links.value = links.value.filter(item => item.annotation_id !== annotation.id)
    if (linkAnnotation.value && linkAnnotation.value.id === annotation.id) {
      linkAnnotation.value = null
      linkCriterionId.value = ''
      linkRationale.value = ''
      linkError.value = ''
    }
    confirmDeleteId.value = ''
  } catch (cause) {
    deleteAnnotationError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    deletingAnnotationId.value = ''
  }
}

// —— 关联操作（adjudication 层：只记录“人判断相关”，不做满足判定） ——

function linksFor(criterionId: string) {
  return links.value.filter(item => item.criterion_id === criterionId)
}

function annotationFor(annotationId: string) {
  return annotations.value.find(item => item.id === annotationId) ?? null
}

function selectAnnotationToLink(annotation: EvidenceAnnotation) {
  if (busy.value) return
  linkAnnotation.value = annotation
  linkCriterionId.value = boundRubric.value?.criteria[0]?.id ?? ''
  linkRationale.value = ''
  linkError.value = ''
  linkNotice.value = ''
}

function cancelLink() {
  if (busy.value) return
  linkAnnotation.value = null
  linkCriterionId.value = ''
  linkRationale.value = ''
  linkError.value = ''
}

async function saveLink() {
  if (busy.value) return
  const annotation = linkAnnotation.value
  if (!annotation) {
    linkError.value = '请先选择要关联的引用'
    return
  }
  if (!linkCriterionId.value) {
    linkError.value = '请选择评分要求'
    return
  }
  if (!linkRationale.value.trim()) {
    linkError.value = 'rationale 不能为空'
    return
  }
  savingLink.value = true
  linkError.value = ''
  linkNotice.value = ''
  try {
    const created = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/criterion-evidence-links`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          annotation_id: annotation.id,
          criterion_id: linkCriterionId.value,
          rationale: linkRationale.value,
        }),
      },
    )) as CriterionEvidenceLink
    links.value = [...links.value, created]
    // 成功路径直接清空（saving 仍为 true，不能走带 guard 的 cancelLink）。
    linkAnnotation.value = null
    linkCriterionId.value = ''
    linkRationale.value = ''
    linkNotice.value = '已建立关联'
  } catch (cause) {
    linkError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    savingLink.value = false
  }
}

async function deleteLink(link: CriterionEvidenceLink) {
  if (busy.value) return
  deletingLinkId.value = link.id
  linkError.value = ''
  linkNotice.value = ''
  try {
    const response = await fetch(
      `/api/v1/materials/${encodeURIComponent(materialId)}/criterion-evidence-links/${encodeURIComponent(link.id)}`,
      { method: 'DELETE' },
    )
    if (response.status !== 204) {
      const body = await response.json().catch(() => null)
      const code = body && body.code ? body.code : String(response.status)
      throw new Error(body && body.message ? `${body.message}（${code}）` : `HTTP ${response.status}`)
    }
    links.value = links.value.filter(item => item.id !== link.id)
    linkNotice.value = '已移除关联'
  } catch (cause) {
    linkError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    deletingLinkId.value = ''
  }
}

// —— 锚点导航：定位并短暂高亮；找不到时明确提示 ——

function goToBlock(blockId: string) {
  if (!blockId) {
    anchorNotice.value = '该关联对应的 Block 已不存在'
    return
  }
  const element = typeof document !== 'undefined' ? document.getElementById(`block-${blockId}`) : null
  if (!element) {
    anchorNotice.value = '找不到该引用对应的 Block（可能已被移除）'
    return
  }
  anchorNotice.value = ''
  highlightedBlockId.value = blockId
  element.scrollIntoView({ behavior: 'smooth', block: 'center' })
  setTimeout(() => {
    if (highlightedBlockId.value === blockId) highlightedBlockId.value = ''
  }, 1600)
}

function lineFor(annotation: EvidenceAnnotation) {
  const block = material.value?.blocks.find(item => item.id === annotation.block_id)
  return block ? block.locator.index : '?'
}

const meta = computed(() => {
  const current = material.value
  if (!current) return ''
  return `${current.size_bytes} 字节 · ${current.line_count} 行 · ${current.blocks.length} 个 Block · sha256 ${current.sha256.slice(0, 12)}…`
})

async function init() {
  await Promise.all([loadMaterial(), loadAnnotations(), loadRubrics(), loadBinding(), loadLinks()])
  // 带 #block-* 打开/刷新：等材料与标注装载完成后再定位。
  if (route.hash.startsWith('#block-')) {
    goToBlock(route.hash.slice('#block-'.length))
  }
}

init()
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-10">
    <!-- 加载/错误状态：保留简单页头，不把半成品渲染成材料页。 -->
    <template v-if="loading || notFound || error">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-sm font-medium text-violet-400">MATERIALS</p>
          <h1 class="mt-2 text-3xl font-semibold tracking-tight">{{ notFound ? '找不到该材料' : 'Material' }}</h1>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
          <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">全部材料</UButton>
        </div>
      </div>
      <UCard v-if="loading" class="mt-8">
        <p class="text-sm text-slate-400">正在读取材料…</p>
      </UCard>
      <UCard v-else-if="notFound" class="mt-8">
        <p class="text-sm text-slate-400">该 ID 不存在，或本地数据库中没有这条记录。</p>
        <UButton class="mt-6" to="/materials" icon="i-lucide-folder-open">返回全部材料</UButton>
      </UCard>
      <UCard v-else-if="error" class="mt-8">
        <h2 class="text-lg font-medium">无法加载材料</h2>
        <p class="mt-2 text-sm text-slate-400">请求失败：{{ error }}</p>
        <UButton class="mt-6" icon="i-lucide-refresh-cw" @click="loadMaterial">重试</UButton>
      </UCard>
    </template>

    <!-- 已保存材料：只读 artifact 页，无上传控件、无临时状态、无保存按钮。 -->
    <template v-else-if="material">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm text-slate-500">
          <RouterLink to="/materials" class="text-slate-400 hover:text-violet-300">Materials</RouterLink>
          <span class="mx-1">/</span>
          <span class="text-slate-300">{{ material.filename }}</span>
        </p>
        <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">Workbench</UButton>
      </div>

      <MaterialHeader
        class="mt-6"
        :filename="material.filename"
        :meta="meta"
        badge-label="已保存"
        badge-color="success"
      >
        <span class="text-sm text-slate-400">保存于 {{ formatSavedAt(material.created_at) }}</span>
      </MaterialHeader>

      <p v-if="anchorNotice" class="mt-3 text-sm text-amber-300" role="status">{{ anchorNotice }}</p>

      <!-- 评分标准：只读标准仓 + 材料绑定 + 人工关联列表。 -->
      <section class="mt-4 rounded-lg border border-slate-800">
        <div class="flex items-center justify-between border-b border-slate-800 px-3 py-2">
          <h2 class="text-sm font-medium text-slate-300">评分标准</h2>
          <span class="text-xs text-slate-500">{{ binding ? '已绑定' : '尚未绑定' }}</span>
        </div>

        <p v-if="bindingLoading || rubricsLoading || linksLoading" class="px-3 py-3 text-sm text-slate-400">
          正在读取评分标准与关联…
        </p>
        <p
          v-else-if="bindingError || rubricsError || linksError"
          class="px-3 py-3 text-sm text-red-400"
          role="alert"
        >
          {{ bindingError || rubricsError || linksError }}
        </p>

        <template v-else-if="binding">
          <div class="px-3 py-3">
            <p class="text-sm text-slate-200">
              {{ boundRubric ? boundRubric.title : binding.rubric_id }}
              <span class="text-xs text-slate-500">
                · rev{{ binding.rubric_revision }} · 来源：{{ boundRubric ? boundRubric.source_note : '标准文件不可用' }}
              </span>
            </p>
            <p v-if="!boundRubric" class="mt-2 text-xs text-red-400">绑定的评分标准版本已不可用</p>
            <div v-else class="mt-3 space-y-3">
              <div
                v-for="criterion in boundRubric.criteria"
                :key="criterion.id"
                class="rounded-md border border-slate-800 p-3"
              >
                <p class="text-sm font-medium text-slate-200">{{ criterion.title }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ criterion.requirement }}</p>
                <div class="mt-2 space-y-2">
                  <div v-for="link in linksFor(criterion.id)" :key="link.id" class="rounded-md bg-slate-900/60 p-2">
                    <p class="font-mono text-xs text-slate-300">
                      “{{ annotationFor(link.annotation_id)?.source.quote ?? '（引用已删除）' }}”
                    </p>
                    <p class="mt-1 text-xs text-slate-500">用途：{{ link.rationale }}</p>
                    <div class="mt-2 flex flex-wrap items-center gap-2">
                      <UButton
                        size="xs"
                        color="neutral"
                        variant="ghost"
                        icon="i-lucide-crosshair"
                        @click="goToBlock(annotationFor(link.annotation_id)?.block_id ?? '')"
                      >
                        查看原文
                      </UButton>
                      <UButton
                        size="xs"
                        color="neutral"
                        variant="ghost"
                        icon="i-lucide-unlink"
                        :loading="deletingLinkId === link.id"
                        :disabled="busy"
                        @click="deleteLink(link)"
                      >
                        移除关联
                      </UButton>
                    </div>
                  </div>
                  <p v-if="linksFor(criterion.id).length === 0" class="text-xs text-slate-500">尚未关联引用</p>
                </div>
              </div>
            </div>
          </div>
        </template>

        <template v-else>
          <p v-if="rubrics.length === 0" class="px-3 py-3 text-sm text-slate-500">尚未配置评分标准</p>
          <ul v-else class="divide-y divide-slate-800">
            <li
              v-for="rubric in rubrics"
              :key="`${rubric.id}:${rubric.revision}`"
              class="flex items-center justify-between gap-3 px-3 py-2"
            >
              <div class="min-w-0">
                <p class="truncate text-sm text-slate-200">{{ rubric.title }}</p>
                <p class="mt-0.5 truncate text-xs text-slate-500">
                  {{ rubric.source_note }} · rev{{ rubric.revision }} · {{ rubric.criteria.length }} 项
                </p>
              </div>
              <UButton size="sm" :loading="bindingBusy" :disabled="busy" @click="bindRubric(rubric)">绑定</UButton>
            </li>
          </ul>
        </template>

        <p v-if="bindingNotice" class="border-t border-slate-800 px-3 py-2 text-xs text-emerald-400">
          {{ bindingNotice }}
        </p>
        <p v-if="linkNotice" class="border-t border-slate-800 px-3 py-2 text-xs text-emerald-400">{{ linkNotice }}</p>
      </section>

      <!-- 证据区：标注列表 + 反馈；表单在选中的 Block 行内展开。 -->
      <section class="mt-4 rounded-lg border border-slate-800">
        <div class="flex items-center justify-between border-b border-slate-800 px-3 py-2">
          <h2 class="text-sm font-medium text-slate-300">证据</h2>
          <span class="text-xs text-slate-500">{{ annotations.length }} 条标注</span>
        </div>
        <p v-if="annotationsLoading" class="px-3 py-3 text-sm text-slate-400">正在读取证据标注…</p>
        <p v-else-if="annotationsError" class="px-3 py-3 text-sm text-red-400" role="alert">{{ annotationsError }}</p>
        <template v-else>
          <p v-if="annotations.length === 0" class="px-3 py-3 text-sm text-slate-500">
            还没有证据标注；在下方 Block 行点击“标注”，quote 会预填整块原文。
          </p>
          <ul v-else class="divide-y divide-slate-800">
            <li v-for="item in annotations" :key="item.id" class="px-3 py-2">
              <p class="font-mono text-sm text-slate-200">“{{ item.source.quote }}”</p>
              <p class="mt-1 text-xs text-slate-500">
                line {{ lineFor(item) }} · {{ item.proposed_by }}<span v-if="item.note"> · {{ item.note }}</span>
              </p>
              <div class="mt-2 flex flex-wrap items-center gap-2">
                <UButton
                  size="xs"
                  color="neutral"
                  variant="ghost"
                  icon="i-lucide-link"
                  :disabled="busy || !binding"
                  @click="selectAnnotationToLink(item)"
                >
                  关联
                </UButton>
                <template v-if="confirmDeleteId === item.id">
                  <span class="text-xs text-red-300">确认删除该标注？其关联会一起清除</span>
                  <UButton
                    size="xs"
                    color="error"
                    variant="subtle"
                    :loading="deletingAnnotationId === item.id"
                    @click="deleteAnnotation(item)"
                  >
                    确认删除
                  </UButton>
                  <UButton size="xs" color="neutral" variant="ghost" :disabled="busy" @click="cancelDeleteAnnotation">
                    取消
                  </UButton>
                </template>
                <UButton
                  v-else
                  size="xs"
                  color="neutral"
                  variant="ghost"
                  icon="i-lucide-trash-2"
                  :disabled="busy"
                  @click="askDeleteAnnotation(item)"
                >
                  删除
                </UButton>
              </div>
              <div
                v-if="linkAnnotation && linkAnnotation.id === item.id"
                class="mt-2 rounded-md border border-slate-800 bg-slate-950/60 p-3"
              >
                <p class="text-xs text-slate-500">
                  关联到评分要求（{{ boundRubric ? boundRubric.title : '尚未绑定评分标准' }}）
                </p>
                <select
                  v-model="linkCriterionId"
                  class="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200"
                >
                  <option disabled value="">选择评分要求</option>
                  <option v-for="criterion in boundRubric?.criteria ?? []" :key="criterion.id" :value="criterion.id">
                    {{ criterion.title }}
                  </option>
                </select>
                <textarea
                  v-model="linkRationale"
                  rows="2"
                  placeholder="rationale（必填：为什么这条引用与该项相关）"
                  class="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200"
                ></textarea>
                <div class="mt-2 flex items-center gap-2">
                  <UButton
                    size="sm"
                    :loading="savingLink"
                    :disabled="savingLink || !boundRubric"
                    @click="saveLink"
                  >
                    {{ savingLink ? '正在保存…' : '建立关联' }}
                  </UButton>
                  <UButton size="sm" color="neutral" variant="ghost" :disabled="savingLink" @click="cancelLink">
                    取消
                  </UButton>
                </div>
                <p v-if="linkError" class="mt-2 text-xs text-red-400" role="alert">{{ linkError }}</p>
              </div>
            </li>
          </ul>
        </template>
        <p v-if="deleteAnnotationError" class="border-t border-slate-800 px-3 py-2 text-xs text-red-400" role="alert">
          {{ deleteAnnotationError }}
        </p>
        <p v-if="annotationNotice" class="border-t border-slate-800 px-3 py-2 text-xs text-emerald-400">
          {{ annotationNotice }}
        </p>
      </section>

      <div class="mt-4">
        <BlockList
          :blocks="material.blocks"
          :annotated-counts="annotatedCounts"
          :highlight-block-id="highlightedBlockId"
        >
          <template #cite="{ block }">
            <UButton
              v-if="!selectedBlock || selectedBlock.id !== block.id"
              class="ml-auto shrink-0"
              size="xs"
              color="neutral"
              variant="ghost"
              icon="i-lucide-quote"
              :disabled="busy"
              @click="selectBlock(block)"
            >
              标注
            </UButton>
            <div v-else class="w-full rounded-md border border-slate-800 bg-slate-950/60 p-3">
              <p class="text-xs text-slate-500">引用 line {{ block.locator.index }} · quote 必须是原文子串，可改窄</p>
              <input
                v-model="quoteInput"
                class="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-sm text-slate-200"
              />
              <textarea
                v-model="noteInput"
                rows="2"
                placeholder="note（可选）"
                class="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200"
              ></textarea>
              <div class="mt-2 flex items-center gap-2">
                <UButton size="sm" :loading="savingAnnotation" :disabled="savingAnnotation" @click="saveAnnotation">
                  {{ savingAnnotation ? '正在保存…' : '保存标注' }}
                </UButton>
                <UButton size="sm" color="neutral" variant="ghost" :disabled="savingAnnotation" @click="cancelSelection">
                  取消
                </UButton>
              </div>
              <p v-if="annotationError" class="mt-2 text-xs text-red-400" role="alert">{{ annotationError }}</p>
            </div>
          </template>
        </BlockList>
      </div>
    </template>
  </main>
</template>
