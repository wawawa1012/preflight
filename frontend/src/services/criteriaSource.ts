import type { CriterionDraft, Rubric, RubricDraft, RubricPublish } from '../types/contracts'
import { ApiFailure } from './reviews'

// Criteria Builder 真实接线（冻结契约 C1）：
// draft = POST /api/v1/rubrics/draft（plain_text/markdown 走模型，rubric_json 纯程序解析）；
// publish = POST /api/v1/rubrics（confirmed:true，每次调用生成新的不可变标准，非幂等）。
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  const body = (await response.json().catch(() => null)) as { code?: string; message?: string } | null
  if (!response.ok) {
    throw new ApiFailure(response.status, body?.code ?? `http_${response.status}`, body?.message ?? `HTTP ${response.status}`)
  }
  return body as T
}

export interface DraftSource {
  text: string
  source_type?: 'plain_text' | 'markdown' | 'rubric_json'
  source_name?: string
}

export const criteriaBuilderApi = {
  draft: (source: DraftSource) =>
    request<RubricDraft>('/api/v1/rubrics/draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(source),
    }),
  // 非幂等：网络层失败时响应不确定，调用方必须给用户诚实恢复状态，禁止自动重试。
  // payload 必须由 preparePublish 产出（手工草稿已带 source_text 快照）。
  publish: (payload: RubricPublish) =>
    request<Rubric>('/api/v1/rubrics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
}

// 手工创建不经过模型：直接给一份可编辑的空草稿。
export function emptyManualDraft(): RubricDraft {
  return {
    title: '',
    source_note: '手工创建',
    source_type: 'manual',
    source_text: '',
    model_assisted: false,
    criteria: [emptyCriterion(0)],
  }
}

export function emptyCriterion(order: number): CriterionDraft {
  return {
    id: `manual-${Date.now()}-${order}`,
    title: '',
    requirement: '',
    required_evidence: [],
    order,
  }
}

export const MAX_SOURCE_TEXT_CHARS = 20000
export const MAX_CRITERIA = 50

// 手工草稿的 source_text 快照：由用户最终确认的标题、每条要求与所需依据组成，不是占位串。
// 用户定义了评分档位时一并序列化（满分 + 每档名称/条件/分值或区间），让发布的 manual 标准
// 来源文本诚实包含评分规则。只有 source_type === 'manual' 走这里；外部来源原文原样保留，
// 绝不改写成 manual 来绕过 provenance 校验。
export function manualSourceSnapshot(draft: RubricDraft): string {
  const lines = [`手工创建标准：${draft.title.trim()}`, '']
  draft.criteria.forEach((criterion, index) => {
    lines.push(`${index + 1}. ${criterion.title.trim()}`)
    lines.push(`审查要求：${criterion.requirement.trim()}`)
    const evidence = criterion.required_evidence.map((item) => item.trim()).filter((item) => item !== '')
    if (evidence.length > 0) lines.push(`所需依据：${evidence.join('；')}`)
    if (criterion.scoring_definition_version) {
      const maxScore = typeof criterion.max_score === 'number' ? criterion.max_score : '未填'
      lines.push(`评分档位（满分 ${maxScore}）：`)
      for (const level of criterion.rubric_levels ?? []) {
        const name = level.label.trim()
        const condition = (level.description ?? '').trim()
        const head = [name, condition].filter((part) => part !== '').join('：')
        const scoreText =
          typeof level.score === 'number'
            ? `${level.score} 分`
            : typeof level.min_score === 'number' && typeof level.max_score === 'number'
              ? `${level.min_score}–${level.max_score} 分`
              : ''
        lines.push(`- ${head}${scoreText ? ` — ${scoreText}` : ''}`)
      }
    }
    lines.push('')
  })
  return lines.join('\n').trimEnd()
}

