// 材料身份显示规则（全站唯一口径）：
// normalized(label) == normalized(filename) 时只显示一次，杜绝「DEMO.md · DEMO.md」；
// label 为空时 fallback filename；不同则 label 为主、filename 为次级出处。
export interface MaterialIdentity {
  primary: string
  secondary: string | null
}

function normalize(value: string): string {
  return value.normalize('NFC').trim().replace(/\s+/g, ' ').toLowerCase()
}

export function materialIdentity(label: string | null | undefined, filename: string): MaterialIdentity {
  const cleanLabel = (label ?? '').trim()
  // filename 空白时不得让 secondary 成为空串：退化为单行身份。
  if (filename.trim() === '') return { primary: cleanLabel || filename, secondary: null }
  if (cleanLabel === '' || normalize(cleanLabel) === normalize(filename)) {
    return { primary: filename, secondary: null }
  }
  return { primary: cleanLabel, secondary: filename }
}

// 下拉选项等单行场景：相同只出现一次，不同则「label · filename」。
export function identityLine(label: string | null | undefined, filename: string): string {
  const identity = materialIdentity(label, filename)
  return identity.secondary ? `${identity.primary} · ${identity.secondary}` : identity.primary
}
