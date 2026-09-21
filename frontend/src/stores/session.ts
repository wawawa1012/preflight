import { defineStore } from 'pinia'

// 有界 session store：只解决「从功能页进入 Source Reader 再返回不丢上下文」。
// 纯内存态：不做 localStorage，不做刷新后恢复，不把 Review.updated_at 当 cache version。
export interface ReaderTarget {
  materialId: string
  blockId: string
  start: number
  end: number
  quote?: string
}

export interface ReaderVisit {
  reviewId: string
  reviewTitle: string
  materialId: string
  materialLabel: string
  materialFilename: string
  targets: ReaderTarget[]
  index: number
  origin: { fullPath: string; label: string }
}

// 从真实 Finding / Repair suggestion 进入修订稿编辑器时携带的建议上下文。
// 建议不是可执行补丁：编辑器只展示它，绝不自动选择数值或改事实。
export interface RevisionAdvice {
  materialId: string
  sourceLabel: string
  findingSummary: string
  suggestion: string
  action: string
}

export const useSessionStore = defineStore('session', {
  state: () => ({
    currentReviewId: '' as string,
    readerVisit: null as ReaderVisit | null,
    // 功能页（一致性/修改效果/质询）的选择与结果快照：key = `${reviewId}:${capability}`。
    capabilitySnapshots: {} as Record<string, unknown>,
    // 修订稿编辑器的建议上下文：进入编辑器时消费一次。
    revisionAdvice: null as RevisionAdvice | null,
    // ActionItem 的「暂时忽略」：只承诺当前 session，刷新即失效，UI 必须明示这一点。
    dismissedActionKeys: [] as string[],
    // Response Coach 草稿：session-only，不是长期保存。key = `${reviewId}:${questionKey}`。
    coachDrafts: {} as Record<string, { answer: string }>,
  }),
  actions: {
    openReader(visit: ReaderVisit) {
      this.readerVisit = visit
      this.currentReviewId = visit.reviewId
    },
    closeReader() {
      this.readerVisit = null
    },
    saveCapability(key: string, snapshot: unknown) {
      this.capabilitySnapshots[key] = snapshot
    },
    restoreCapability<T>(key: string): T | null {
      return (this.capabilitySnapshots[key] as T | undefined) ?? null
    },
    setRevisionAdvice(advice: RevisionAdvice) {
      this.revisionAdvice = advice
    },
    takeRevisionAdvice(materialId: string): RevisionAdvice | null {
      const advice = this.revisionAdvice
      if (!advice || advice.materialId !== materialId) return null
      this.revisionAdvice = null
      return advice
    },
    dismissAction(key: string) {
      if (!this.dismissedActionKeys.includes(key)) this.dismissedActionKeys.push(key)
    },
    restoreAction(key: string) {
      this.dismissedActionKeys = this.dismissedActionKeys.filter((item) => item !== key)
    },
    saveCoachDraft(key: string, answer: string) {
      this.coachDrafts[key] = { answer }
    },
  },
})
