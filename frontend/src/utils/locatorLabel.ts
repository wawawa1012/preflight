import type { Locator } from '../types/contracts'

// Locator 是唯一的位置事实源：kind 决定中文说法，index 是 1 基序号。
// md 落 line（第 N 行）；PDF/PPTX/DOCX 各自成句，调用点不变。
export function locatorLabel(locator: Pick<Locator, 'kind' | 'index'> | null | undefined): string {
  if (!locator) return '位置未知'
  switch (locator.kind) {
    case 'line':
      return `第 ${locator.index} 行`
    case 'slide':
      return `第 ${locator.index} 张幻灯片`
    case 'page':
      return `第 ${locator.index} 页`
    case 'paragraph':
      return `第 ${locator.index} 段`
    default:
      // 冻结契约里只有四种 kind；真出现新 kind 时也不假装是行号。
      return `第 ${locator.index} 处`
  }
}
