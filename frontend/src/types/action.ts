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

export interface ActionItemModel {
  key: string
  // WHAT：发生了什么（一句话结论，不夸大）。
  what: string
  // 主视觉值：让人一眼看到冲突/规模，如「95% / 91%」。
  detail?: string
  // WHY：为什么值得处理。
  why: string
  // WHERE：来源身份（材料 label / 审查标题），不含内部 ID。
  where: string
  // NEXT：现在能做什么，按推荐程度排序。
  actions: ActionItemAction[]
  // 低权重出处，如「由：一致性检查（程序）」。
  meta?: string
}
