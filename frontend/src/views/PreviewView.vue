<script setup lang="ts">
import { computed, ref } from 'vue'
import type { MarkdownPreview, SavedMaterial } from '../types/contracts'

// 当前展示的材料：来自临时预览（id 为 null）或已保存材料（id 稳定）。
type DisplayedMaterial = {
  id: string | null
  filename: string
  size_bytes: number
  line_count: number
  sha256: string
  created_at: string | null
  blocks: MarkdownPreview['blocks']
}

const selectedFile = ref<File | null>(null)
const previewedFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const preview = ref<DisplayedMaterial | null>(null)
const loading = ref(false)
const saving = ref(false)
const loadingRecent = ref(false)
const error = ref('')
const notice = ref('')

// 三个异步操作（生成预览/保存/读取 recent）统一互斥：任一进行中都不能再开始或换文件。
const busy = computed(() => loading.value || saving.value || loadingRecent.value)

function displayedFromPreview(data: MarkdownPreview): DisplayedMaterial {
  return {
    id: null,
    filename: data.filename,
    size_bytes: data.size_bytes,
    line_count: data.line_count,
    sha256: data.sha256,
    created_at: null,
    blocks: data.blocks,
  }
}

function displayedFromSaved(data: SavedMaterial): DisplayedMaterial {
  return {
    id: data.id,
    filename: data.filename,
    size_bytes: data.size_bytes,
    line_count: data.line_count,
    sha256: data.sha256,
    created_at: data.created_at,
    blocks: data.blocks,
  }
}

function onFileChange(event: Event) {
  if (busy.value) return
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files && input.files[0] ? input.files[0] : null
  // 换文件时先清空旧结果与保存状态，避免旧结果被当成新文件的结果。
  preview.value = null
  previewedFile.value = null
  error.value = ''
  notice.value = ''
}

