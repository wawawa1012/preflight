import type { AssessmentComparisonVM, AssessmentSnapshotVM } from '../types/assessment'

// Assessment 适配边界（唯一）：页面与组件只消费 types/assessment.ts 的展示 VM。
// DS-B 的 Assessment contract checkpoint 落地前，这里不发明 wire DTO、不发真实请求：
// available() 返回 false，页面呈现诚实的「尚未接入」空态。
// 契约落地后只改本文件：generated 类型 → VM 的映射集中在这里。
export class AssessmentContractPending extends Error {
  constructor() {
    super('assessment contract not integrated yet')
    this.name = 'AssessmentContractPending'
  }
}

export function assessmentAvailable(): boolean {
  return false
}

export async function listSnapshots(_reviewId: string): Promise<AssessmentSnapshotVM[]> {
  throw new AssessmentContractPending()
}

export async function generateSnapshot(_reviewId: string): Promise<AssessmentSnapshotVM> {
  throw new AssessmentContractPending()
}

export async function compareSnapshots(
  _reviewId: string,
  _beforeId: string,
  _afterId: string,
): Promise<AssessmentComparisonVM> {
  throw new AssessmentContractPending()
}
