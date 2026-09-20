<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import type { MaterialSummary } from '../../types/contracts'
import type { ReviewMaterialEntry } from '../../types/review'
import { ApiFailure, reviewsApi } from '../../services/reviews'
import { reviewContextKey } from './reviewContext'
import { materialIdentity } from '../../utils/materialIdentity'
import EmptyState from '../../components/review/EmptyState.vue'

// 材料视角：管理本次审查的成员。身份是 label（filename 只是出处）。
// 所有写操作走同一 upsert/remove；绑定冲突由后端裁决，前端只呈现为 amber 行内提示。
const context = inject(reviewContextKey)
if (!context) throw new Error('ReviewMembersView 必须在 ReviewWorkspaceView 内使用')
const { review, refresh } = context

const library = ref<MaterialSummary[]>([])
const loading = ref(true)
const loadError = ref('')

// 本地顺序：后端按 position, material_id 排好；这里只在重排时先乐观更新，再回写 position。
const ordered = ref<ReviewMaterialEntry[]>([])
const labels = ref<Record<string, string>>({})

const addMaterialId = ref('')
const addLabel = ref('')

const mutating = ref(false)
const mutationError = ref<{ message: string; conflict: boolean } | null>(null)

const pendingRemove = ref<ReviewMaterialEntry | null>(null)
const removing = ref(false)
const removeError = ref('')

watch(
  () => review.value?.materials,
  (list) => {
    const entries = list ?? []
    ordered.value = [...entries]
    const next: Record<string, string> = {}
    for (const entry of entries) next[entry.material_id] = entry.label
    labels.value = next
  },
  { immediate: true },
)

const filenameById = computed(() => new Map(library.value.map((item) => [item.id, item.filename])))

function filenameOf(materialId: string) {
  return filenameById.value.get(materialId) ?? '未知材料'
}

// 成员行身份：label 为主、filename 为次级出处；相同只显示一次。
function identityOf(entry: ReviewMaterialEntry) {
  return materialIdentity(entry.label, filenameOf(entry.material_id))
}

const candidates = computed(() =>
  library.value.filter((item) => !ordered.value.some((entry) => entry.material_id === item.id)),
)

