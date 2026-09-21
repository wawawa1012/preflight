import { defineStore } from 'pinia'
import type { ResponseCoachResponse, Rubric, RubricDraft } from '../types/contracts'

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

// Response Coach 一条练习的会话状态：草稿、来源勾选与最近一次反馈。
// feedback.fingerprint 是请求内容（问题+回答+来源）的确定性散列；
// 回答或来源变化后旧反馈不得冒充当前结果，由面板比对 fingerprint 决定不渲染。
export interface CoachDraftEntry {
  answer: string
  sourceExcluded: boolean
  feedback: { fingerprint: string; response: ResponseCoachResponse } | null
}

// 新审查 Wizard 的最小 round-trip 草稿：只解决 ReviewNew → MaterialNew → ReviewNew 一次往返。
// 纯内存（File 对象也只活在内存）；刷新恢复 Wizard 草稿不是本期承诺。
// MaterialNew 不理解审查规则：它只按 returnTo 返回并报告新 material id，草稿语义全在 ReviewNew。
export interface WizardDraftSeat {
  materialId: string
  filename: string
  checked: boolean
  label: string
}

export interface WizardDraft {
  title: string
  step: number
  seats: WizardDraftSeat[]
  criteriaKind: 'existing' | 'paste' | 'upload' | 'manual'
  rubricKey: string
  pastedText: string
  uploadFile: File | null
  draft: RubricDraft | null
  publishedRubric: Rubric | null
  createdReviewId: string
  createdRubric: Rubric | null
  addedSeatIds: string[]
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
    // Response Coach 练习状态：session-only，不是长期保存。key = `${reviewId}:${materialId}:${questionKey}`。
    coachDrafts: {} as Record<string, CoachDraftEntry>,
    // Wizard round-trip 草稿：进入 MaterialNew 前写入，回到 ReviewNew 时消费一次。
    wizardDraft: null as WizardDraft | null,
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
    saveCoachDraft(key: string, patch: Partial<CoachDraftEntry>) {
      const current = this.coachDrafts[key] ?? { answer: '', sourceExcluded: false, feedback: null }
      this.coachDrafts[key] = { ...current, ...patch }
    },
    saveWizardDraft(draft: WizardDraft) {
      this.wizardDraft = draft
    },
    // 消费一次：回到 ReviewNew 时取走即清空；再次离开去上传时由 ReviewNew 重新写入。
    takeWizardDraft(): WizardDraft | null {
      const draft = this.wizardDraft
      this.wizardDraft = null
      return draft
    },
  },
})
