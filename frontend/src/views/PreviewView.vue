<script setup lang="ts">
import { ref } from 'vue'
import type { MarkdownPreview } from '../types/contracts'

const selectedFile = ref<File | null>(null)
const loading = ref(false)
const error = ref('')
const preview = ref<MarkdownPreview | null>(null)

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  selectedFile.value = input.files && input.files[0] ? input.files[0] : null
  // 换文件时先清空旧结果，避免旧结果被当成新文件的结果。
  preview.value = null
  error.value = ''
}

async function upload() {
  const file = selectedFile.value
  if (!file) {
    error.value = '请先选择一份 .md 文件'
    return
  }
  loading.value = true
  error.value = ''
  preview.value = null
  try {
    const form = new FormData()
    form.append('file', file)
    const response = await fetch('/api/v1/preview/markdown', { method: 'POST', body: form })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    preview.value = body as MarkdownPreview
  } catch (cause) {
    // 失败时不保留任何结果，也不退回本地数据。
    preview.value = null
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-16">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p class="text-sm font-medium text-violet-400">MATERIAL PREVIEW / TEMPORARY</p>
        <h1 class="mt-2 text-3xl font-semibold tracking-tight">材料预览</h1>
        <p class="mt-2 text-sm text-slate-400">上传一份 Markdown，查看程序生成的 Block 与原始行号。</p>
      </div>
      <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">返回 Workbench</UButton>
    </div>

    <div class="mt-6 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-200">
      临时预览，尚未保存；刷新后需重新上传。
    </div>

    <UCard class="mt-6">
      <h2 class="text-lg font-medium">选择文件</h2>
      <p class="mt-2 text-sm text-slate-400">仅支持 UTF-8 Markdown（.md），单文件不超过 1 MiB；后端会再次校验。</p>
      <input
        type="file"
        accept=".md,text/markdown"
        class="mt-4 block w-full text-sm text-slate-400 file:mr-4 file:rounded-md file:border-0 file:bg-slate-700 file:px-4 file:py-2 file:text-sm file:text-slate-100"
        @change="onFileChange"
      />
      <div class="mt-4 flex items-center gap-4">
        <UButton icon="i-lucide-upload" :loading="loading" :disabled="!selectedFile" @click="upload">生成预览</UButton>
        <p class="text-sm text-slate-400">{{ selectedFile ? selectedFile.name : '尚未选择文件' }}</p>
      </div>
      <p v-if="error" class="mt-4 text-sm text-red-400" role="alert">{{ error }}</p>
    </UCard>

    <UCard v-if="preview" class="mt-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 class="text-lg font-medium">{{ preview.filename }}</h2>
        <UBadge color="neutral" variant="subtle">临时 · 未保存</UBadge>
      </div>
      <p class="mt-2 break-all text-sm text-slate-400">
        {{ preview.size_bytes }} 字节 · {{ preview.line_count }} 行 · {{ preview.blocks.length }} 个 Block · sha256 {{ preview.sha256.slice(0, 12) }}…
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
    </UCard>
  </main>
</template>
