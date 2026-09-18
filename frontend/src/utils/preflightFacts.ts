import type { AgentProposal } from '../types/contracts'

/** 提案列表新到旧；第一条 completed 即该 criterion 最新完成预检。 */
export function latestCompletedProposal(proposals: AgentProposal[], criterionId: string) {
  return proposals.find((item) => item.criterion_id === criterionId && item.status === 'completed') ?? null
}

export function latestProposal(proposals: AgentProposal[], criterionId: string) {
  return proposals.find((item) => item.criterion_id === criterionId) ?? null
}

export function passedCount(proposal: AgentProposal | null) {
  if (!proposal) return 0
  return proposal.candidates.filter((item) => item.validation_status === 'passed').length
}

export function pendingPassedCount(proposal: AgentProposal | null) {
  if (!proposal) return 0
  return proposal.candidates.filter(
    (item) => item.validation_status === 'passed' && item.review_status === 'unreviewed',
  ).length
}

export function confirmedCount(links: { criterion_id: string }[], criterionId: string) {
  return links.filter((item) => item.criterion_id === criterionId).length
}
