import type { Review, ReviewCreate, ReviewDetail, ReviewMaterialEntry } from '../types/review'

// Review API 客户端：只搬运 backend 响应。绑定冲突、标准不可切换等业务规则一律以后端为准，
// 前端不复制规则，只按 code/status 呈现。
export class ApiFailure extends Error {
  code: string
  status: number

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  const body = (await response.json().catch(() => null)) as { code?: string; message?: string } | null
  if (!response.ok) {
    throw new ApiFailure(response.status, body?.code ?? `http_${response.status}`, body?.message ?? `HTTP ${response.status}`)
  }
  return body as T
}

function json(method: string, payload?: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  }
}

export const reviewsApi = {
  list: () => request<Review[]>('/api/v1/reviews'),
  get: (reviewId: string) => request<ReviewDetail>(`/api/v1/reviews/${encodeURIComponent(reviewId)}`),
  create: (payload: ReviewCreate) => request<Review>('/api/v1/reviews', json('POST', payload)),
  rename: (reviewId: string, title: string) =>
    request<Review>(`/api/v1/reviews/${encodeURIComponent(reviewId)}`, json('PATCH', { title })),
  upsertMaterial: (reviewId: string, materialId: string, patch: { label?: string; position?: number }) =>
    request<ReviewMaterialEntry>(
      `/api/v1/reviews/${encodeURIComponent(reviewId)}/materials/${encodeURIComponent(materialId)}`,
      json('PUT', patch),
    ),
  // 204 与 404 都按“成员关系已不存在”处理；其余状态抛 ApiFailure。
  removeMaterial: async (reviewId: string, materialId: string) => {
    const response = await fetch(
      `/api/v1/reviews/${encodeURIComponent(reviewId)}/materials/${encodeURIComponent(materialId)}`,
      { method: 'DELETE' },
    )
    if (!response.ok && response.status !== 404) {
      const body = (await response.json().catch(() => null)) as { code?: string; message?: string } | null
      throw new ApiFailure(response.status, body?.code ?? `http_${response.status}`, body?.message ?? `HTTP ${response.status}`)
    }
  },
  // 删除 Review 只删除审查上下文与成员关系；材料与材料的审查标准绑定都不受影响。
  remove: async (reviewId: string) => {
    const response = await fetch(`/api/v1/reviews/${encodeURIComponent(reviewId)}`, { method: 'DELETE' })
    if (!response.ok && response.status !== 404) {
      const body = (await response.json().catch(() => null)) as { code?: string; message?: string } | null
      throw new ApiFailure(response.status, body?.code ?? `http_${response.status}`, body?.message ?? `HTTP ${response.status}`)
    }
  },
  // 材料的审查标准应用（B1）：未绑定→首次绑定(201)；同标准→幂等(200)；已绑定其他标准→409 binding_conflict。
  // 前端只呈现结果，绝不自动换绑。
  bindMaterial: async (materialId: string, rubricId: string, rubricRevision: number) => {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}/rubric-binding`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rubric_id: rubricId, rubric_revision: rubricRevision }),
    })
    const body = (await response.json().catch(() => null)) as { code?: string; message?: string } | null
    if (!response.ok) {
      throw new ApiFailure(response.status, body?.code ?? `http_${response.status}`, body?.message ?? `HTTP ${response.status}`)
    }
    return response.status === 201 ? ('created' as const) : ('existing' as const)
  },
}
