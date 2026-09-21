// Request Scope（请求身份守卫，Sprint 3 异步稳定化）。
//
// 区分两件事，不许混用：
// - CONTENT FINGERPRINT：回答/来源内容是否仍与反馈匹配（如 ResponseCoachPanel 的 fingerprint）。
// - REQUEST IDENTITY：这个响应是否仍属于发起时的 Review / material / task / session target。
// 本 helper 只负责后者：用代次（generation）回答「响应回来时，它还是不是当前请求」。
//
// 规则（冻结）：
// 1. 一次 begin 作废旧请求：同一 scope 内只认最新一代；invalidate 也推进代次。
// 2. result / error / finally(loading 复位) / session 写入，四类写入都必须经过 commit，无一例外。
// 3. 不同 scope 实例互不作废（例如 load 与 run 是两个独立 scope）。
// 4. invalidate 只用于上下文切换（watch）与组件 unmount；abort/AbortController 不作为正确性保证。
//
// 故意很小：没有 scheduler / queue / cache / 事件总线 / 泛型 fetch 包装。
export interface RequestTicket<C> {
  /** 发起时捕获的不可变上下文快照（如 { reviewId, materialId, storageKey }）。 */
  readonly context: C
  isCurrent(): boolean
  /** 唯一写入门：identity 仍 current 才执行 write；返回是否已提交。 */
  commit(write: (context: C) => void): boolean
}

export interface RequestScope {
  /** 发起请求时调用：作废旧请求，捕获上下文快照。 */
  begin<C>(context: C): RequestTicket<C>
  /** 上下文切换 / unmount：作废旧请求。 */
  invalidate(): void
}

export function createRequestScope(): RequestScope {
  let generation = 0
  return {
    begin<C>(context: C): RequestTicket<C> {
      generation += 1
      const ticketGeneration = generation
      return {
        context,
        isCurrent: () => ticketGeneration === generation,
        commit: (write: (context: C) => void) => {
          if (ticketGeneration !== generation) return false
          write(context)
          return true
        },
      }
    },
    invalidate: () => {
      generation += 1
    },
  }
}
