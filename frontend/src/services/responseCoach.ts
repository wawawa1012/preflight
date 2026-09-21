// Response Coach（RC1）适配边界。
// RC1 wire contract 由 Backend Pod 开发中；冻结前这里不猜任何 API 字段。
// UI 只面向 CoachCheckResult 编程；契约冻结后在此实现真实调用。
export type CoachCheckResult =
  | { status: 'unavailable'; reason: 'rc1_contract_pending' }

export interface CoachCheckRequest {
  question: string
  answer: string
  materialId: string
}

export async function checkAnswer(_request: CoachCheckRequest): Promise<CoachCheckResult> {
  return { status: 'unavailable', reason: 'rc1_contract_pending' }
}
