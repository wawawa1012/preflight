<script setup lang="ts">
import type { CriterionDraft, RubricDraft } from '../../types/contracts'
import { emptyCriterion } from '../../services/criteriaSource'

// 标准草稿编辑器：发布前用户可以改标题/要求/所需依据、删除、排序、新增。
// 评分档位等 source-grounded metadata 只读展示——它们来自源文本，不是本产品的评分承诺。
const props = defineProps<{ modelValue: RubricDraft; disabled?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', draft: RubricDraft): void }>()

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

        <!-- 源文本里真实存在的评分档位：只读参考，不是本产品的评分。 -->
        <div v-if="hasScoringMeta(criterion)" class="mt-2 rounded-md bg-slate-900/60 px-3 py-2">
          <p class="text-[11px] text-slate-600">源标准中的评分档位（仅供参考，本产品不做评分）</p>
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
      </li>
    </ol>

    <UButton class="mt-4" color="neutral" variant="subtle" size="sm" icon="i-lucide-plus" :disabled="disabled" @click="addCriterion">
      添加一条要求
    </UButton>
  </div>
</template>
