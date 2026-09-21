<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { SourcePreview } from '../types/contracts'
import BlockList from '../components/BlockList.vue'
import MaterialHeader from '../components/MaterialHeader.vue'
import { formatLabel } from '../utils/formatLabel'

// /materials/new 是添加材料工作台：选择文件 → 校验并预览 → 保存；
// 保存成功后 router.replace 到稳定的 /materials/:id/report，本页不保留持久身份。
// 从「开始新审查」来时（?return=review-new）：本页只消费 return 并上报新 material id，
// 不携带也不解释任何审查/绑定规则。
const router = useRouter()
const route = useRoute()

const returnTo = computed(() => (route.query.return === 'review-new' ? '/reviews/new' : null))

const selectedFile = ref<File | null>(null)
const previewedFile = ref<File | null>(null)
const preview = ref<SourcePreview | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const dragActive = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

// 上传与保存互斥：任一进行中都不能再开始另一个，也不能换文件。
const busy = computed(() => loading.value || saving.value)

const steps = ['上传文件', '校验并预览', '保存为稳定材料']
// 步骤条只反映选择进度；生成预览后整个上传区退场，不再需要步骤条。
const currentStep = computed(() => (selectedFile.value ? 1 : 0))

// 与 input accept 同一集合：前端只做后缀提示，真实解析以服务端为准。
const SUPPORTED_EXTENSIONS = ['md', 'markdown', 'txt', 'docx']
const SUPPORTED_EXTENSION_HINT = '只支持 .md / .txt / .docx 文件'

function hasSupportedExtension(name: string) {
  const lower = name.toLowerCase()
  return SUPPORTED_EXTENSIONS.some((extension) => lower.endsWith(`.${extension}`))
}

// parser 错误码 → 人话；其他错误保持通用 HTTP/未知错误风格。
const PREVIEW_ERROR_MESSAGES: Record<string, string> = {
  invalid_extension: SUPPORTED_EXTENSION_HINT,
  invalid_encoding: '文件编码无法识别，请使用 UTF-8 文本',
  invalid_zip: '这份 Word 文档无法解析，请另存为标准 .docx 后重试',
  invalid_xml: '这份 Word 文档无法解析，请另存为标准 .docx 后重试',
  invalid_docx: '这份 Word 文档无法解析，请另存为标准 .docx 后重试',
  unsupported_structure: '这份 Word 文档含有暂不支持的结构（如合并单元格、嵌套表格、文本框），未做展开',
  archive_too_large: '文件超过大小限制',
}

function previewErrorMessage(body: { code?: string; message?: string } | null, status: number) {
  const code = body?.code
  if (code && PREVIEW_ERROR_MESSAGES[code]) return PREVIEW_ERROR_MESSAGES[code]
  if (body?.message) return body.message
  return `HTTP ${status}`
}

const previewMeta = computed(() => {
  const current = preview.value
  if (!current) return ''
  const parts = [formatLabel(current.format), `${current.size_bytes} 字节`]
  // docx 无真实行号：line_count 为 null 时不显示，绝不伪造「null 行」。
  if (typeof current.line_count === 'number') parts.push(`${current.line_count} 行`)
  parts.push(`${current.blocks.length} 段原文`)
  return parts.join(' · ')
})

// 选择文件的唯一入口：input change 与 drag/drop 都走这里，保证校验与清状态一致。
function acceptFile(file: File | null) {
  if (busy.value) return
  // 换文件时先清空旧结果，避免旧结果被当成新文件的结果。
  preview.value = null
  previewedFile.value = null
  error.value = ''
  if (file && !hasSupportedExtension(file.name)) {
    selectedFile.value = null
    error.value = SUPPORTED_EXTENSION_HINT
    return
  }
  selectedFile.value = file
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  acceptFile(input.files && input.files[0] ? input.files[0] : null)
}

function openFilePicker() {
  if (busy.value) return
  fileInput.value?.click()
}

function onDragOver(event: DragEvent) {
  if (busy.value) return
  event.preventDefault()
  dragActive.value = true
}

function onDragLeave() {
  dragActive.value = false
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  dragActive.value = false
  if (busy.value) return
  const files = event.dataTransfer ? event.dataTransfer.files : null
  acceptFile(files && files.length > 0 ? files[0] : null)
  // drop 不经过 input；清掉 input 避免旧值与所选文件不一致。
  if (fileInput.value) fileInput.value.value = ''
}

