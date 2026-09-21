<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CriterionDraft, RubricDraft, RubricLevel } from '../../types/contracts'
import { emptyCriterion } from '../../services/criteriaSource'

// 标准草稿编辑器：发布前用户可以改标题/要求/所需依据、删除、排序、新增。
// 评分档位：manual/rubric_json 草稿可逐条定义（minimal scoring editor）；plain_text/markdown
// 只读展示源文本里已记录的档位，不推导执行规则（后端 publish 会拒绝文本转录上的执行评分）。
const props = defineProps<{ modelValue: RubricDraft; disabled?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', draft: RubricDraft): void }>()

// 只有手工创建或 JSON 导入的来源允许用户定义评分档位。
const scoringEditable = computed(
  () => props.modelValue.source_type === 'manual' || props.modelValue.source_type === 'rubric_json',
)
const hasAnyScoring = computed(() =>
  props.modelValue.criteria.some((criterion) => criterion.scoring_definition_version === 'anchors-v1'),
)

function update(patch: Partial<RubricDraft>) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

function updateCriterion(index: number, patch: Partial<CriterionDraft>) {
  const criteria = props.modelValue.criteria.map((criterion, i) => (i === index ? { ...criterion, ...patch } : criterion))
  update({ criteria: criteria as RubricDraft['criteria'] })
}

// 结构性改动（删除/新增/移动）后，按当前显示顺序统一重编号 order；
// criterion identity 原样保留，order 不携带历史，杜绝重复 order。
function commitCriteria(criteria: CriterionDraft[]) {
  update({ criteria: criteria.map((criterion, index) => ({ ...criterion, order: index })) as RubricDraft['criteria'] })
}

function removeCriterion(index: number) {
  // criteria 契约要求非空；删空时由发布前校验拦住，这里允许删到 0 再补。
  commitCriteria(props.modelValue.criteria.filter((_, i) => i !== index))
}

function moveCriterion(index: number, offset: -1 | 1) {
  const target = index + offset
  const criteria = [...props.modelValue.criteria]
  if (target < 0 || target >= criteria.length) return
  const [item] = criteria.splice(index, 1)
  criteria.splice(target, 0, item)
  commitCriteria(criteria)
}

function addCriterion() {
  commitCriteria([...props.modelValue.criteria, emptyCriterion(props.modelValue.criteria.length)])
}

function setEvidence(index: number, raw: string) {
  updateCriterion(index, { required_evidence: raw.split('\n').map((line) => line.trim()).filter((line) => line !== '') })
}

function hasScoringMeta(criterion: CriterionDraft): boolean {
  return (criterion.rubric_levels?.length ?? 0) > 0 || (criterion.scoring_anchors?.length ?? 0) > 0
}

// ---- minimal scoring editor ----

function isQuantified(criterion: CriterionDraft): boolean {
  return criterion.scoring_definition_version === 'anchors-v1'
}

function numberOrNull(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : null
}

// 写入 criteria 的同时同步 draft 级 scoring_aggregation：任一量化 → sum_points_v1；全部不量化 → 移除字段。
function setCriteriaAndAggregation(criteria: CriterionDraft[]) {
  const normalized = criteria.map((criterion, index) => ({ ...criterion, order: index })) as RubricDraft['criteria']
  const next: RubricDraft = { ...props.modelValue, criteria: normalized }
  if (normalized.some((criterion) => isQuantified(criterion))) {
    next.scoring_aggregation = 'sum_points_v1'
  } else {
    delete next.scoring_aggregation
  }
  emit('update:modelValue', next)
}

function enableScoring(index: number) {
  const criteria = props.modelValue.criteria.map((criterion, i) => {
    if (i !== index || isQuantified(criterion)) return criterion
    const levels: RubricLevel[] = [
      { label: '', description: '', anchor_id: 'a1', score: null, min_score: null, max_score: null },
      { label: '', description: '', anchor_id: 'a2', score: null, min_score: null, max_score: null },
    ]
    return { ...criterion, scoring_definition_version: 'anchors-v1' as const, rubric_levels: levels }
  })
  setCriteriaAndAggregation(criteria)
}

function disableScoring(index: number) {
  const criteria = props.modelValue.criteria.map((criterion, i) => {
    if (i !== index) return criterion
    const next = { ...criterion }
    // 保留 title/requirement/required_evidence 与其他元数据，只移除评分定义。
    delete next.max_score
    delete next.rubric_levels
    delete next.scoring_definition_version
    return next
  })
  setCriteriaAndAggregation(criteria)
}

function setMaxScore(criterionIndex: number, raw: string) {
  updateCriterion(criterionIndex, { max_score: numberOrNull(raw) })
}

// anchor_id 程序生成且稳定：a1、a2…；删除后新增取当前未用的最小序号。UI 不展示。
function nextAnchorId(levels: RubricLevel[]): string {
  const used = new Set(
    levels.map((level) => level.anchor_id).filter((id): id is string => typeof id === 'string' && id !== ''),
  )
  let n = 1
  while (used.has(`a${n}`)) n += 1
  return `a${n}`
}

function addLevel(criterionIndex: number) {
  const levels = props.modelValue.criteria[criterionIndex].rubric_levels ?? []
  updateCriterion(criterionIndex, {
    rubric_levels: [
      ...levels,
      { label: '', description: '', anchor_id: nextAnchorId(levels), score: null, min_score: null, max_score: null },
    ],
  })
}

function removeLevel(criterionIndex: number, levelIndex: number) {
  const levels = (props.modelValue.criteria[criterionIndex].rubric_levels ?? []).filter((_, index) => index !== levelIndex)
  updateCriterion(criterionIndex, { rubric_levels: levels })
}

function updateLevel(criterionIndex: number, levelIndex: number, patch: Partial<RubricLevel>) {
  const levels = (props.modelValue.criteria[criterionIndex].rubric_levels ?? []).map((level, index) =>
    index === levelIndex ? { ...level, ...patch } : level,
  )
  updateCriterion(criterionIndex, { rubric_levels: levels })
}

// 档位模式是纯 UI 提示（exact XOR range）：字段本身仍是发布真源；切换时清掉另一侧字段。
const levelModes = ref<Record<string, 'exact' | 'range'>>({})

function levelKey(criterionIndex: number, levelIndex: number): string {
  const criterion = props.modelValue.criteria[criterionIndex]
  const level = (criterion.rubric_levels ?? [])[levelIndex]
  return `${criterion.id}:${level?.anchor_id ?? levelIndex}`
}

function levelMode(criterionIndex: number, levelIndex: number): 'exact' | 'range' {
  const explicit = levelModes.value[levelKey(criterionIndex, levelIndex)]
  if (explicit) return explicit
  const level = (props.modelValue.criteria[criterionIndex].rubric_levels ?? [])[levelIndex]
  return level && (typeof level.min_score === 'number' || typeof level.max_score === 'number') ? 'range' : 'exact'
}

function setLevelMode(criterionIndex: number, levelIndex: number, mode: 'exact' | 'range') {
  levelModes.value = { ...levelModes.value, [levelKey(criterionIndex, levelIndex)]: mode }
  if (mode === 'exact') updateLevel(criterionIndex, levelIndex, { min_score: null, max_score: null })
  else updateLevel(criterionIndex, levelIndex, { score: null })
}

function setLevelLabel(criterionIndex: number, levelIndex: number, value: string) {
  updateLevel(criterionIndex, levelIndex, { label: value })
}

function setLevelDescription(criterionIndex: number, levelIndex: number, value: string) {
  updateLevel(criterionIndex, levelIndex, { description: value })
}

function setLevelScore(criterionIndex: number, levelIndex: number, raw: string) {
  updateLevel(criterionIndex, levelIndex, { score: numberOrNull(raw) })
}

function setLevelMin(criterionIndex: number, levelIndex: number, raw: string) {
  updateLevel(criterionIndex, levelIndex, { min_score: numberOrNull(raw) })
}

function setLevelMax(criterionIndex: number, levelIndex: number, raw: string) {
  updateLevel(criterionIndex, levelIndex, { max_score: numberOrNull(raw) })
}
</script>

<template>
  <div>
    <label class="block">
      <span class="text-xs text-slate-500">标准名称</span>
      <input
        :value="modelValue.title"
        type="text"
        :disabled="disabled"
        placeholder="例如：2026 AIC 作品审查标准"
        class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
        @input="update({ title: ($event.target as HTMLInputElement).value })"
      />
    </label>

    <!-- 总分只在所有条目都量化时出现；有任一评分档位时提示，避免误以为总分必然可得。 -->
    <p v-if="hasAnyScoring" class="mt-3 text-[11px] leading-relaxed text-slate-500">
      只有所有条目都定义评分档位，评估才会给出总分。
    </p>

    <ol class="mt-4 space-y-4">
      <li
        v-for="(criterion, index) in modelValue.criteria"
        :key="criterion.id"
        class="rounded-xl border border-slate-800 p-4"
      >
        <div class="flex items-center justify-between gap-3">
          <span class="font-mono text-[11px] text-slate-600">要求 {{ index + 1 }}</span>
          <div class="flex items-center gap-1">
            <UButton color="neutral" variant="ghost" size="xs" icon="i-lucide-arrow-up" :disabled="disabled || index === 0" aria-label="上移" @click="moveCriterion(index, -1)" />
            <UButton color="neutral" variant="ghost" size="xs" icon="i-lucide-arrow-down" :disabled="disabled || index === modelValue.criteria.length - 1" aria-label="下移" @click="moveCriterion(index, 1)" />
            <UButton color="neutral" variant="ghost" size="xs" icon="i-lucide-trash-2" :disabled="disabled" aria-label="删除这条要求" @click="removeCriterion(index)" />
          </div>
        </div>

        <label class="mt-2 block">
          <span class="text-[11px] text-slate-500">标题</span>
          <input
            :value="criterion.title"
            type="text"
            :disabled="disabled"
            class="mt-0.5 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
            @input="updateCriterion(index, { title: ($event.target as HTMLInputElement).value })"
          />
        </label>
        <label class="mt-2 block">
          <span class="text-[11px] text-slate-500">审查要求</span>
          <textarea
            :value="criterion.requirement"
            rows="2"
            :disabled="disabled"
            class="mt-0.5 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
            @input="updateCriterion(index, { requirement: ($event.target as HTMLTextAreaElement).value })"
          ></textarea>
        </label>
        <label class="mt-2 block">
          <span class="text-[11px] text-slate-500">所需依据（每行一条）</span>
          <textarea
            :value="criterion.required_evidence.join('\n')"
            rows="2"
            :disabled="disabled"
            placeholder="例如：测试条件说明"
            class="mt-0.5 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
            @input="setEvidence(index, ($event.target as HTMLTextAreaElement).value)"
          ></textarea>
        </label>

        <!-- 只读参考：plain_text/markdown 源文本里已记录的评分档位，不推导执行规则。 -->
        <div v-if="!scoringEditable && hasScoringMeta(criterion)" class="mt-2 rounded-md bg-slate-900/60 px-3 py-2">
          <p class="text-[11px] text-slate-600">
            源标准中的评分档位记录（仅供参考）；量化评估需在手工创建或 JSON 导入的标准上定义评分档位。
          </p>
          <ul v-if="criterion.rubric_levels?.length" class="mt-1 space-y-0.5">
            <li v-for="level in criterion.rubric_levels" :key="level.label" class="text-[11px] text-slate-500">
              <span class="text-slate-400">{{ level.label }}</span>
              <span v-if="level.description"> — {{ level.description }}</span>
            </li>
          </ul>
          <p v-if="criterion.scoring_anchors?.length" class="mt-1 text-[11px] text-slate-500">
            评分锚点：{{ criterion.scoring_anchors.join('；') }}
          </p>
        </div>

        <!-- 评分档位编辑：manual/rubric_json 草稿逐条二选一（不量化 / 定义评分档位）。 -->
        <div v-else-if="scoringEditable" class="mt-3 rounded-md border border-slate-800 bg-slate-900/40 px-3 py-2">
          <div class="flex flex-wrap items-center gap-4">
            <label class="flex items-center gap-1.5 text-[11px] text-slate-400">
              <input
                type="radio"
                :name="`scoring-mode-${criterion.id}`"
                :checked="!isQuantified(criterion)"
                :disabled="disabled"
                @change="disableScoring(index)"
              />
              不量化
            </label>
            <label class="flex items-center gap-1.5 text-[11px] text-slate-400">
              <input
                type="radio"
                :name="`scoring-mode-${criterion.id}`"
                :checked="isQuantified(criterion)"
                :disabled="disabled"
                @change="enableScoring(index)"
              />
              定义评分档位
            </label>
          </div>

          <template v-if="isQuantified(criterion)">
            <label class="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
              <span>满分</span>
              <input
                type="number"
                min="0"
                step="any"
                :value="criterion.max_score ?? ''"
                :disabled="disabled"
                class="w-24 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
                @input="setMaxScore(index, ($event.target as HTMLInputElement).value)"
              />
            </label>

            <div
              v-for="(level, levelIndex) in criterion.rubric_levels ?? []"
              :key="level.anchor_id ?? levelIndex"
              class="mt-2 rounded-md border border-slate-800 bg-slate-950/30 p-2"
            >
              <div class="flex items-center gap-2">
                <input
                  type="text"
                  :value="level.label"
                  :disabled="disabled"
                  placeholder="档位名称"
                  class="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
                  @input="setLevelLabel(index, levelIndex, ($event.target as HTMLInputElement).value)"
                />
                <UButton color="neutral" variant="ghost" size="xs" icon="i-lucide-trash-2" :disabled="disabled" aria-label="删除档位" @click="removeLevel(index, levelIndex)" />
              </div>
              <input
                type="text"
                :value="level.description ?? ''"
                :disabled="disabled"
                placeholder="达成条件"
                class="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
                @input="setLevelDescription(index, levelIndex, ($event.target as HTMLInputElement).value)"
              />
              <div class="mt-1 flex flex-wrap items-center gap-3">
                <label class="flex items-center gap-1.5 text-[11px] text-slate-400">
                  <input
                    type="radio"
                    :name="`level-mode-${criterion.id}-${level.anchor_id ?? levelIndex}`"
                    :checked="levelMode(index, levelIndex) === 'exact'"
                    :disabled="disabled"
                    @change="setLevelMode(index, levelIndex, 'exact')"
                  />
                  固定分值
                </label>
                <label class="flex items-center gap-1.5 text-[11px] text-slate-400">
                  <input
                    type="radio"
                    :name="`level-mode-${criterion.id}-${level.anchor_id ?? levelIndex}`"
                    :checked="levelMode(index, levelIndex) === 'range'"
                    :disabled="disabled"
                    @change="setLevelMode(index, levelIndex, 'range')"
                  />
                  区间
                </label>
                <template v-if="levelMode(index, levelIndex) === 'exact'">
                  <input
                    type="number"
                    step="any"
                    :value="level.score ?? ''"
                    :disabled="disabled"
                    placeholder="分值"
                    class="w-20 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
                    @input="setLevelScore(index, levelIndex, ($event.target as HTMLInputElement).value)"
                  />
                </template>
                <template v-else>
                  <input
                    type="number"
                    step="any"
                    :value="level.min_score ?? ''"
                    :disabled="disabled"
                    placeholder="下限"
                    class="w-20 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
                    @input="setLevelMin(index, levelIndex, ($event.target as HTMLInputElement).value)"
                  />
                  <span aria-hidden="true" class="text-slate-600">–</span>
                  <input
                    type="number"
                    step="any"
                    :value="level.max_score ?? ''"
                    :disabled="disabled"
                    placeholder="上限"
                    class="w-20 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-violet-500 focus:outline-none disabled:opacity-60"
                    @input="setLevelMax(index, levelIndex, ($event.target as HTMLInputElement).value)"
                  />
                </template>
              </div>
            </div>

            <UButton class="mt-2" color="neutral" variant="ghost" size="xs" icon="i-lucide-plus" :disabled="disabled" @click="addLevel(index)">
              添加档位
            </UButton>
          </template>
        </div>
      </li>
    </ol>

    <UButton class="mt-4" color="neutral" variant="subtle" size="sm" icon="i-lucide-plus" :disabled="disabled" @click="addCriterion">
      添加一条要求
    </UButton>
  </div>
</template>
