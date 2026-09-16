// 最小前端状态时序检查（不引入测试框架）：
// 证明 /materials/new 工作台的上传与保存互斥、busy 期间不能换文件、保存成功跳转、失败不跳转且可恢复；
// 并静态核对 Materials IA：/materials/new 是正式路由，/preview 只做兼容重定向。
// 运行：cd frontend && node scripts/check-preview-race.mjs
import { readFileSync } from 'node:fs'
import { createSSRApp } from 'vue'
import { ssrContextKey } from '@vue/runtime-core'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'

const source = readFileSync(new URL('../src/views/MaterialNewView.vue', import.meta.url), 'utf8')
const routerSource = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })

// 静态：Materials IA 与 busy 绑定、入口 guard、recent UI 已移除。
check('/materials/new 是正式路由', routerSource.includes("path: '/materials/new'"))
check('/preview 兼容重定向到 /materials/new', /\{\s*path: '\/preview',\s*redirect: '\/materials\/new'\s*\}/.test(routerSource))
check('preview 不再是平级导航目标', !routerSource.includes("name: 'preview'"))
check('file input 用 busy 禁用', /type="file"[\s\S]*?:disabled="busy"/.test(source))
check('生成预览按钮用 busy 禁用', source.includes(':disabled="!selectedFile || busy"'))
check('保存按钮用 busy 禁用', source.includes(':disabled="!previewedFile || busy"'))
check(
  '三个以上入口都有 busy guard',
  (source.match(/if \(busy\.value\) return/g) || []).length >= 3,
  (source.match(/if \(busy\.value\) return/g) || []).length,
)
check('recent 用户交互已移除', !source.includes('loadRecent') && !source.includes('读取最近保存的材料'))
check('不使用 localStorage 存状态', !source.includes('localStorage'))

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

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const module = await server.ssrLoadModule('/src/views/MaterialNewView.vue')
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/materials/new', component: { template: '<div />' } },
      { path: '/materials/:materialId', component: { template: '<div />' } },
    ],
  })
  const app = createSSRApp({})
  app.use(router)
  await router.push('/materials/new')
  await router.isReady()
  // SSR 编译的 SFC setup 需要 SSR context；提供一个最小 context。
  app.provide(ssrContextKey, { modules: new Set() })
  const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))

  let fetchCount = 0
  const fileA = new File(['# A\n'], 'A.md', { type: 'text/markdown' })
  const fileB = new File(['# B\n'], 'B.md', { type: 'text/markdown' })
  const fileC = new File(['# C\n'], 'C.md', { type: 'text/markdown' })

  // 场景一：生成预览进行中 —— 不能重复提交 / 保存 / 换文件。
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
  check('preview 中重复 upload/save 都不发请求', fetchCount === 1, `fetchCount=${fetchCount}`)
  check('preview 中 saving 保持 false', bindings.saving.value === false)

  bindings.onFileChange({ target: { files: [fileB] } })
  check('preview 中不能换文件', bindings.selectedFile.value === fileA)

  releasePreview()
  await pendingUpload
  check('preview 完成后 busy=false（控件恢复）', bindings.busy.value === false)
  check('preview 结果与当时选择一致（A.md）', bindings.preview.value?.filename === 'A.md')

  // 场景二：保存进行中 —— 不能 upload / 换文件；成功后 router.replace 到 /materials/:id。
  bindings.onFileChange({ target: { files: [fileB] } })
  globalThis.fetch = async () => jsonResponse(makePreview('B.md'))
  await bindings.upload()
  check('准备保存的预览为 B.md', bindings.preview.value?.filename === 'B.md')

  let releaseSave = null
  globalThis.fetch = () => {
    fetchCount += 1
    return new Promise((resolve) => {
      releaseSave = () =>
        resolve(
          jsonResponse({
            id: 'mat_saved_1',
            filename: 'B.md',
            size_bytes: 10,
            sha256: 'a'.repeat(64),
            line_count: 1,
            created_at: '2026-09-16T00:00:00+00:00',
            blocks: [],
          }),
        )
    })
  }
  const pendingSave = bindings.saveMaterial()
  check('saving 中 busy=true', bindings.busy.value === true)
  const countBeforeSave = fetchCount

  await bindings.upload()
  bindings.onFileChange({ target: { files: [fileC] } })
  check('saving 中 upload/换文件都被拦截', fetchCount === countBeforeSave && bindings.selectedFile.value === fileB)

  releaseSave()
  await pendingSave
  await flush()
  check('保存成功后跳转到 /materials/mat_saved_1', router.currentRoute.value.path === '/materials/mat_saved_1', router.currentRoute.value.path)
  check('saving 完成后 busy=false', bindings.busy.value === false)

  // 场景三：失败恢复；保存失败不跳转（先回到 /materials/new 模拟再次上传）。
  await router.push('/materials/new')
  globalThis.fetch = async () => {
    throw new Error('network down')
  }
  bindings.onFileChange({ target: { files: [fileC] } })
  await bindings.upload()
  check('预览失败后控件恢复且报错', bindings.busy.value === false && bindings.error.value.length > 0 && bindings.preview.value === null)

  globalThis.fetch = async () => jsonResponse(makePreview('C.md'))
  await bindings.upload()
  check('失败后可正常上传并展示新结果（C.md）', bindings.preview.value?.filename === 'C.md')

  globalThis.fetch = async () => {
    throw new Error('save failed')
  }
  await bindings.saveMaterial()
  await flush()
  check(
    '保存失败：报错、busy 恢复、停留在 /materials/new 不跳转',
    bindings.error.value.length > 0 && bindings.busy.value === false && router.currentRoute.value.path === '/materials/new',
    router.currentRoute.value.path,
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