async function loadLibrary() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetch('/api/v1/materials')
    const body = await response.json().catch(() => null)
    if (!response.ok) throw new Error(body?.message ?? `HTTP ${response.status}`)
    library.value = Array.isArray(body) ? (body as MaterialSummary[]) : []
  } catch (cause) {
    loadError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

// 每次 mutation 后统一 refresh()：列表顺序与 label 都以服务端为准，不在前端另存一份真相。
async function runMutation(action: () => Promise<void>) {
  if (mutating.value) return
  mutating.value = true
  mutationError.value = null
  try {
    await action()
  } catch (cause) {
    if (cause instanceof ApiFailure && cause.code === 'binding_conflict') {
      mutationError.value = { message: cause.message, conflict: true }
    } else {
      mutationError.value = { message: cause instanceof Error ? cause.message : '未知错误', conflict: false }
    }
  } finally {
    await refresh()
    mutating.value = false
  }
}

function saveLabel(entry: ReviewMaterialEntry) {
  const draft = (labels.value[entry.material_id] ?? '').trim()
  // 空 label 会被后端契约拒绝（min_length=1）：不发送，恢复原值。
  if (draft === '' || draft === entry.label) {
    labels.value = { ...labels.value, [entry.material_id]: entry.label }
    return
  }
  void runMutation(async () => {
    await reviewsApi.upsertMaterial(reviewId.value, entry.material_id, { label: draft })
  })
}

function onLabelEnter(event: KeyboardEvent) {
  ;(event.target as HTMLInputElement).blur()
}

function move(index: number, delta: number) {
  const target = index + delta
  if (target < 0 || target >= ordered.value.length) return
  const next = [...ordered.value]
  const [item] = next.splice(index, 1)
  next.splice(target, 0, item)
  ordered.value = next
  // 只对 position 真正变化的成员 PUT，写成连续 0..n-1。
  const changed = next
    .map((entry, position) => ({ entry, position }))
    .filter(({ entry, position }) => entry.position !== position)
  void runMutation(async () => {
    for (const { entry, position } of changed) {
      await reviewsApi.upsertMaterial(reviewId.value, entry.material_id, { position })
    }
  })
}

function addMember() {
  const materialId = addMaterialId.value
  if (materialId === '') return
  const label = addLabel.value.trim()
  void runMutation(async () => {
    await reviewsApi.upsertMaterial(reviewId.value, materialId, label === '' ? {} : { label })
    addMaterialId.value = ''
    addLabel.value = ''
  })
}

function requestRemove(entry: ReviewMaterialEntry) {
  if (removing.value) return
  removeError.value = ''
  pendingRemove.value = entry
}

function cancelRemove() {
  if (removing.value) return
  pendingRemove.value = null
  removeError.value = ''
}

async function confirmRemove() {
  const entry = pendingRemove.value
  if (!entry || removing.value) return
  removing.value = true
  removeError.value = ''
  try {
    await reviewsApi.removeMaterial(reviewId.value, entry.material_id)
    pendingRemove.value = null
    await refresh()
  } catch (cause) {
    removeError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    removing.value = false
  }
}

const reviewId = computed(() => review.value?.id ?? '')

loadLibrary()
</script>

<template>
  <div class="space-y-8">
    <section>
      <div class="flex flex-wrap items-baseline justify-between gap-3">
        <h2 class="text-sm font-medium tracking-wide text-slate-200">审查材料</h2>
        <span class="text-xs text-slate-500">{{ ordered.length }} 份 · label 是本次审查中的名字</span>
      </div>

      <p v-if="loading" class="mt-4 text-sm text-slate-400">正在读取材料库…</p>
      <div v-else-if="loadError" class="mt-4 rounded-xl bg-slate-950/40 px-5 py-4">
        <p class="text-sm text-red-400" role="alert">无法加载材料库：{{ loadError }}</p>
        <UButton class="mt-3" size="sm" icon="i-lucide-refresh-cw" @click="loadLibrary">重试</UButton>
      </div>

      <div v-else>
        <EmptyState
          v-if="ordered.length === 0"
          class="mt-4 rounded-xl bg-slate-950/40"
          title="这次审查还没有材料"
          hint="从材料库把材料加进来，并为它在本次审查里起一个名字。"
        />

        <ul v-else class="mt-4 divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800">
          <li v-for="(entry, index) in ordered" :key="entry.material_id" class="flex flex-wrap items-center gap-3 px-4 py-3">
            <div class="min-w-0 flex-1">
              <input
                v-model="labels[entry.material_id]"
                type="text"
                :aria-label="`编辑材料名称 ${filenameOf(entry.material_id)}`"
                class="w-full rounded-md border border-transparent bg-transparent px-2 py-1 text-sm font-medium text-slate-100 hover:border-slate-700 focus:border-violet-500 focus:bg-slate-900 focus:outline-none"
                :placeholder="filenameOf(entry.material_id)"
                @blur="saveLabel(entry)"
                @keydown.enter="onLabelEnter"
              />
              <p v-if="identityOf(entry).secondary" class="truncate px-2 font-mono text-[11px] text-slate-500">{{ identityOf(entry).secondary }}</p>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <UButton
                color="neutral"
                variant="ghost"
                size="xs"
                icon="i-lucide-chevron-up"
                :disabled="index === 0 || mutating"
                aria-label="上移"
                @click="move(index, -1)"
              />
              <UButton
                color="neutral"
                variant="ghost"
                size="xs"
                icon="i-lucide-chevron-down"
                :disabled="index >= ordered.length - 1 || mutating"
                aria-label="下移"
                @click="move(index, 1)"
              />
              <UButton
                color="error"
                variant="ghost"
                size="xs"
                icon="i-lucide-trash-2"
                :disabled="mutating"
                :aria-label="`移除 ${entry.label}`"
                @click="requestRemove(entry)"
              />
            </div>
          </li>
        </ul>

        <div v-if="mutationError" class="mt-3 rounded-md px-3 py-2 text-xs" :class="mutationError.conflict ? 'bg-amber-950/30 text-amber-300' : 'bg-red-950/30 text-red-400'" role="alert">
          {{ mutationError.message }}
        </div>
      </div>
    </section>

    <section v-if="!loading && !loadError">
      <h2 class="text-sm font-medium tracking-wide text-slate-200">添加材料</h2>
      <p v-if="candidates.length === 0" class="mt-2 text-xs text-slate-500">材料库中的材料都已加入本次审查。</p>
      <div v-else class="mt-3 flex flex-wrap items-end gap-3">
        <label class="text-xs text-slate-500">
          材料
          <select
            v-model="addMaterialId"
            aria-label="选择要添加的材料"
            class="mt-1 block rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
          >
            <option value="">请选择材料</option>
            <option v-for="item in candidates" :key="item.id" :value="item.id">{{ item.filename }}</option>
          </select>
        </label>
        <label class="text-xs text-slate-500">
          在本次审查中的名称（可留空）
          <input
            v-model="addLabel"
            type="text"
            :placeholder="addMaterialId === '' ? '留空则使用原文件名' : filenameOf(addMaterialId)"
            class="mt-1 block rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none"
          />
        </label>
        <UButton icon="i-lucide-plus" :disabled="addMaterialId === '' || mutating" @click="addMember">添加</UButton>
      </div>
    </section>

    <UModal
      :open="pendingRemove !== null"
      :dismissible="!removing"
      title="移除材料"
      description="只解除本次审查的引用，不删除材料本身。"
      @update:open="(value: boolean) => { if (!value) cancelRemove() }"
    >
      <template #body>
        <p class="text-sm text-slate-300">
          确定把「{{ pendingRemove?.label }}」从本次审查中移除？
        </p>
        <p v-if="removeError" class="mt-3 text-sm text-red-400" role="alert">{{ removeError }}</p>
      </template>
      <template #footer>
        <div class="flex justify-end gap-3">
          <UButton color="neutral" variant="subtle" :disabled="removing" @click="cancelRemove">取消</UButton>
          <UButton color="error" icon="i-lucide-trash-2" :loading="removing" @click="confirmRemove">移除</UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>
