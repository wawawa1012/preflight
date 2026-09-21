import type { GrillQuestion } from '../types/contracts'

// 模拟评审刷新恢复（sessionStorage ONLY）：刷新后不必重新等待模型生成。
// 边界冻结：不做 backend 持久化、不做历史列表、不做跨设备同步；sessionStorage 不可用时
// 降级为模块级内存 Map（等价于当前的纯内存行为），绝不阻塞 Grill。
//
// 身份规则：快照绑定 Review + rubric_id + rubric_revision；材料身份来自快照本身。
// 换标准版本即视为另一份快照；新 revision 是新 material，天然不继承旧快照。
// Coach feedback 永不入盘：旧判断不能在刷新后冒充当前判断，只恢复回答草稿与来源勾选。
export const GRILL_RECOVERY_VERSION = 1

// 恢复时用于校验快照身份的最小上下文。
export interface GrillRecoveryContext {
  reviewId: string
  rubricId: string
  rubricRevision: number
}

export interface GrillRecoveryCoachDraft {
  answer: string
  sourceExcluded: boolean
}

export interface GrillRecoverySnapshot extends GrillRecoveryContext {
  version: typeof GRILL_RECOVERY_VERSION
  materialId: string
  generatedAt: string
  questions: GrillQuestion[]
  // key = questionKey（block_id:start:hash(prompt)），只含草稿与勾选，不含 feedback。
  coachDrafts: Record<string, GrillRecoveryCoachDraft>
}

// 每个 Review 只保留一份（最近查看的材料），与现有内存快照的单材料行为一致。
function storageKey(reviewId: string): string {
  return `preflight:grill-recovery:${reviewId}`
}

const memoryFallback = new Map<string, string>()

function readRaw(reviewId: string): string | null {
  try {
    return window.sessionStorage.getItem(storageKey(reviewId))
  } catch {
    return memoryFallback.get(storageKey(reviewId)) ?? null
  }
}

function writeRaw(reviewId: string, value: string) {
  try {
    window.sessionStorage.setItem(storageKey(reviewId), value)
  } catch {
    memoryFallback.set(storageKey(reviewId), value)
  }
}

export function saveGrillSnapshot(snapshot: GrillRecoverySnapshot) {
  writeRaw(snapshot.reviewId, JSON.stringify(snapshot))
}

// 身份不匹配 / 版本不符 / 数据损坏：一律返回 null，调用方按「没有可恢复内容」处理。
export function loadGrillSnapshot(context: GrillRecoveryContext): GrillRecoverySnapshot | null {
  const raw = readRaw(context.reviewId)
  if (raw === null) return null
  try {
    const parsed = JSON.parse(raw) as Partial<GrillRecoverySnapshot>
    if (parsed.version !== GRILL_RECOVERY_VERSION) return null
    if (parsed.reviewId !== context.reviewId) return null
    if (parsed.rubricId !== context.rubricId || parsed.rubricRevision !== context.rubricRevision) return null
    if (typeof parsed.materialId !== 'string' || parsed.materialId === '') return null
    if (!Array.isArray(parsed.questions) || typeof parsed.generatedAt !== 'string') return null
    return {
      version: GRILL_RECOVERY_VERSION,
      reviewId: parsed.reviewId,
      rubricId: parsed.rubricId,
      rubricRevision: parsed.rubricRevision,
      materialId: parsed.materialId,
      generatedAt: parsed.generatedAt,
      questions: parsed.questions as GrillQuestion[],
      coachDrafts: parsed.coachDrafts && typeof parsed.coachDrafts === 'object' ? parsed.coachDrafts : {},
    }
  } catch {
    return null
  }
}

// 复验：恢复的问题必须仍能对上当前原文（block 存在且 quote == text[start:end]），
// 与后端「复验通过才返回」同一语义；对不上的条目丢弃，不展示也不可点。
export function verifyRestoredQuestion(
  question: GrillQuestion,
  blocks: { id: string; text: string }[],
): boolean {
  const block = blocks.find((item) => item.id === question.block_id)
  if (!block) return false
  return block.text.slice(question.start, question.end) === question.quote
}
