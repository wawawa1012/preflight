// ActionItem：全站统一的「待处理事项」呈现模型。
// 只是 transient UI / session view model——不是持久化 Finding，没有 database ID、
// owner 或工作流状态机。key 只在当前会话内稳定，用于列表渲染与去重。
export interface ActionItemAction {
  key: string
  label: string
  // 有 to 走路由跳转；没有 to 由宿主监听 act 事件自行处理。
  to?: string
  primary?: boolean
}

// 事项类别：按 issue 语义区分，不按 Agent 分栏；执行态（运行中/等待）永不成类别。
export type ActionItemCategory = 'numeric_inconsistency' | 'evidence_gap' | 'statement_signal' | 'defense_prep'

// 来源数组里的一项：轻量来源身份（哪份材料），只是指向真实材料的引用，
// 不是 Composite Evidence，不合并、不推断内容。
export interface ActionItemSource {
  materialId: string
  label: string
}

export interface ActionItemModel {
  key: string
  category: ActionItemCategory
  // WHAT：发生了什么（一句话结论，不夸大）。
  what: string
  // 主视觉值：让人一眼看到冲突/规模，如「95% / 91%」。
  detail?: string
  // WHY：为什么值得处理。
  why: string
  // WHERE：主来源身份（材料 label / 审查标题），不含内部 ID。
  where: string
  // 来源数组：本事项涉及的全部材料身份；单项也用一个元素的数组。
  sources: ActionItemSource[]
  // 轻量上下文：所属审查与标准，如「春季终审 · 标准 v1」。
  context?: string
  // NEXT：现在能做什么，按推荐程度排序。
  actions: ActionItemAction[]
  // 低权重出处，如「由：一致性检查（程序）」。
  meta?: string
}