async function upload() {
  if (busy.value) return
  const file = selectedFile.value
  if (!file) {
    error.value = '请先选择一份 .md 文件'
    return
  }
  loading.value = true
  error.value = ''
  notice.value = ''
  preview.value = null
  previewedFile.value = null
  try {
    const form = new FormData()
    form.append('file', file)
    const response = await fetch('/api/v1/preview/markdown', { method: 'POST', body: form })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    preview.value = displayedFromPreview(body as MarkdownPreview)
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
  notice.value = ''
  try {
    // 只上传原文件；blocks/locator 由后端重新解析，不信任浏览器回传。
    const form = new FormData()
    form.append('file', file)
    const response = await fetch('/api/v1/materials', { method: 'POST', body: form })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    const saved = body as SavedMaterial
    preview.value = displayedFromSaved(saved)
    notice.value = `已保存材料 ${saved.id}`
  } catch (cause) {
    // 保存失败：preview 保持未保存状态，不能显示“已保存”。
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    saving.value = false
  }
}

async function loadRecent() {
  if (busy.value) return
  loadingRecent.value = true
  error.value = ''
  notice.value = ''
  try {
    const response = await fetch('/api/v1/materials/recent')
    const body = await response.json().catch(() => null)
    if (response.status === 404) {
      notice.value = body && body.message ? body.message : '还没有已保存的材料'
      return
    }
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    const saved = body as SavedMaterial
    preview.value = displayedFromSaved(saved)
    // 展示的是持久化材料，清掉与之无关的临时文件引用，避免过期状态。
    selectedFile.value = null
    previewedFile.value = null
    if (fileInput.value) fileInput.value.value = ''
    notice.value = `已读取最近保存的材料 ${saved.id}`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loadingRecent.value = false
  }
}
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-16">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="text-sm font-medium text-violet-400">MATERIAL PREVIEW / TEMPORARY</p>
        <h1 class="mt-2 text-3xl font-semibold tracking-tight">材料预览</h1>
        <p class="mt-2 text-sm text-slate-400">上传一份 Markdown，查看程序生成的 Block 与原始行号；可保存到本地 SQLite。</p>
      </div>
      <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">返回 Workbench</UButton>
    </div>

    <div
      v-if="!preview || !preview.id"
      class="mt-6 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-200"
    >
      临时预览，尚未保存；刷新后需重新上传。点击“保存材料”后才会持久化。
    </div>
    <div v-else class="mt-6 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-4 text-sm text-emerald-200">
      已保存材料：刷新页面或重启后端后，仍可用“读取最近保存的材料”恢复。
    </div>

    <UCard class="mt-6">
      <h2 class="text-lg font-medium">选择文件</h2>
      <p class="mt-2 text-sm text-slate-400">仅支持 UTF-8 Markdown（.md），单文件不超过 1 MiB；后端会再次校验。</p>
      <input
        ref="fileInput"
        type="file"
        accept=".md,text/markdown"
        :disabled="busy"
        class="mt-4 block w-full text-sm text-slate-400 file:mr-4 file:rounded-md file:border-0 file:bg-slate-700 file:px-4 file:py-2 file:text-sm file:text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
        @change="onFileChange"
      />
      <div class="mt-4 flex flex-wrap items-center gap-3">
        <UButton icon="i-lucide-upload" :loading="loading" :disabled="!selectedFile || busy" @click="upload">
          {{ loading ? '正在上传…' : '生成预览' }}
        </UButton>
        <UButton
          icon="i-lucide-history"
          color="neutral"
          variant="subtle"
          :loading="loadingRecent"
          :disabled="busy"
          @click="loadRecent"
        >
          读取最近保存的材料
        </UButton>
        <p class="text-sm text-slate-400">{{ selectedFile ? selectedFile.name : '尚未选择文件' }}</p>
      </div>
      <p v-if="error" class="mt-4 text-sm text-red-400" role="alert">{{ error }}</p>
      <p v-if="notice" class="mt-4 text-sm text-slate-300" role="status">{{ notice }}</p>
    </UCard>

    <UCard v-if="preview" class="mt-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-lg font-medium">{{ preview.filename }}</h2>
        <UBadge :color="preview.id ? 'success' : 'neutral'" variant="subtle">
          {{ preview.id ? '已保存' : '临时 · 未保存' }}
        </UBadge>
      </div>
      <p class="mt-2 break-all text-sm text-slate-400">
        {{ preview.size_bytes }} 字节 · {{ preview.line_count }} 行 · {{ preview.blocks.length }} 个 Block · sha256 {{ preview.sha256.slice(0, 12) }}…
      </p>
      <p v-if="preview.id" class="mt-1 break-all font-mono text-xs text-slate-500">
        material id：{{ preview.id }} · 保存于 {{ preview.created_at }}
      </p>

      <p v-if="preview.blocks.length === 0" class="mt-6 text-sm text-slate-400">
        这个文件没有生成任何 Block：只有长度为 0 的空行不生成 Block（但仍计入行号）。
      </p>
      <div v-else class="mt-4 divide-y divide-slate-800 overflow-hidden rounded-lg border border-slate-800">
        <div
          v-for="block in preview.blocks"
          :key="block.id"
          class="flex items-start gap-3 px-3 py-2 hover:bg-slate-800/40"
        >
          <span class="w-24 shrink-0 whitespace-nowrap pt-0.5 font-mono text-xs">
            <span class="text-slate-300">line {{ block.locator.index }}</span>
            <span class="ml-1 text-slate-600">#{{ block.ordinal }}</span>
          </span>
          <p class="min-w-0 flex-1 whitespace-pre-wrap break-words font-mono text-sm text-slate-200">{{ block.text }}</p>
        </div>
      </div>

      <div v-if="!preview.id" class="mt-4">
        <UButton
          icon="i-lucide-save"
          :loading="saving"
          :disabled="!previewedFile || busy"
          @click="saveMaterial"
        >
          {{ saving ? '正在保存…' : '保存材料' }}
        </UButton>
      </div>
    </UCard>
  </main>
</template>
