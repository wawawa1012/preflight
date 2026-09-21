import type { Locator } from '../types/contracts'

// 位置文案的唯一来源：kind 决定中文说法，index 是 1 基序号。
// md/txt 落 line（第 N 行）；docx 落 paragraph / table_cell；PDF/PPTX 落 page / slide。
// 完整 Locator 可直接传入；旧快照兜底只需 kind + index（可选表格细分字段）。
type LocatorLike = Pick<Locator, 'kind' | 'index'> &
  Partial<Pick<Locator, 'row_index' | 'cell_index' | 'paragraph_index'>>

// 1 基序号才有效；null / undefined / 0 一律不参与文案，避免「第 0 行」「第 null 行」。
function isPositiveIndex(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}

export function locatorLabel(locator: LocatorLike | null | undefined): string {
  if (!locator || !isPositiveIndex(locator.index)) return '位置未知'
  switch (locator.kind) {
    case 'line':
      return `第 ${locator.index} 行`
    case 'paragraph':
      return `第 ${locator.index} 段`
    case 'page':
      return `第 ${locator.index} 页`
    case 'slide':
      return `第 ${locator.index} 张幻灯片`
    case 'table_cell': {
      // 冻结文案：表格 N · 第 R 行 · 第 C 列 · 第 P 段；细分字段缺失时省略该段。
      const parts = [`表格 ${locator.index}`]
      if (isPositiveIndex(locator.row_index)) parts.push(`第 ${locator.row_index} 行`)
      if (isPositiveIndex(locator.cell_index)) parts.push(`第 ${locator.cell_index} 列`)
      if (isPositiveIndex(locator.paragraph_index)) parts.push(`第 ${locator.paragraph_index} 段`)
      return parts.join(' · ')
    }
    default:
      // 契约里暂无其他 kind；真出现新 kind 时也不假装是行号。
      return `第 ${locator.index} 处`
  }
}
