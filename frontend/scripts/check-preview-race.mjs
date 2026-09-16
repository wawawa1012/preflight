// 最小前端状态时序检查（不引入测试框架）：
// 证明三个异步操作（生成预览/保存/读取 recent）互斥、busy 期间不能换文件、失败后可恢复。
// 运行：cd frontend && node scripts/check-preview-race.mjs
import { readFileSync } from 'node:fs'
import { createSSRApp } from 'vue'
import { ssrContextKey } from '@vue/runtime-core'
import { createServer } from 'vite'

const source = readFileSync(new URL('../src/views/PreviewView.vue', import.meta.url), 'utf8')

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })

// 静态：统一 busy 绑定与四个入口 guard。
check('file input 用 busy 禁用', /type="file"[\s\S]*?:disabled="busy"/.test(source))
check('生成预览按钮用 busy 禁用', source.includes(':disabled="!selectedFile || busy"'))
check('保存按钮用 busy 禁用', source.includes(':disabled="!previewedFile || busy"'))
check('读取按钮用 busy 禁用', /:disabled="busy"[\s\S]{0,40}@click="loadRecent"/.test(source))
check(
  '四个入口都有 busy guard',
  (source.match(/if \(busy\.value\) return/g) || []).length >= 4,
  (source.match(/if \(busy\.value\) return/g) || []).length,
)

const jsonResponse = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

const makePreview = (filename) => ({
  document_id: 'preview',
  filename,
  size_bytes: 10,
  sha256: 'a'.repeat(64),
  line_count: 1,
  blocks: [],
})

const makeSaved = (filename, id) => ({
  id,
  filename,
  size_bytes: 10,
  sha256: 'a'.repeat(64),
  line_count: 1,
  created_at: '2026-09-16T00:00:00+00:00',
  blocks: [],
})

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const module = await server.ssrLoadModule('/src/views/PreviewView.vue')
  // SSR 编译的 SFC setup 需要 SSR context；提供一个最小 context。
  const app = createSSRApp({})
  app.provide(ssrContextKey, { modules: new Set() })
  const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))

  let fetchCount = 0
  const fileA = new File(['# A\n'], 'A.md', { type: 'text/markdown' })
  const fileB = new File(['# B\n'], 'B.md', { type: 'text/markdown' })
  const fileC = new File(['# C\n'], 'C.md', { type: 'text/markdown' })

  // 场景一：生成预览进行中 —— 不能重复提交 / save / load / 换文件。
  bindings.onFileChange({ target: { files: [fileA] } })
  let releasePreview = null
  globalThis.fetch = () => {
    fetchCount += 1
    return new Promise((resolve) => {
      releasePreview = () => resolve(jsonResponse(makePreview('A.md')))
    })
  }
  const pendingUpload = bindings.upload()
  check('preview 中 busy=true 且 loading=true', bindings.busy.value === true && bindings.loading.value === true)

  await bindings.upload()
  await bindings.saveMaterial()
  await bindings.loadRecent()
  check('preview 中重复 upload/save/load 都不发请求', fetchCount === 1, `fetchCount=${fetchCount}`)
  check('preview 中 saving/loadingRecent 保持 false', bindings.saving.value === false && bindings.loadingRecent.value === false)

  bindings.onFileChange({ target: { files: [fileB] } })
  check('preview 中不能换文件', bindings.selectedFile.value === fileA)

  releasePreview()
  await pendingUpload
  check('preview 完成后 busy=false（控件恢复）', bindings.busy.value === false)
  check('preview 结果与当时选择一致（A.md）', bindings.preview.value?.filename === 'A.md' && bindings.preview.value?.id === null)

  // 场景二：保存进行中 —— 不能 upload / load / 换文件；旧响应不能顶替状态。
  bindings.onFileChange({ target: { files: [fileB] } })
  globalThis.fetch = async () => jsonResponse(makePreview('B.md'))
  await bindings.upload()
  check('准备保存的预览为 B.md', bindings.preview.value?.filename === 'B.md')

  let releaseSave = null
  globalThis.fetch = () => {
    fetchCount += 1
    return new Promise((resolve) => {
      releaseSave = () => resolve(jsonResponse(makeSaved('B.md', 'mat_saved_1')))
    })
  }
  const pendingSave = bindings.saveMaterial()
  check('saving 中 busy=true', bindings.busy.value === true)
  const countBeforeSave = fetchCount

  await bindings.upload()
  await bindings.loadRecent()
  bindings.onFileChange({ target: { files: [fileC] } })
  check('saving 中 upload/load/换文件都被拦截', fetchCount === countBeforeSave && bindings.selectedFile.value === fileB)

  releaseSave()
  await pendingSave
  check('saving 完成后展示已保存材料且 id 正确', bindings.preview.value?.id === 'mat_saved_1' && bindings.busy.value === false)

  // 场景三：读取 recent 进行中 —— 不能 upload / save / 换文件；成功后清除临时文件引用。
  let releaseRecent = null
  globalThis.fetch = () => {
    fetchCount += 1
    return new Promise((resolve) => {
      releaseRecent = () => resolve(jsonResponse(makeSaved('recent.md', 'mat_recent_1')))
    })
  }
  const pendingRecent = bindings.loadRecent()
  check('loadRecent 中 busy=true', bindings.busy.value === true)
  const countBeforeRecent = fetchCount

  await bindings.upload()
  await bindings.saveMaterial()
  bindings.onFileChange({ target: { files: [fileC] } })
  check('loadRecent 中 upload/save/换文件都被拦截', fetchCount === countBeforeRecent && bindings.selectedFile.value === fileB)

  releaseRecent()
  await pendingRecent
  check('loadRecent 成功展示 recent 材料', bindings.preview.value?.id === 'mat_recent_1')
  check('loadRecent 成功后清除临时文件引用', bindings.selectedFile.value === null && bindings.previewedFile.value === null)
  check('loadRecent 完成后 busy=false', bindings.busy.value === false)

  // 场景四：失败恢复；随后合法操作展示新状态，不被旧状态覆盖。
  globalThis.fetch = async () => {
    throw new Error('network down')
  }
  bindings.onFileChange({ target: { files: [fileC] } })
  await bindings.upload()
  check('失败后控件恢复且报错', bindings.busy.value === false && bindings.error.value.length > 0)

  globalThis.fetch = async () => jsonResponse(makePreview('C.md'))
  await bindings.upload()
  check(
    '失败后可正常上传并展示新结果（C.md 未保存）',
    bindings.preview.value?.filename === 'C.md' && bindings.preview.value?.id === null,
  )
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
