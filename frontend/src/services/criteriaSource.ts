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
  publish: (draft: RubricDraft) => {
    const payload: RubricPublish = { ...draft, confirmed: true }
    return request<Rubric>('/api/v1/rubrics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },
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
