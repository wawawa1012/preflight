<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { Block, EvidenceAnnotation, SavedMaterial } from '../types/contracts'
import BlockList from '../components/BlockList.vue'
import MaterialHeader from '../components/MaterialHeader.vue'
import { formatSavedAt } from '../utils/format'

const route = useRoute()
const materialId = String(route.params.materialId)

const material = ref<SavedMaterial | null>(null)
const loading = ref(true)
const notFound = ref(false)
const error = ref('')

// 证据区状态：选 Block → 行内表单（quote 预填整块）→ 保存 → 列表。
const annotations = ref<EvidenceAnnotation[]>([])
const annotationsLoading = ref(false)
const annotationsError = ref('')
const selectedBlock = ref<Block | null>(null)
const quoteInput = ref('')
const noteInput = ref('')
const savingAnnotation = ref(false)
const annotationError = ref('')
const annotationNotice = ref('')

// 证据保存互斥：进行中不能改选 Block、不能重复提交（沿用 preview race 纪律）。
const evidenceBusy = computed(() => savingAnnotation.value)

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
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/evidence-annotations`)
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    annotations.value = body as EvidenceAnnotation[]
  } catch (cause) {
    annotationsError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    annotationsLoading.value = false
  }
}

function selectBlock(block: Block) {
  if (evidenceBusy.value) return
  selectedBlock.value = block
  quoteInput.value = block.text
  noteInput.value = ''
  annotationError.value = ''
  annotationNotice.value = ''
}

function cancelSelection() {
  if (evidenceBusy.value) return
  selectedBlock.value = null
  quoteInput.value = ''
  noteInput.value = ''
  annotationError.value = ''
}

async function saveAnnotation() {
  if (evidenceBusy.value) return
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
    const response = await fetch('/api/v1/evidence-annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ block_id: block.id, quote: quoteInput.value, note: noteInput.value || null }),
    })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(
        body && body.message ? `${body.message}（${body.code ?? response.status}）` : `HTTP ${response.status}`,
      )
    }
    annotations.value = [...annotations.value, body as EvidenceAnnotation]
    // 成功路径直接清空（此时 saving 仍为 true，不能走带 guard 的 cancelSelection）。
    selectedBlock.value = null
    quoteInput.value = ''
    noteInput.value = ''
    annotationError.value = ''
    annotationNotice.value = '已保存证据标注'
  } catch (cause) {
    annotationError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    savingAnnotation.value = false
  }
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

loadMaterial()
loadAnnotations()
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
            </li>
          </ul>
        </template>
        <p v-if="annotationNotice" class="border-t border-slate-800 px-3 py-2 text-xs text-emerald-400">
          {{ annotationNotice }}
        </p>
      </section>

      <div class="mt-4">
        <BlockList :blocks="material.blocks">
          <template #cite="{ block }">
            <UButton
              v-if="!selectedBlock || selectedBlock.id !== block.id"
              class="ml-auto shrink-0"
              size="xs"
              color="neutral"
              variant="ghost"
              icon="i-lucide-quote"
              :disabled="evidenceBusy"
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
