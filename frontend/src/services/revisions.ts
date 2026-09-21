import type {
  EditableSource,
  MaterialRevisionCreate,
  MaterialRevisionCreated,
} from '../types/contracts'
import { ApiFailure } from './reviews'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  const body = (await response.json().catch(() => null)) as { code?: string; message?: string } | null
  if (!response.ok) {
    throw new ApiFailure(response.status, body?.code ?? `http_${response.status}`, body?.message ?? `HTTP ${response.status}`)
  }
  return body as T
}

// 旧 Material 永远不可变：保存修订 = 以 parent 为基准创建一份全新 Material。
// 传 review_id 时后端会校验 parent 在该 Review 中并把 child 自动加入成员；
// 不传则 child 继承 parent 的绑定，不属于任何 Review。
export const revisionsApi = {
  editableSource: (materialId: string) =>
    request<EditableSource>(`/api/v1/materials/${encodeURIComponent(materialId)}/editable-source`),
  create: (parentId: string, payload: MaterialRevisionCreate) =>
    request<MaterialRevisionCreated>(`/api/v1/materials/${encodeURIComponent(parentId)}/revisions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
}
