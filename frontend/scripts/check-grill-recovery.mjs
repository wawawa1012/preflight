// 模拟评审刷新恢复（grillRecovery）的 targeted 检查：
// 身份绑定（review + rubric 版本）、版本号、损坏数据、quote 复验。
// 纯 node：esbuild 把 TS bundle 到临时文件后 dynamic import，不起测试框架。
import { build } from 'esbuild'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const tempDir = mkdtempSync(join(tmpdir(), 'grill-recovery-'))
const bundlePath = join(tempDir, 'grillRecovery.mjs')
await build({
  entryPoints: ['src/utils/grillRecovery.ts'],
  bundle: true,
  format: 'esm',
  outfile: bundlePath,
  logLevel: 'silent',
})
const recovery = await import(pathToFileURL(bundlePath).href)
const { saveGrillSnapshot, loadGrillSnapshot, verifyRestoredQuestion } = recovery

let passed = 0
let failed = 0
function check(name, condition) {
  if (condition) {
    passed += 1
    console.log(`PASS ${name}`)
  } else {
    failed += 1
    console.log(`FAIL ${name}`)
  }
}

const question = {
  prompt: '准确率怎么测的？',
  quote: '准确率 93%',
  block_id: 'blk_1',
  locator: { kind: 'line', index: 7 },
  start: 10,
  end: 17,
  trigger: 'numeric',
  why: '数值缺少口径',
  preparation: ['准备测试条件'],
}
const context = { reviewId: 'rev_a', rubricId: 'rubric_x', rubricRevision: 2 }
const snapshot = {
  version: 1,
  ...context,
  materialId: 'mat_a',
  generatedAt: '2026-09-21T10:00:00.000Z',
  questions: [question],
  coachDrafts: { 'blk_1:10:abc': { answer: '我的回答', sourceExcluded: false } },
}

// 1. 往返：同身份可恢复，且 coachDrafts 不含 feedback 字段。
saveGrillSnapshot(snapshot)
const restored = loadGrillSnapshot(context)
check('同身份 save/load 往返恢复问题与草稿', restored !== null && restored.questions.length === 1 && restored.coachDrafts['blk_1:10:abc']?.answer === '我的回答')
check('恢复快照不含 feedback', restored !== null && !('feedback' in (restored.coachDrafts['blk_1:10:abc'] ?? {})))

// 2. 身份不匹配：换 rubric 版本 / 换 Review 一律 null。
check('rubric_revision 变化后不继承', loadGrillSnapshot({ ...context, rubricRevision: 3 }) === null)
check('rubric_id 变化后不继承', loadGrillSnapshot({ ...context, rubricId: 'rubric_y' }) === null)
check('换 Review 后不可见', loadGrillSnapshot({ ...context, reviewId: 'rev_b' }) === null)

// 3. 版本与损坏数据：null，不抛错。
saveGrillSnapshot({ ...snapshot, version: 99 })
check('版本号不符返回 null', loadGrillSnapshot(context) === null)
saveGrillSnapshot(snapshot)
check('版本不符后可被正确快照覆盖', loadGrillSnapshot(context) !== null)

// 4. 复验：quote == block.text[start:end]，block 缺失或 span 偏移都判失败。
const blocks = [{ id: 'blk_1', text: '0123456789准确率 93% 其余文本' }]
check('复验通过：span 精确对上', verifyRestoredQuestion({ ...question, start: 10, end: 17 }, blocks))
check('复验拒绝：span 偏移', !verifyRestoredQuestion({ ...question, start: 9, end: 16 }, blocks))
check('复验拒绝：block 不存在', !verifyRestoredQuestion({ ...question, block_id: 'blk_x' }, blocks))
check('复验拒绝：quote 被改动', !verifyRestoredQuestion({ ...question, quote: '准确率 95%' }, blocks))

rmSync(tempDir, { recursive: true, force: true })
console.log(`SUMMARY: ${passed}/${passed + failed} passed`)
process.exit(failed > 0 ? 1 : 0)
