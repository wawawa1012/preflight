// Request Scope 健身测试（纯 node，不引入测试框架、不起 vite server）。
// 目标：把「异步响应属于谁」的最小规则钉死——
// 1) A 发出 → 切上下文(invalidate) → B 发出 → A 后返回：A 的 result/error/finally/session 四类写入全部被拒；
// 2) 旧请求 finally 晚到：A 的 loading 复位不得执行（B 的 loading 不被清掉）；
// 3) Coach：旧响应 commit 不写；写入用 ticket.context.storageKey 落发起时的 k1，而不是外部当前 k2；
// 4) invalidate 后响应：commit 一律拒绝；
// 5) 两个独立 scope（load/run）：一方 invalidate 不影响另一方 ticket 提交。
// 运行：cd frontend && node scripts/check-request-scope.mjs
import { build } from 'esbuild'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })

// helper 是纯 TS：bundle 到临时目录后 dynamic import。
const outDir = mkdtempSync(join(tmpdir(), 'preflight-request-scope-'))
const outFile = join(outDir, 'requestScope.mjs')
await build({
  entryPoints: [fileURLToPath(new URL('../src/utils/requestScope.ts', import.meta.url))],
  outfile: outFile,
  bundle: true,
  format: 'esm',
  platform: 'node',
  logLevel: 'silent',
})
const { createRequestScope } = await import(pathToFileURL(outFile).href)
rmSync(outDir, { recursive: true, force: true })