// 低权重的“更换文件”：回到选择状态，不离开当前页。
function resetFile() {
  if (busy.value) return
  selectedFile.value = null
  previewedFile.value = null
  preview.value = null
  error.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

async function upload() {
  if (busy.value) return
  const file = selectedFile.value
  if (!file) {
    error.value = '请先选择一份 .md / .txt / .docx 文件'
    return
  }
  loading.value = true
  error.value = ''
  preview.value = null
  previewedFile.value = null
  try {
    const form = new FormData()
    form.append('file', file)
    const response = await fetch('/api/v1/preview', { method: 'POST', body: form })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(previewErrorMessage(body, response.status))
    }
    preview.value = body as SourcePreview
    previewedFile.value = file
  } catch (cause) {
    // 失败时不保留任何结果，也不退回本地数据。
    preview.value = null
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function saveMaterial() {
  if (busy.value) return
  const file = previewedFile.value
  if (!file) {
    error.value = '没有可保存的预览，请先生成预览'
    return
  }
  saving.value = true
  error.value = ''
  try {
    // 只上传原文件；blocks/locator 由后端重新解析，不信任浏览器回传。
    const form = new FormData()
    form.append('file', file)
    const response = await fetch('/api/v1/materials', { method: 'POST', body: form })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    const saved = body as { id: string }
    // 保存成功：来自 Wizard 时带新 id 返回（由 Wizard 自动选中）；否则进材料报告页。
    if (returnTo.value) {
      router.replace(`${returnTo.value}?added=${saved.id}`)
    } else {
      router.replace(`/materials/${saved.id}/report`)
    }
  } catch (cause) {
    // 保存失败：保持未保存状态，不能显示“已保存”。
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-10">
    <p v-if="returnTo" class="mb-4 rounded-md bg-slate-900/60 px-3 py-2 text-xs text-slate-400">
      从「开始新审查」来到此处；保存后将返回并自动选中这份材料。
    </p>

    <!-- 状态一：选择文件。上传区是当前唯一任务区。 -->
    <template v-if="!preview">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-sm font-medium text-violet-400">材料 · 添加</p>
          <h1 class="mt-2 text-3xl font-semibold tracking-tight">添加材料</h1>
          <p class="mt-2 text-sm text-slate-400">
            保存后即可开始审查，每个结论都能定位到原文（行 / 段 / 表格单元格）。
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <UButton v-if="returnTo" :to="returnTo" color="neutral" variant="subtle" icon="i-lucide-arrow-left">返回创建审查</UButton>
          <UButton v-else to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
          <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">全部材料</UButton>
        </div>
      </div>

      <ol class="mt-8 flex flex-wrap gap-x-8 gap-y-3 text-sm">
        <li
          v-for="(step, index) in steps"
          :key="step"
          class="flex items-center gap-2"
          :class="index === currentStep ? 'text-slate-100' : 'text-slate-500'"
        >
          <span
            class="flex h-5 w-5 items-center justify-center rounded-full border text-xs"
            :class="index === currentStep ? 'border-violet-500 text-violet-300' : 'border-slate-700'"
          >
            {{ index + 1 }}
          </span>
          {{ step }}
        </li>
      </ol>
      <p class="mt-3 text-xs text-slate-500">位置由程序生成，不由模型编造。</p>

      <div
        class="mt-6 cursor-pointer rounded-lg border-2 border-dashed px-6 py-10 text-center transition"
        :class="dragActive ? 'border-violet-500/70 bg-violet-500/5' : 'border-slate-700 hover:border-slate-500'"
        role="button"
        tabindex="0"
        @click="openFilePicker"
        @keydown.enter="openFilePicker"
        @dragover="onDragOver"
        @dragleave="onDragLeave"
        @drop="onDrop"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".md,.markdown,.txt,.docx"
          :disabled="busy"
          class="sr-only"
          @change="onFileChange"
        />
        <template v-if="!selectedFile">
          <UIcon name="i-lucide-file-up" class="mx-auto text-3xl text-slate-500" />
          <p class="mt-4 text-sm text-slate-300">点击选择或拖入 .md / .txt / .docx 文件</p>
          <p class="mt-1 text-xs text-slate-500">.md / .txt / .docx · 单文件不超过 1 MiB · 保存时由服务端重新解析</p>
        </template>
        <template v-else>
          <UIcon name="i-lucide-file-check" class="mx-auto text-3xl text-violet-400" />
          <p class="mt-4 text-sm font-medium text-slate-200">{{ selectedFile.name }}</p>
          <p class="mt-1 text-xs text-slate-500">{{ selectedFile.size }} 字节 · 待校验</p>
          <div class="mt-6 flex items-center justify-center gap-3">
            <UButton icon="i-lucide-scan-search" :loading="loading" :disabled="!selectedFile || busy" @click.stop="upload">
              {{ loading ? '正在校验…' : '生成预览' }}
            </UButton>
            <UButton color="neutral" variant="ghost" :disabled="busy" @click.stop="resetFile">重新选择</UButton>
          </div>
        </template>
      </div>
      <p v-if="error" class="mt-4 text-sm text-red-400" role="alert">{{ error }}</p>
    </template>

    <!-- 状态二：已生成预览。上传表单退场，保存动作固定在 sticky 身份头。 -->
    <template v-else>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm text-slate-500">
          <RouterLink to="/materials" class="text-slate-400 hover:text-violet-300">材料</RouterLink>
          <span class="mx-1">/</span>
          <span class="text-slate-300">添加材料</span>
        </p>
        <div class="flex flex-wrap items-center gap-3">
          <UButton v-if="returnTo" :to="returnTo" color="neutral" variant="subtle" icon="i-lucide-arrow-left">返回创建审查</UButton>
          <UButton v-else to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
          <UButton color="neutral" variant="subtle" icon="i-lucide-refresh-cw" :disabled="busy" @click="resetFile">
            更换文件
          </UButton>
        </div>
      </div>

      <MaterialHeader
        class="mt-6"
        :filename="preview.filename"
        :meta="previewMeta"
        badge-label="临时 · 未保存"
        badge-color="warning"
        hint="临时预览，刷新后丢失；保存后即可审查，并能定位到原文。"
      >
        <UButton icon="i-lucide-save" :loading="saving" :disabled="!previewedFile || busy" @click="saveMaterial">
          {{ saving ? '正在保存…' : '保存材料' }}
        </UButton>
      </MaterialHeader>

      <div class="mt-4">
        <BlockList :blocks="preview.blocks" />
      </div>
      <p v-if="error" class="mt-4 text-sm text-red-400" role="alert">{{ error }}</p>
    </template>
  </main>
</template>
