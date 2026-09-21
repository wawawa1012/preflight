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
// 只有 source_type === 'manual' 走这里；外部来源（plain_text/markdown/rubric_json）的原文原样保留，
// 绝不改写成 manual 来绕过 provenance 校验。
export function manualSourceSnapshot(draft: RubricDraft): string {
  const lines = [`手工创建标准：${draft.title.trim()}`, '']
  draft.criteria.forEach((criterion, index) => {
    lines.push(`${index + 1}. ${criterion.title.trim()}`)
    lines.push(`审查要求：${criterion.requirement.trim()}`)
    const evidence = criterion.required_evidence.map((item) => item.trim()).filter((item) => item !== '')
    if (evidence.length > 0) lines.push(`所需依据：${evidence.join('；')}`)
    lines.push('')
  })
  return lines.join('\n').trimEnd()
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
  })

  const isManual = draft.source_type === 'manual'
  const sourceText = isManual ? manualSourceSnapshot({ ...draft, title }) : draft.source_text
  if (sourceText.trim() === '') problems.push('缺少标准原文来源。')
  if (sourceText.length > MAX_SOURCE_TEXT_CHARS) {
    problems.push(`标准原文过长（${sourceText.length} / ${MAX_SOURCE_TEXT_CHARS} 字），请精简后再发布。`)
  }
  if (problems.length > 0) return { ok: false, problems, payload: null }

  return {
    ok: true,
    problems: [],
    payload: {
      ...draft,
      title,
      source_text: sourceText,
      criteria: draft.criteria.map((criterion, index) => ({ ...criterion, order: index })),
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
