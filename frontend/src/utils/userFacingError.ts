import { ApiFailure } from '../services/reviews'

// 用户可见错误映射（呈现层唯一出口）：HTTP/code/业务成功状态一律不动，只把原因翻成人话。
// 规则：
// - 已知 code 用固定安全文案；未知 code 仅在文案通过安全过滤时透传，否则给状态级兜底；
// - 部署变量（.env / PREFLIGHT_* / API_KEY / BASE_URL）与 schema/Criterion 校验原文绝不外露；
// - 保留原始 code 供诊断（返回值里的 code），失败不吞、不伪造空结果。
export interface UserFacingError {
  code: string
  message: string
  retryable: boolean
}

const CANONICAL: Record<string, { message: string; retryable: boolean }> = {
  llm_unconfigured: { message: '后端未配置 LLM，配置后重试', retryable: true },
  llm_timeout: { message: '生成超时，可重试', retryable: true },
  llm_invalid_response: { message: 'AI 返回的内容不符合要求，未生成结果；可重试', retryable: true },
  citation_mismatch: { message: '引用与材料原文对不上，未生成建议', retryable: false },
  material_too_large: { message: '材料超出单次核验上限，本行未核验', retryable: false },
  binding_conflict: { message: '该材料已绑定其他审查标准版本，未做任何改动', retryable: false },
  invalid_rubric: { message: '标准内容不完整，无法发布；请检查名称、每条要求和所需依据', retryable: false },
  invalid_rubric_source: { message: '这份结构化标准读不了；请对照 JSON 示例检查格式', retryable: false },
  invalid_request: { message: '提交内容不符合要求，请检查后重试', retryable: false },
  rubric_not_found: { message: '该审查标准版本已不可用，请重新选择', retryable: false },
  rubric_not_bound: { message: '该材料尚未绑定审查标准', retryable: false },
  review_not_found: { message: '找不到这次审查，可能已被删除', retryable: false },
  material_not_found: { message: '找不到该材料，可能已被删除', retryable: false },
  criterion_not_found: { message: '找不到该审查要求', retryable: false },
  block_not_found: { message: '找不到该段原文', retryable: false },
  quote_not_found: { message: '引用与材料原文对不上，请重新选择原文片段', retryable: false },
  span_mismatch: { message: '引用位置与原文不一致，请重新选择原文片段', retryable: false },
  duplicate_link: { message: '该引用已经关联过这条要求', retryable: false },
  candidate_already_reviewed: { message: '这条候选已经被处理过', retryable: false },
  parent_not_in_review: { message: '该材料不在这次审查里', retryable: false },
  membership_not_found: { message: '该材料不在这次审查里', retryable: false },
  revision_parent_conflict: { message: '这份修订稿与原材料的关联已变化，请刷新后重试', retryable: false },
  same_material: { message: '请选择两份不同的材料', retryable: false },
  conflict: { message: '当前操作与已有数据冲突，未做任何改动', retryable: false },
  no_saved_material: { message: '还没有保存过任何材料', retryable: false },
  file_too_large: { message: '文件超过 1 MiB 上限', retryable: false },
  invalid_extension: { message: '只支持 .md 文件', retryable: false },
  invalid_encoding: { message: '文件不是有效 UTF-8 文本', retryable: false },
}

// 命中即视为机器原文：部署变量、schema/Criterion 校验细节都不适合普通用户读。
const UNSAFE_TEXT = /(PREFLIGHT_|API[_-]?KEY|BASE_URL|\.env|schema|pydantic|validation|field required|criteria\[\d+\]|Criterion)/i

const MAX_SAFE_MESSAGE_CHARS = 160

function safeServerMessage(message: string): string | null {
  const trimmed = message.trim()
  if (trimmed === '' || trimmed.length > MAX_SAFE_MESSAGE_CHARS) return null
  if (UNSAFE_TEXT.test(trimmed)) return null
  return trimmed
}

/** 从 HTTP 响应构造 ApiFailure：body 不是 JSON/缺字段时也有稳定 code，前端只按 code/status 呈现。 */
export function failureFromResponse(status: number, body: unknown): ApiFailure {
  const record = (body !== null && typeof body === 'object' ? body : {}) as { code?: unknown; message?: unknown }
  const code = typeof record.code === 'string' && record.code !== '' ? record.code : `http_${status}`
  const message = typeof record.message === 'string' && record.message !== '' ? record.message : `HTTP ${status}`
  return new ApiFailure(status, code, message)
}

export function toUserFacingError(cause: unknown, fallbackMessage = '操作失败，请稍后重试'): UserFacingError {
  if (cause instanceof ApiFailure) {
    const canonical = CANONICAL[cause.code]
    if (canonical) return { code: cause.code, ...canonical }
    const safe = safeServerMessage(cause.message)
    if (safe !== null) return { code: cause.code, message: safe, retryable: cause.status >= 500 }
    if (cause.status >= 500) return { code: cause.code, message: '服务暂时不可用，请稍后重试', retryable: true }
    if (cause.status === 409) return { code: cause.code, message: '当前操作与已有数据冲突，未做任何改动', retryable: false }
    if (cause.status === 404) return { code: cause.code, message: '找不到所请求的内容', retryable: false }
    return { code: cause.code, message: fallbackMessage, retryable: false }
  }
  if (cause instanceof TypeError) {
    return { code: 'network_error', message: '连接不上服务，请检查网络后重试', retryable: true }
  }
  if (cause instanceof Error) {
    const safe = safeServerMessage(cause.message)
    if (safe !== null) return { code: 'unexpected_error', message: safe, retryable: true }
    return { code: 'unexpected_error', message: fallbackMessage, retryable: true }
  }
  return { code: 'unknown_error', message: fallbackMessage, retryable: true }
}
