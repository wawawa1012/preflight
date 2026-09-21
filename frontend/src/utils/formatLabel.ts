import type { MaterialSummary, SavedMaterial } from '../types/contracts'

// 材料格式标签的唯一来源：列表、材料头、上传预览共用，禁止在页面里散落映射。
export type MaterialFormat = SavedMaterial['format'] | MaterialSummary['format']

export function formatLabel(format: MaterialFormat): string {
  switch (format) {
    case 'md':
      return 'Markdown'
    case 'txt':
      return '纯文本'
    case 'docx':
      return 'Word 文档'
    default:
      return format
  }
}
