// 迟到响应守卫（Stale Response Guard，Sprint 2 P0）。
// 每个异步入口在发起时取一枚 token；await 返回后先校验 token 仍是当前代，
// 否则结果直接丢弃——用户切换 Review / 材料 / 重新运行后，旧响应不得污染新上下文。
// 纯 session 内存机制，不要求 backend 建 job system。
export interface AsyncGuard {
  next: () => number
  isCurrent: (token: number) => boolean
  invalidate: () => void
}

export function createAsyncGuard(): AsyncGuard {
  let generation = 0
  return {
    next: () => ++generation,
    isCurrent: (token: number) => token === generation,
    invalidate: () => {
      generation += 1
    },
  }
}