// controlled deferred Promise：手动决定「响应什么时候回来」。
const deferred = () => {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

try {
  // ——— 1. 上下文切换后，旧响应四类写入全部被拒；新请求正常提交 ———
  {
    const scope = createRequestScope()
    const state = { result: null, error: null, loading: false, session: null }
    const aResponse = deferred()
    const bResponse = deferred()

    const runA = (async () => {
      const ticket = scope.begin({ reviewId: 'rev_a' })
      state.loading = true
      try {
        const value = await aResponse.promise
        ticket.commit((context) => {
          state.result = `${value}:${context.reviewId}`
        })
        ticket.commit(() => {
          state.session = 'A-session'
        })
      } catch (cause) {
        ticket.commit(() => {
          state.error = String(cause)
        })
      } finally {
        ticket.commit(() => {
          state.loading = false
        })
      }
    })()

    // 上下文切换（watch）：作废 A，随后 B 发出。
    scope.invalidate()
    const runB = (async () => {
      const ticket = scope.begin({ reviewId: 'rev_b' })
      state.loading = true
      const value = await bResponse.promise
      ticket.commit((context) => {
        state.result = `${value}:${context.reviewId}`
      })
      ticket.commit(() => {
        state.loading = false
      })
    })()

    // A 后返回：四类写入都应被拒。
    aResponse.reject(new Error('A 失败'))
    await runA
    check(
      '1. 切上下文后 A 的 result/error/finally/session 全部被拒且无副作用',
      state.result === null && state.error === null && state.session === null && state.loading === true,
      `result=${state.result} error=${state.error} session=${state.session} loading=${state.loading}`,
    )

    // B 正常提交。
    bResponse.resolve('B')
    await runB
    check('1. B 正常提交且落地正确上下文', state.result === 'B:rev_b' && state.loading === false, `result=${state.result}`)
  }

  // ——— 2. 旧请求 finally 晚到，不得复位 B 的 loading ———
  {
    const scope = createRequestScope()
    const state = { loading: false }
    const aResponse = deferred()
    const bResponse = deferred()

    const runA = (async () => {
      const ticket = scope.begin({ reviewId: 'rev_a' })
      state.loading = true
      await aResponse.promise
      ticket.commit(() => {
        state.loading = false
      })
    })()

    scope.invalidate()
    const runB = (async () => {
      const ticket = scope.begin({ reviewId: 'rev_b' })
      state.loading = true
      await bResponse.promise
      ticket.commit(() => {
        state.loading = false
      })
    })()

    aResponse.resolve('A 迟到 finally')
    await runA
    check('2. A 的 loading 复位 commit 不执行（B 仍 running）', state.loading === true, `loading=${state.loading}`)

    bResponse.resolve('B')
    await runB
    check('2. B 的 loading 复位正常执行', state.loading === false, `loading=${state.loading}`)
  }

  // ——— 3. Coach：storageKey/fingerprint 身份 ———
  {
    const drafts = {}
    const save = (storageKey, value) => {
      drafts[storageKey] = { ...(drafts[storageKey] ?? {}), ...value }
    }

    // (a) 响应回来前外部把目标改成 k2（新 begin）：旧响应 commit 不写。
    const scope = createRequestScope()
    const aResponse = deferred()
    const bResponse = deferred()
    const runA = (async () => {
      const ticket = scope.begin({ storageKey: 'k1', fingerprint: 'f1' })
      const response = await aResponse.promise
      ticket.commit((context) => {
        save(context.storageKey, { feedback: { fingerprint: context.fingerprint, response } })
      })
    })()
    const runB = (async () => {
      const ticket = scope.begin({ storageKey: 'k2', fingerprint: 'f2' })
      const response = await bResponse.promise
      ticket.commit((context) => {
        save(context.storageKey, { feedback: { fingerprint: context.fingerprint, response } })
      })
    })()

    aResponse.resolve('old')
    await runA
    check('3a. 目标改 k2 后旧响应不写', drafts.k1 === undefined, JSON.stringify(drafts))

    bResponse.resolve('new')
    await runB
    check(
      '3a. 新响应写入发起时 k2/f2',
      drafts.k2?.feedback?.response === 'new' && drafts.k2?.feedback?.fingerprint === 'f2',
      JSON.stringify(drafts),
    )

    // (b) 用 ticket.context.storageKey 写入，落的是发起时的 k1，而不是外部当前 k2。
    const captureScope = createRequestScope()
    const ticket = captureScope.begin({ storageKey: 'k1', fingerprint: 'f1' })
    const ambientStorageKey = 'k2' // 模拟响应回来时 props.storageKey 已经变成 k2
    const wrote = ticket.commit((context) => {
      save(context.storageKey, { feedback: { fingerprint: context.fingerprint, response: 'captured' } })
    })
    check(
      '3b. 写入用捕获的 k1 而不是外部当前 k2',
      wrote === true &&
        drafts.k1?.feedback?.response === 'captured' &&
        drafts.k1?.feedback?.fingerprint === 'f1' &&
        drafts.k2?.feedback?.response === 'new' &&
        ambientStorageKey === 'k2',
      JSON.stringify({ k1: drafts.k1, k2: drafts.k2 }),
    )
  }

  // ——— 4. invalidate 后响应：commit 一律拒绝 ———
  {
    const scope = createRequestScope()
    const ticket = scope.begin({ reviewId: 'rev_a' })
    let wrote = false
    scope.invalidate()
    const committed = ticket.commit(() => {
      wrote = true
    })
    check('4. invalidate 后 commit 被拒且 isCurrent=false', committed === false && ticket.isCurrent() === false && wrote === false)
  }

  // ——— 5. 两个独立 scope：互不作废 ———
  {
    const loadScope = createRequestScope()
    const runScope = createRequestScope()
    const loadResponse = deferred()
    const runResponse = deferred()

    const loadTicket = loadScope.begin({ purpose: 'load' })
    const runTicket = runScope.begin({ purpose: 'run' })

    loadScope.invalidate()
    runResponse.resolve('run')
    await runResponse.promise
    const runCommitted = runTicket.commit((context) => context.purpose === 'run')
    check(
      '5. load.invalidate 不影响 run ticket 提交',
      runCommitted === true && loadTicket.isCurrent() === false && runTicket.isCurrent() === true,
    )

    const loadTicket2 = loadScope.begin({ purpose: 'load' })
    runScope.invalidate()
    loadResponse.resolve('load')
    await loadResponse.promise
    const loadCommitted = loadTicket2.commit((context) => context.purpose === 'load')
    check(
      '5. run.invalidate 不影响 load ticket 提交',
      loadCommitted === true && runTicket.isCurrent() === false && loadTicket2.isCurrent() === true,
    )
  }
} catch (error) {
  check('测试脚本无异常', false, error instanceof Error ? error.stack : String(error))
}

let failed = 0
for (const item of results) {
  if (!item.ok) failed += 1
  console.log(`${item.ok ? 'PASS' : 'FAIL'} ${item.name}${item.detail ? ' | ' + item.detail : ''}`)
}
console.log(`SUMMARY: ${results.length - failed}/${results.length} passed`)
if (failed > 0) process.exit(1)
