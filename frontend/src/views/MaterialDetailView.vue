<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import type { SavedMaterial } from '../types/contracts'
import BlockList from '../components/BlockList.vue'
import MaterialHeader from '../components/MaterialHeader.vue'
import { formatSavedAt } from '../utils/format'

const route = useRoute()
const materialId = String(route.params.materialId)

const material = ref<SavedMaterial | null>(null)
const loading = ref(true)
const notFound = ref(false)
const error = ref('')

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

const meta = computed(() => {
  const current = material.value
  if (!current) return ''
  return `${current.size_bytes} 字节 · ${current.line_count} 行 · ${current.blocks.length} 个 Block · sha256 ${current.sha256.slice(0, 12)}…`
})

loadMaterial()
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

      <div class="mt-4">
        <BlockList :blocks="material.blocks" />
      </div>
    </template>
  </main>
</template>
