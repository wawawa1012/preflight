// P1 Review API 的本地类型：Review 尚未进入 ContractBundle（前端契约导出阶段再挂），
// 此处与 backend/app/contracts.py 的 Review 系列模型手工对齐；字段变更以 backend 为准。
export interface Review {
  id: string
  title: string
  rubric_id: string
  rubric_revision: number
  created_at: string
  updated_at: string
}

export interface ReviewMaterialEntry {
  material_id: string
  label: string
  position: number
}

export interface ReviewDetail extends Review {
  materials: ReviewMaterialEntry[]
}

export interface ReviewCreate {
  title: string
  rubric_id: string
  rubric_revision: number
}
