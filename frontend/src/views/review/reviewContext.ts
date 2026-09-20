import type { InjectionKey, Ref } from 'vue'
import type { ReviewDetail } from '../../types/review'

// Workspace 上下文：shell 加载 ReviewDetail 后下发给所有能力视图；
// 成员增删改后统一调 refresh()，各视图不各自重取。
// rubricTitle 由 shell 从评分标准文件仓解析（内部 rubric_id 不进正常 UI）。
export interface ReviewContext {
  review: Ref<ReviewDetail | null>
  rubricTitle: Ref<string>
  refresh: () => Promise<void>
}

export const reviewContextKey: InjectionKey<ReviewContext> = Symbol('review-context')
