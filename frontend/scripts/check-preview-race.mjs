// 最小前端时序检查（不引入测试框架）：
// 证明上传进行中控件禁用、无法重复提交、完成后状态与当前选择一致。
// 运行：cd frontend && node scripts/check-preview-race.mjs
import { readFileSync } from 'node:fs'
import { createSSRApp } from 'vue'
import { ssrContextKey } from '@vue/runtime-core'
import { createServer } from 'vite'

const source = readFileSync(new URL('../src/views/PreviewView.vue', import.meta.url), 'utf8')

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })

// 静态绑定：上传中禁用文件选择与提交，并有入口 guard。
check('file input 在上传中禁用', /type="file"[\s\S]*?:disabled="loading"/.test(source))
check('提交按钮在上传中禁用', /:disabled="!selectedFile \|\| loading"/.test(source))
check('upload 入口存在 loading guard', source.includes('if (loading.value) return'))

const makePreview = (filename) => ({
  document_id: 'preview',
  filename,
  size_bytes: 10,
  sha256: 'a'.repeat(64),
  line_count: 1,
  blocks: [],
})

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const module = await server.ssrLoadModule('/src/views/PreviewView.vue')
  // SSR 编译的 SFC setup 需要 SSR context；提供一个最小 context。
  const app = createSSRApp({})
  app.provide(ssrContextKey, { modules: new Set() })
  const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))

  // 场景一：上传 A.md 且响应延迟；期间重复提交不应产生第二个请求。
  let fetchCount = 0
  let releaseFetch = null
  globalThis.fetch = () => {
    fetchCount += 1
    return new Promise((resolve) => {
      releaseFetch = () =>
        resolve(new Response(JSON.stringify(makePreview('A.md')), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    })
  }

  const fileA = new File(['# A\n'], 'A.md', { type: 'text/markdown' })
  bindings.onFileChange({ target: { files: [fileA] } })

  const firstUpload = bindings.upload()
  check('上传开始后 loading 为 true', bindings.loading.value === true)

  await bindings.upload()
  check('上传进行中重复提交被 guard 拦截', fetchCount === 1, `fetchCount=${fetchCount}`)

  releaseFetch()
  await firstUpload
  check('请求完成后 loading 为 false（控件恢复可用）', bindings.loading.value === false)
  check('结果与当前选择一致（A.md）', bindings.preview.value?.filename === 'A.md')

  // 场景二：完成后选择 B.md，结果应来自 B.md。
  const fileB = new File(['# B\n'], 'B.md', { type: 'text/markdown' })
  bindings.onFileChange({ target: { files: [fileB] } })
  globalThis.fetch = async () =>
    new Response(JSON.stringify(makePreview('B.md')), { status: 200, headers: { 'Content-Type': 'application/json' } })
  await bindings.upload()
  check('完成后可上传新选择并得到对应结果（B.md）', bindings.preview.value?.filename === 'B.md')

  // 场景三：失败时清空旧结果并报错（保持既有行为）。
  globalThis.fetch = async () => {
    throw new Error('network down')
  }
  await bindings.upload()
  check('失败时清空旧 preview 并报错', bindings.preview.value === null && bindings.error.value.length > 0)
} finally {
  await server.close()
}

let failed = 0
for (const item of results) {
  if (!item.ok) failed += 1
  console.log(`${item.ok ? 'PASS' : 'FAIL'} ${item.name}${item.detail ? ' | ' + item.detail : ''}`)
}
console.log(`SUMMARY: ${results.length - failed}/${results.length} passed`)
if (failed > 0) process.exit(1)