// 评分档位预检：与 backend Criterion.executable_scoring 对齐，问题文案指明第几条。
// 允许部分 criterion 量化、部分不量化；总分只在全部量化时出现（backend 判定）。
function scoringProblems(criterion: CriterionDraft, index: number): string[] {
  if (criterion.scoring_definition_version !== 'anchors-v1') return []
  const label = `第 ${index + 1} 条要求`
  const problems: string[] = []
  const rawMax = criterion.max_score
  const maxScore = typeof rawMax === 'number' && Number.isFinite(rawMax) && rawMax > 0 ? rawMax : null
  if (maxScore === null) problems.push(`${label}的满分必须填写且大于 0。`)
  const levels = criterion.rubric_levels ?? []
  if (levels.length < 2) problems.push(`${label}至少需要两个评分档位。`)
  levels.forEach((level, levelIndex) => {
    const at = `${label}的第 ${levelIndex + 1} 个评分档位`
    if (level.label.trim() === '') problems.push(`${at}缺少名称。`)
    if ((level.description ?? '').trim() === '') problems.push(`${at}缺少达成条件。`)
    const score = level.score
    const min = level.min_score
    const max = level.max_score
    if (typeof score === 'number' && (typeof min === 'number' || typeof max === 'number')) {
      problems.push(`${at}只能选择固定分值或区间，不能同时填写。`)
    } else if (typeof score === 'number') {
      if (!Number.isFinite(score) || score < 0 || (maxScore !== null && score > maxScore)) {
        problems.push(`${at}的固定分值必须在 0 到满分之间。`)
      }
    } else if (typeof min === 'number' && typeof max === 'number') {
      if (
        !Number.isFinite(min) ||
        !Number.isFinite(max) ||
        min < 0 ||
        min > max ||
        (maxScore !== null && max > maxScore)
      ) {
        problems.push(`${at}的区间必须满足 0 ≤ 下限 ≤ 上限 ≤ 满分。`)
      }
    } else if (typeof min === 'number' || typeof max === 'number') {
      problems.push(`${at}的区间必须同时填写下限与上限。`)
    } else {
      problems.push(`${at}需要填写固定分值或区间。`)
    }
  })
  return problems
}

export interface PublishDraftResult {
  ok: boolean
  problems: string[]
  payload: RubricPublish | null
}

// 发布前校验必填、数量与 source_text 长度；按当前显示顺序重编号 order（identity 不变）。
// 服务端契约仍是最终裁判，这里只让用户不必等一次往返才看到问题。
export function preparePublish(draft: RubricDraft): PublishDraftResult {
  const problems: string[] = []
  const title = draft.title.trim()
  if (title === '') problems.push('标准名称不能为空。')
  if (draft.source_note.trim() === '') problems.push('标准来源说明不能为空。')
  if (draft.criteria.length === 0) problems.push('至少需要一条审查要求。')
  if (draft.criteria.length > MAX_CRITERIA) problems.push(`审查要求最多 ${MAX_CRITERIA} 条。`)
  draft.criteria.forEach((criterion, index) => {
    if (criterion.title.trim() === '') problems.push(`第 ${index + 1} 条要求缺少标题。`)
    if (criterion.requirement.trim() === '') problems.push(`第 ${index + 1} 条要求缺少审查要求内容。`)
    if (criterion.required_evidence.some((item) => item.trim() === '')) {
      problems.push(`第 ${index + 1} 条要求的所需依据不能有空行。`)
    }
    problems.push(...scoringProblems(criterion, index))
  })

  const isManual = draft.source_type === 'manual'
  const sourceText = isManual ? manualSourceSnapshot({ ...draft, title }) : draft.source_text
  if (sourceText.trim() === '') problems.push('缺少标准原文来源。')
  if (sourceText.length > MAX_SOURCE_TEXT_CHARS) {
    problems.push(`标准原文过长（${sourceText.length} / ${MAX_SOURCE_TEXT_CHARS} 字），请精简后再发布。`)
  }
  if (problems.length > 0) return { ok: false, problems, payload: null }

  // draft 级联动：任一 criterion 量化 → sum_points_v1；全部不量化 → 字段不出现。
  const anyScoring = draft.criteria.some((criterion) => criterion.scoring_definition_version === 'anchors-v1')
  return {
    ok: true,
    problems: [],
    payload: {
      ...draft,
      title,
      source_text: sourceText,
      criteria: draft.criteria.map((criterion, index) => ({ ...criterion, order: index })),
      scoring_aggregation: anyScoring ? 'sum_points_v1' : undefined,
      confirmed: true,
    } as RubricPublish,
  }
}

// JSON 高级导入的最小合法示例：title + criteria，每项 title/requirement/required_evidence。
// 与 backend criteria_builder 的 rubric_json 确定性解析对齐（无评分语义，不调用模型）。
export const RUBRIC_JSON_EXAMPLE = `{
  "title": "我的审查标准",
  "criteria": [
    {
      "title": "性能数字要有测试条件",
      "requirement": "所有性能数字必须给出测试条件与统计口径。",
      "required_evidence": ["测试环境说明", "统计口径说明"]
    }
  ]
}`
