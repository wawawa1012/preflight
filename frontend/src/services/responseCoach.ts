import type { CoachSourceRef, ResponseCoachRequest, ResponseCoachResponse } from '../types/contracts'
import { ApiFailure } from './reviews'

// Response Coach（RC1）适配边界：只搬运 backend 的 /api/v1/response-coach。
// 不代写答案、不给分；裁决与来源回填一律以后端为准，前端只按 status/code 呈现。
export interface CoachCheckRequest {
  materialId: string
  reviewId: string
  question: string
  answer: string
  sourceRefs: CoachSourceRef[]
}

// 请求内容（问题+回答+来源）的确定性散列：与 ReviewGrillView.questionKey 同算法（FNV-1a）。
// 面板用它判断旧反馈是否仍适用于当前回答；不是持久 id，不进后端。
export function coachFingerprint(input: {
  question: string
  answer: string
  sourceRefs: CoachSourceRef[]
}): string {
  const payload = JSON.stringify({
    question: input.question,
    answer: input.answer,
    sourceRefs: input.sourceRefs,
  })
  let hash = 2166136261
  for (let index = 0; index < payload.length; index += 1) {
    hash ^= payload.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

export async function checkAnswer(request: CoachCheckRequest): Promise<ResponseCoachResponse> {
  const payload: ResponseCoachRequest = {
    material_id: request.materialId,
    question: request.question,
    user_answer: request.answer,
    // 空数组也要显式发送：后端据此走确定性 insufficient_context，而不是退回默认来源池。
    source_refs: request.sourceRefs as ResponseCoachRequest['source_refs'],
    review_id: request.reviewId === '' ? null : request.reviewId,
  }
  const response = await fetch('/api/v1/response-coach', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const body = (await response.json().catch(() => null)) as { code?: string; message?: string } | null
  if (!response.ok) {
    throw new ApiFailure(
      response.status,
      body?.code ?? `http_${response.status}`,
      body?.message ?? `HTTP ${response.status}`,
    )
  }
  return body as ResponseCoachResponse
}
