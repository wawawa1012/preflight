<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import type {
  AgentProposal,
  Block,
  CriterionEvidenceLink,
  EvidenceAnnotation,
  ProposalAcceptance,
  ProposalCandidate,
  Rubric,
  RubricBinding,
  SavedMaterial,
} from '../types/contracts'
import BlockList from '../components/BlockList.vue'
import MaterialHeader from '../components/MaterialHeader.vue'
import { formatSavedAt } from '../utils/format'
import { formatLabel } from '../utils/formatLabel'
import { locatorLabel } from '../utils/locatorLabel'
import { confirmedCount, latestCompletedProposal, latestProposal, passedCount } from '../utils/preflightFacts'

const route = useRoute()
const materialId = String(route.params.materialId)

const material = ref<SavedMaterial | null>(null)
const loading = ref(true)
const notFound = ref(false)
const error = ref('')

// —— 证据标注（identity 层：只表示引用了真实原文） ——
const annotations = ref<EvidenceAnnotation[]>([])
const annotationsLoading = ref(false)
const annotationsError = ref('')
const selectedBlock = ref<Block | null>(null)
const quoteInput = ref('')
const noteInput = ref('')
const savingAnnotation = ref(false)
const annotationError = ref('')
const annotationNotice = ref('')
const deletingAnnotationId = ref('')
const deleteAnnotationError = ref('')
const confirmDeleteId = ref('')

// —— 评分标准绑定与人工关联（adjudication 层：只表示“人判断它相关”） ——
const rubrics = ref<Rubric[]>([])
const rubricsLoading = ref(false)
const rubricsError = ref('')
const binding = ref<RubricBinding | null>(null)
const bindingLoading = ref(false)
const bindingError = ref('')
const bindingNotice = ref('')
const bindingBusy = ref(false)
const links = ref<CriterionEvidenceLink[]>([])
const linksLoading = ref(false)
const linksError = ref('')
const linkAnnotation = ref<EvidenceAnnotation | null>(null)
const linkCriterionId = ref('')
const linkRationale = ref('')
const savingLink = ref(false)
const linkError = ref('')
const linkNotice = ref('')
const deletingLinkId = ref('')

// —— Agent 提案（单 criterion AI 预检；LLM 只提出候选，服务端验证，人工裁决） ——
const proposals = ref<AgentProposal[]>([])
const proposalsLoading = ref(false)
const proposalsError = ref('')
const proposingIds = ref<string[]>([])
const preflightStartedAt = ref<Record<string, number>>({})
const preflightNow = ref(Date.now())
let preflightClock: ReturnType<typeof setInterval> | null = null
const acceptingCandidateId = ref('')
const acceptingBatchCriterionId = ref('')
const rejectingCandidateId = ref('')
const rejectFormId = ref('')
const rejectReasonInput = ref('')
const proposalError = ref('')
const proposalErrorDetail = ref('')
const proposalNotice = ref('')

// —— 折叠（易用性：默认收起长列表，标题可展开） ——
const evidenceOpen = ref(false)
const blocksOpen = ref(false)

// —— 锚点导航 ——
const highlightedBlockId = ref('')
const anchorNotice = ref('')

// 统一互斥：任一写操作进行中都不再开始另一个，防止重复提交与旧响应覆盖。
const busy = computed(
  () =>
    savingAnnotation.value ||
    savingLink.value ||
    bindingBusy.value ||
    deletingAnnotationId.value !== '' ||
    deletingLinkId.value !== '' ||
    proposingIds.value.length > 0 ||
    acceptingCandidateId.value !== '' ||
    acceptingBatchCriterionId.value !== '' ||
    rejectingCandidateId.value !== '',
)

const boundRubric = computed(() => {
  const current = binding.value
  if (!current) return null
  return rubrics.value.find(item => item.id === current.rubric_id && item.revision === current.rubric_revision) ?? null
})

const annotatedCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const item of annotations.value) {
    counts[item.block_id] = (counts[item.block_id] ?? 0) + 1
  }
  return counts
})

async function requestJson(path: string, options: RequestInit = {}) {
  const response = await fetch(path, options)
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const code = body && body.code ? body.code : String(response.status)
    throw new Error(body && body.message ? `${body.message}（${code}）` : `HTTP ${response.status}`)
  }
  return body
}

async function loadMaterial() {
  loading.value = true
  error.value = ''
  notFound.value = false
  try {
    const response = await fetch(`/api/v1/materials/${encodeURIComponent(materialId)}`)
    const body = await response.json().catch(() => null)
    if (response.status === 404) {
      // 未知 ID 明确报“找不到”，不回退任何本地 mock。
      notFound.value = true
      return
    }
    if (!response.ok) {
      throw new Error(body && body.message ? body.message : `HTTP ${response.status}`)
    }
    material.value = body as SavedMaterial
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function loadAnnotations() {
  annotationsLoading.value = true
  annotationsError.value = ''
  try {
    annotations.value = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/evidence-annotations`,
    )) as EvidenceAnnotation[]
  } catch (cause) {
    annotationsError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    annotationsLoading.value = false
  }
}

async function loadRubrics() {
  rubricsLoading.value = true
  rubricsError.value = ''
  try {
    rubrics.value = (await requestJson('/api/v1/rubrics')) as Rubric[]
  } catch (cause) {
    rubricsError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    rubricsLoading.value = false
  }
}

async function loadBinding() {
  bindingLoading.value = true
  bindingError.value = ''
  try {
    binding.value = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/rubric-binding`,
    )) as RubricBinding | null
  } catch (cause) {
    bindingError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    bindingLoading.value = false
  }
}

async function loadLinks() {
  linksLoading.value = true
  linksError.value = ''
  try {
    links.value = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/criterion-evidence-links`,
    )) as CriterionEvidenceLink[]
  } catch (cause) {
    linksError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    linksLoading.value = false
  }
}

async function bindRubric(rubric: Rubric) {
  if (busy.value) return
  bindingBusy.value = true
  bindingError.value = ''
  bindingNotice.value = ''
  try {
    const created = (await requestJson(`/api/v1/materials/${encodeURIComponent(materialId)}/rubric-binding`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rubric_id: rubric.id, rubric_revision: rubric.revision }),
    })) as RubricBinding
    binding.value = created
    bindingNotice.value = `已绑定 ${rubric.title}（rev${rubric.revision}）`
  } catch (cause) {
    bindingError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    bindingBusy.value = false
  }
}

// —— 证据标注操作 ——

function selectBlock(block: Block) {
  if (busy.value) return
  selectedBlock.value = block
  quoteInput.value = block.text
  noteInput.value = ''
  annotationError.value = ''
  annotationNotice.value = ''
}

function cancelSelection() {
  if (busy.value) return
  selectedBlock.value = null
  quoteInput.value = ''
  noteInput.value = ''
  annotationError.value = ''
}

async function saveAnnotation() {
  if (busy.value) return
  const block = selectedBlock.value
  if (!block) {
    annotationError.value = '请先在原文段落行选择“标注”'
    return
  }
  savingAnnotation.value = true
  annotationError.value = ''
  annotationNotice.value = ''
  try {
    // 只提交 block_id + quote + note；material_id/span 由服务端校验并派生。
    const created = (await requestJson('/api/v1/evidence-annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ block_id: block.id, quote: quoteInput.value, note: noteInput.value || null }),
    })) as EvidenceAnnotation
    annotations.value = [...annotations.value, created]
    // 成功路径直接清空（此时 saving 仍为 true，不能走带 guard 的 cancelSelection）。
    selectedBlock.value = null
    quoteInput.value = ''
    noteInput.value = ''
    // 「证据」默认折叠：刚保存的引用要看得见。
    evidenceOpen.value = true
    annotationNotice.value = '已保存证据标注'
  } catch (cause) {
    annotationError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    savingAnnotation.value = false
  }
}

function askDeleteAnnotation(annotation: EvidenceAnnotation) {
  if (busy.value) return
  confirmDeleteId.value = annotation.id
  deleteAnnotationError.value = ''
}

function cancelDeleteAnnotation() {
  if (busy.value) return
  confirmDeleteId.value = ''
}

async function deleteAnnotation(annotation: EvidenceAnnotation) {
  if (busy.value) return
  deletingAnnotationId.value = annotation.id
  deleteAnnotationError.value = ''
  try {
    const response = await fetch(
      `/api/v1/materials/${encodeURIComponent(materialId)}/evidence-annotations/${encodeURIComponent(annotation.id)}`,
      { method: 'DELETE' },
    )
    if (response.status !== 204) {
      const body = await response.json().catch(() => null)
      const code = body && body.code ? body.code : String(response.status)
      throw new Error(body && body.message ? `${body.message}（${code}）` : `HTTP ${response.status}`)
    }
    annotations.value = annotations.value.filter(item => item.id !== annotation.id)
    links.value = links.value.filter(item => item.annotation_id !== annotation.id)
    if (linkAnnotation.value && linkAnnotation.value.id === annotation.id) {
      linkAnnotation.value = null
      linkCriterionId.value = ''
      linkRationale.value = ''
      linkError.value = ''
    }
    confirmDeleteId.value = ''
  } catch (cause) {
    deleteAnnotationError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    deletingAnnotationId.value = ''
  }
}

// —— 关联操作（adjudication 层：只记录“人判断相关”，不做满足判定） ——

function linksFor(criterionId: string) {
  return links.value.filter(item => item.criterion_id === criterionId)
}

function annotationFor(annotationId: string) {
  return annotations.value.find(item => item.id === annotationId) ?? null
}

function selectAnnotationToLink(annotation: EvidenceAnnotation) {
  if (busy.value) return
  linkAnnotation.value = annotation
  linkCriterionId.value = boundRubric.value?.criteria[0]?.id ?? ''
  linkRationale.value = ''
  linkError.value = ''
  linkNotice.value = ''
}

function cancelLink() {
  if (busy.value) return
  linkAnnotation.value = null
  linkCriterionId.value = ''
  linkRationale.value = ''
  linkError.value = ''
}

async function saveLink() {
  if (busy.value) return
  const annotation = linkAnnotation.value
  if (!annotation) {
    linkError.value = '请先选择要关联的引用'
    return
  }
  if (!linkCriterionId.value) {
    linkError.value = '请选择审查要求'
    return
  }
  if (!linkRationale.value.trim()) {
    linkError.value = 'rationale 不能为空'
    return
  }
  savingLink.value = true
  linkError.value = ''
  linkNotice.value = ''
  try {
    const created = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/criterion-evidence-links`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          annotation_id: annotation.id,
          criterion_id: linkCriterionId.value,
          rationale: linkRationale.value,
        }),
      },
    )) as CriterionEvidenceLink
    links.value = [...links.value, created]
    // 成功路径直接清空（saving 仍为 true，不能走带 guard 的 cancelLink）。
    linkAnnotation.value = null
    linkCriterionId.value = ''
    linkRationale.value = ''
    linkNotice.value = '已建立关联'
  } catch (cause) {
    linkError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    savingLink.value = false
  }
}

async function deleteLink(link: CriterionEvidenceLink) {
  if (busy.value) return
  deletingLinkId.value = link.id
  linkError.value = ''
  linkNotice.value = ''
  try {
    const response = await fetch(
      `/api/v1/materials/${encodeURIComponent(materialId)}/criterion-evidence-links/${encodeURIComponent(link.id)}`,
      { method: 'DELETE' },
    )
    if (response.status !== 204) {
      const body = await response.json().catch(() => null)
      const code = body && body.code ? body.code : String(response.status)
      throw new Error(body && body.message ? `${body.message}（${code}）` : `HTTP ${response.status}`)
    }
    links.value = links.value.filter(item => item.id !== link.id)
    linkNotice.value = '已移除关联'
  } catch (cause) {
    linkError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    deletingLinkId.value = ''
  }
}

// —— Agent 提案操作（AI 预检 / 接受 / 拒绝） ——

async function loadProposals() {
  proposalsLoading.value = true
  proposalsError.value = ''
  try {
    proposals.value = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/agent-proposals`,
    )) as AgentProposal[]
  } catch (cause) {
    proposalsError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    proposalsLoading.value = false
  }
}

function latestProposalFor(criterionId: string) {
  return latestProposal(proposals.value, criterionId)
}

function completedProposalFor(criterionId: string) {
  return latestCompletedProposal(proposals.value, criterionId)
}

function criterionConfirmed(criterionId: string) {
  return confirmedCount(links.value, criterionId)
}

function criterionIdForCandidate(candidate: ProposalCandidate) {
  return proposals.value.find(item => item.id === candidate.proposal_id)?.criterion_id ?? ''
}

/** 与后端 duplicate_link 同一判定：该 criterion 下已有 block_id + quote 相同的关联。 */
function candidateLinkedFor(criterionId: string, candidate: ProposalCandidate) {
  if (!criterionId) return false
  return links.value.some((link) => {
    if (link.criterion_id !== criterionId) return false
    const annotation = annotationFor(link.annotation_id)
    return annotation !== null && annotation.block_id === candidate.block_id && annotation.source.quote === candidate.quote
  })
}

/** 可批量接受：验证门通过、未裁决、且没有已存在关联（已关联的跳过）。 */
function candidateAcceptable(criterionId: string, candidate: ProposalCandidate) {
  return (
    candidate.validation_status === 'passed' &&
    candidate.review_status === 'unreviewed' &&
    !candidateLinkedFor(criterionId, candidate)
  )
}

function acceptableCandidatesFor(criterionId: string) {
  const proposal = latestProposalFor(criterionId)
  if (!proposal || proposal.status !== 'completed') return []
  return proposal.candidates.filter(item => candidateAcceptable(criterionId, item))
}

function criterionPending(criterionId: string) {
  return acceptableCandidatesFor(criterionId).length
}

/** 每条的确认按钮文案：N = 未关联的 passed 候选数（已关联/无效/已裁决都不计）。 */
function confirmCandidatesLabel(criterionId: string) {
  return `确认这 ${acceptableCandidatesFor(criterionId).length} 条依据`
}

/** 列表只渲染待审核候选；被验证门挡下（或已裁决/已关联）的候选不出卡片，但机器码仍要如实交代。 */
function invalidCandidatesSummary(criterionId: string) {
  const proposal = latestProposalFor(criterionId)
  if (!proposal || proposal.status !== 'completed') return ''
  const invalid = proposal.candidates.filter((item) => item.validation_status === 'invalid')
  if (invalid.length === 0) return ''
  const codes = [...new Set(invalid.map((item) => item.validation_code).filter(Boolean))]
  return codes.length > 0
    ? `原文引用无效 ${invalid.length} 条：${codes.join('、')}（未列入待审核）`
    : `原文引用无效 ${invalid.length} 条（未列入待审核）`
}

function criterionEmptyPreflight(criterionId: string) {
  const completed = completedProposalFor(criterionId)
  return completed !== null && passedCount(completed) === 0
}

function preflightButtonLabel(criterionId: string) {
  // 已有 completed 提案时只展示历史，必须点「重新预检」才会再次 POST。
  return latestProposalFor(criterionId)?.status === 'completed' ? '重新依据审计' : '依据审计'
}

function preflightSeconds(criterionId: string) {
  const startedAt = preflightStartedAt.value[criterionId]
  if (!startedAt) return null
  return Math.max(1, Math.ceil((preflightNow.value - startedAt) / 1000))
}

function stopPreflightClock() {
  if (preflightClock !== null) {
    clearInterval(preflightClock)
    preflightClock = null
  }
}

function tickPreflightClock() {
  preflightNow.value = Date.now()
  if (proposingIds.value.length === 0) stopPreflightClock()
}

function ensurePreflightClock() {
  if (preflightClock !== null) return
  preflightNow.value = Date.now()
  preflightClock = setInterval(tickPreflightClock, 1000)
}

onUnmounted(stopPreflightClock)

function blockLocation(blockId: string) {
  const block = material.value?.blocks.find(item => item.id === blockId)
  return locatorLabel(block?.locator ?? null)
}

async function runPreflight(criterion: Rubric['criteria'][number]) {
  // 未绑定不允许；同一条已在预检中则忽略重复点击（不同 criterion 可并行）。
  if (!boundRubric.value || proposingIds.value.includes(criterion.id)) return
  proposingIds.value = [...proposingIds.value, criterion.id]
  preflightStartedAt.value = { ...preflightStartedAt.value, [criterion.id]: Date.now() }
  ensurePreflightClock()
  proposalError.value = ''
  proposalErrorDetail.value = ''
  proposalNotice.value = ''
  try {
    const proposal = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/agent-proposals`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ criterion_id: criterion.id }),
      },
    )) as AgentProposal
    proposals.value = [proposal, ...proposals.value.filter(item => item.id !== proposal.id)]
    if (proposal.status === 'completed') {
      if (proposal.candidates.length === 0) {
        proposalNotice.value = '依据审计完成：没有提出候选（空结果正常）'
      } else {
        const passed = proposal.candidates.filter(item => item.validation_status === 'passed').length
        const invalid = proposal.candidates.filter(item => item.validation_status === 'invalid').length
        proposalNotice.value = `依据审计完成：原文引用有效 ${passed} 条，无效 ${invalid} 条，待你判断是否关联`
      }
    } else {
      proposalError.value = `依据审计失败：${proposal.error ?? '未知错误'}`
    }
  } catch (cause) {
    const raw = cause instanceof Error ? cause.message : ''
    proposalErrorDetail.value = raw
    proposalError.value = humanizePreflightError(raw)
  } finally {
    proposingIds.value = proposingIds.value.filter(item => item !== criterion.id)
    const started = { ...preflightStartedAt.value }
    delete started[criterion.id]
    preflightStartedAt.value = started
    if (proposingIds.value.length === 0) stopPreflightClock()
  }
}

async function runPreflightAll() {
  if (!boundRubric.value) return
  const criteria = boundRubric.value.criteria
  const pending = criteria.filter(item => completedProposalFor(item.id) === null)
  // 全已预检时按钮文案已是「再预检全部」，意图明确，直接重跑，不做原生确认。
  const targets = (pending.length > 0 ? pending : [...criteria])
    .filter(item => !proposingIds.value.includes(item.id))
    .slice(0, 3)
  await Promise.all(targets.map(item => runPreflight(item)))
}

function preflightAllLabel() {
  const total = boundRubric.value?.criteria.length ?? 0
  if (proposingIds.value.length > 0) return `依据审计中 ${proposingIds.value.length}/${total}`
  const criteria = boundRubric.value?.criteria ?? []
  const allCompleted = criteria.length > 0 && criteria.every(item => completedProposalFor(item.id) !== null)
  return allCompleted ? '再依据审计全部' : '依据审计全部'
}

function humanizePreflightError(raw: string | null | undefined) {
  // 主句只说人话；机器码/原始报错放 title（调用方传入）。
  const text = (raw ?? '').trim()
  if (!text) return '依据审计失败，点「重新依据审计」再试。'
  if (text.includes('llm_invalid_response')) {
    return text.includes('空')
      ? '依据审计没有返回内容，点「重新依据审计」再试。'
      : '依据审计结果不完整，点「重新依据审计」再试。'
  }
  if (text.includes('llm_timeout')) return '依据审计超时，点「重新依据审计」再试。'
  if (text.includes('llm_unavailable')) return '依据审计服务暂时不可用，点「重新依据审计」再试。'
  if (text.includes('llm_unconfigured')) return '尚未配置 LLM，检查 backend/.env 后再试。'
  if (text.includes('material_too_large')) return '材料过大，依据审计未执行；请拆分材料后再试。'
  return text
}

function isDuplicateLinkError(raw: string) {
  return raw.includes('duplicate_link')
}

function humanizeAcceptFailure(raw: string) {
  if (raw.includes('candidate_not_found')) return '找不到该候选，未接受。'
  if (raw.includes('invalid_candidate')) return '候选原文校验不通过，未接受。'
  if (raw.includes('span_mismatch')) return '原文已变化，未接受该候选。'
  return raw
}

function batchAcceptNotice(accepted: number, skipped: number) {
  if (accepted === 0) {
    return skipped > 0 ? `${skipped} 条候选的原文已关联此审查要求，未重复建立关联` : '没有可接受的候选'
  }
  return `已接受 ${accepted} 条候选并物化为引用（AI 建议）${skipped > 0 ? `；${skipped} 条原文已关联，已跳过` : ''}`
}

async function acceptCandidate(candidate: ProposalCandidate) {
  if (busy.value) return
  if (candidate.validation_status !== 'passed') {
    proposalError.value = '原文引用无效的候选不能接受'
    return
  }
  const criterionId = criterionIdForCandidate(candidate)
  if (candidateLinkedFor(criterionId, candidate)) {
    // 已关联的候选不再发请求，主句也不是红字：它已经是人确认过的关联。
    proposalNotice.value = '该候选的原文已关联此审查要求'
    return
  }
  acceptingCandidateId.value = candidate.id
  proposalError.value = ''
  proposalNotice.value = ''
  try {
    const acceptance = (await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/proposal-candidates/${encodeURIComponent(candidate.id)}/accept`,
      { method: 'POST' },
    )) as ProposalAcceptance
    annotations.value = [...annotations.value, acceptance.annotation]
    links.value = [...links.value, acceptance.link]
    await loadProposals()
    proposalNotice.value = '已接受候选并物化为引用（AI 建议）'
  } catch (cause) {
    const raw = cause instanceof Error ? cause.message : '未知错误'
    if (isDuplicateLinkError(raw)) {
      // 客户端镜像滞后（别处已建过同一关联）：刷新关联让候选收敛到「已关联」，不写红字主句。
      await Promise.all([loadAnnotations(), loadLinks(), loadProposals()])
      proposalNotice.value = '该候选的原文已关联此审查要求'
    } else {
      proposalError.value = raw
    }
  } finally {
    acceptingCandidateId.value = ''
  }
}

/** 批量接受：逐条接受 passed+unreviewed（已关联的跳过），失败不中断其余候选。 */
async function acceptPassedFor(criterionId: string) {
  if (busy.value) return
  const targets = acceptableCandidatesFor(criterionId)
  if (targets.length === 0) return
  acceptingBatchCriterionId.value = criterionId
  proposalError.value = ''
  proposalErrorDetail.value = ''
  proposalNotice.value = ''
  let accepted = 0
  let skipped = 0
  let firstFailure = ''
  try {
    for (const candidate of targets) {
      try {
        const acceptance = (await requestJson(
          `/api/v1/materials/${encodeURIComponent(materialId)}/proposal-candidates/${encodeURIComponent(candidate.id)}/accept`,
          { method: 'POST' },
        )) as ProposalAcceptance
        annotations.value = [...annotations.value, acceptance.annotation]
        links.value = [...links.value, acceptance.link]
        accepted += 1
      } catch (cause) {
        const raw = cause instanceof Error ? cause.message : ''
        if (isDuplicateLinkError(raw)) {
          skipped += 1
        } else if (!firstFailure) {
          firstFailure = raw
        }
      }
    }
    if (skipped > 0) await loadLinks()
    await loadProposals()
    proposalNotice.value = batchAcceptNotice(accepted, skipped)
    if (firstFailure) proposalError.value = humanizeAcceptFailure(firstFailure)
  } finally {
    acceptingBatchCriterionId.value = ''
  }
}

function toggleEvidence() {
  evidenceOpen.value = !evidenceOpen.value
}

function toggleBlocks() {
  blocksOpen.value = !blocksOpen.value
}

function askReject(candidate: ProposalCandidate) {
  if (busy.value) return
  rejectFormId.value = candidate.id
  rejectReasonInput.value = ''
  proposalError.value = ''
}

function cancelReject() {
  if (busy.value) return
  rejectFormId.value = ''
  rejectReasonInput.value = ''
}

async function rejectCandidate(candidate: ProposalCandidate) {
  if (busy.value) return
  rejectingCandidateId.value = candidate.id
  proposalError.value = ''
  proposalNotice.value = ''
  try {
    await requestJson(
      `/api/v1/materials/${encodeURIComponent(materialId)}/proposal-candidates/${encodeURIComponent(candidate.id)}/reject`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: rejectReasonInput.value || null }),
      },
    )
    await loadProposals()
    rejectFormId.value = ''
    rejectReasonInput.value = ''
    proposalNotice.value = '已拒绝该候选'
  } catch (cause) {
    proposalError.value = cause instanceof Error ? cause.message : '未知错误'
  } finally {
    rejectingCandidateId.value = ''
  }
}

// —— 锚点导航：定位并短暂高亮；找不到时明确提示 ——

async function goToBlock(blockId: string) {
  if (!blockId) {
    anchorNotice.value = '该关联对应的 Block 已不存在'
    return
  }
  // 全文 Block 默认折叠：先展开再定位，否则「查看原文」点了没反应。
  blocksOpen.value = true
  await nextTick()
  const element = typeof document !== 'undefined' ? document.getElementById(`block-${blockId}`) : null
  if (!element) {
    anchorNotice.value = '找不到该引用对应的 Block（可能已被移除）'
    return
  }
  anchorNotice.value = ''
  highlightedBlockId.value = blockId
  element.scrollIntoView({ behavior: 'smooth', block: 'center' })
  setTimeout(() => {
    if (highlightedBlockId.value === blockId) highlightedBlockId.value = ''
  }, 1600)
}

const meta = computed(() => {
  const current = material.value
  if (!current) return ''
  const parts = [formatLabel(current.format), `${current.size_bytes} 字节`]
  // docx 无真实行号：line_count 为 null 时不显示。
  if (typeof current.line_count === 'number') parts.push(`${current.line_count} 行`)
  parts.push(`${current.blocks.length} 段原文`)
  parts.push(`sha256 ${current.sha256.slice(0, 12)}…`)
  return parts.join(' · ')
})

async function init() {
  await Promise.all([loadMaterial(), loadAnnotations(), loadRubrics(), loadBinding(), loadLinks(), loadProposals()])
  // 带 #block-* 打开/刷新：等材料与标注装载完成后再定位。
  if (route.hash.startsWith('#block-')) {
    goToBlock(route.hash.slice('#block-'.length))
  }
}

init()
</script>

<template>
  <main class="mx-auto max-w-6xl px-6 py-10">
    <!-- 加载/错误状态：保留简单页头，不把半成品渲染成材料页。 -->
    <template v-if="loading || notFound || error">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-sm font-medium text-violet-400">材料</p>
          <h1 class="mt-2 text-3xl font-semibold tracking-tight">{{ notFound ? '找不到该材料' : 'Material' }}</h1>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
          <UButton to="/materials" color="neutral" variant="subtle" icon="i-lucide-folder-open">全部材料</UButton>
        </div>
      </div>
      <UCard v-if="loading" class="mt-8">
        <p class="text-sm text-slate-400">正在读取材料…</p>
      </UCard>
      <UCard v-else-if="notFound" class="mt-8">
        <p class="text-sm text-slate-400">找不到这份材料，可能已被删除。</p>
        <UButton class="mt-6" to="/materials" icon="i-lucide-folder-open">返回全部材料</UButton>
      </UCard>
      <UCard v-else-if="error" class="mt-8">
        <h2 class="text-lg font-medium">无法加载材料</h2>
        <p class="mt-2 text-sm text-slate-400">请求失败：{{ error }}</p>
        <UButton class="mt-6" icon="i-lucide-refresh-cw" @click="loadMaterial">重试</UButton>
      </UCard>
    </template>

    <!-- 已保存材料：只读 artifact 页，无上传控件、无临时状态、无保存按钮。 -->
    <template v-else-if="material">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm text-slate-500">
          <RouterLink to="/materials" class="text-slate-400 hover:text-violet-300">材料</RouterLink>
          <span class="mx-1">/</span>
          <span class="text-slate-300">{{ material.filename }}</span>
        </p>
        <div class="flex flex-wrap items-center gap-3">
          <UButton
            :to="`/materials/${materialId}/report`"
            color="neutral"
            variant="subtle"
            icon="i-lucide-table"
          >
            查看审查结果
          </UButton>
          <UButton to="/" color="neutral" variant="subtle" icon="i-lucide-arrow-left">审查</UButton>
        </div>
      </div>

      <MaterialHeader
        class="mt-6"
        :filename="material.filename"
        :meta="meta"
        badge-label="已保存"
        badge-color="success"
      >
        <span class="text-sm text-slate-400">保存于 {{ formatSavedAt(material.created_at) }}</span>
      </MaterialHeader>

      <p v-if="anchorNotice" class="mt-3 text-sm text-amber-300" role="status">{{ anchorNotice }}</p>

      <!-- 评分标准：只读标准仓 + 材料绑定 + 人工关联列表。 -->
      <section class="mt-4 rounded-lg border border-slate-800">
        <div class="flex items-center justify-between border-b border-slate-800 px-3 py-2">
          <h2 class="text-sm font-medium text-slate-300">审查标准</h2>
          <div class="flex items-center gap-2">
            <UButton
              v-if="boundRubric"
              size="xs"
              color="neutral"
              variant="subtle"
              icon="i-lucide-sparkles"
              :disabled="!boundRubric"
              @click="runPreflightAll"
            >
              {{ preflightAllLabel() }}
            </UButton>
            <span class="text-xs text-slate-500">{{ binding ? '已绑定' : '尚未绑定' }}</span>
          </div>
        </div>

        <p v-if="bindingLoading || rubricsLoading || linksLoading" class="px-3 py-3 text-sm text-slate-400">
          正在读取审查标准与关联…
        </p>
        <p
          v-else-if="bindingError || rubricsError || linksError"
          class="px-3 py-3 text-sm text-red-400"
          role="alert"
        >
          {{ bindingError || rubricsError || linksError }}
        </p>

        <template v-else-if="binding">
          <div class="px-3 py-3">
            <p class="text-sm text-slate-200">
              {{ boundRubric ? boundRubric.title : '绑定的标准已不可用' }}
              <span class="text-xs text-slate-500">
                · 标准版本 {{ binding.rubric_revision }} · 来源：{{ boundRubric ? boundRubric.source_note : '标准文件不可用' }}
              </span>
            </p>
            <p v-if="!boundRubric" class="mt-2 text-xs text-red-400">绑定的审查标准版本已不可用</p>
            <div v-else class="mt-3 space-y-3">
              <div
                v-for="criterion in boundRubric.criteria"
                :key="criterion.id"
                class="rounded-md border border-slate-800 p-3"
              >
                <p class="text-sm font-medium text-slate-200">{{ criterion.title }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ criterion.requirement }}</p>
                <div class="mt-2 flex flex-wrap gap-2">
                  <UBadge
                    v-if="!completedProposalFor(criterion.id)"
                    color="neutral"
                    variant="subtle"
                    size="sm"
                  >
                    尚未运行依据审计
                  </UBadge>
                  <UBadge
                    v-if="criterionEmptyPreflight(criterion.id)"
                    color="neutral"
                    variant="subtle"
                    size="sm"
                  >
                    {{ criterionConfirmed(criterion.id) > 0 ? '本次未提出新候选' : '依据审计完成 · 当前材料尚未发现候选引用' }}
                  </UBadge>
                  <UBadge
                    v-if="criterionPending(criterion.id) > 0"
                    color="warning"
                    variant="subtle"
                    size="sm"
                  >
                    已发现 {{ criterionPending(criterion.id) }} 条候选，待审核
                  </UBadge>
                  <UBadge
                    v-if="criterionConfirmed(criterion.id) > 0"
                    color="success"
                    variant="subtle"
                    size="sm"
                  >
                    已确认关联 {{ criterionConfirmed(criterion.id) }} 条
                  </UBadge>
                </div>
                <p
                  v-if="criterionEmptyPreflight(criterion.id) && material"
                  class="mt-1 text-xs text-slate-500"
                >
                  范围：{{ material.filename }} · {{ material.blocks.length }} 段原文
                </p>
                <div class="mt-2 space-y-2">
                  <div v-for="link in linksFor(criterion.id)" :key="link.id" class="rounded-md bg-slate-900/60 p-2">
                    <p class="font-mono text-xs text-slate-300">
                      “{{ annotationFor(link.annotation_id)?.source.quote ?? '（引用已删除）' }}”
                    </p>
                    <p class="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span>用途：{{ link.rationale }}</span>
                      <UBadge :color="link.proposed_by === 'agent' ? 'info' : 'neutral'" variant="subtle" size="sm">
                        {{ link.proposed_by === 'human' ? '人工' : 'AI 建议' }}
                      </UBadge>
                    </p>
                    <div class="mt-2 flex flex-wrap items-center gap-2">
                      <UButton
                        size="xs"
                        color="neutral"
                        variant="ghost"
                        icon="i-lucide-crosshair"
                        @click="goToBlock(annotationFor(link.annotation_id)?.block_id ?? '')"
                      >
                        查看原文
                      </UButton>
                      <UButton
                        size="xs"
                        color="neutral"
                        variant="ghost"
                        icon="i-lucide-unlink"
                        :loading="deletingLinkId === link.id"
                        :disabled="busy"
                        @click="deleteLink(link)"
                      >
                        移除关联
                      </UButton>
                    </div>
                  </div>
                  <p
                    v-if="criterionConfirmed(criterion.id) === 0 && !completedProposalFor(criterion.id)"
                    class="text-xs text-slate-500"
                  >
                    尚未关联引用
                  </p>
                </div>

                <!-- AI 预检：只产生候选；接受/拒绝由人裁决。 -->
                <div class="mt-3 border-t border-slate-800 pt-3">
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <p class="text-xs text-slate-500">
                      最新依据审计：{{ latestProposalFor(criterion.id) ? latestProposalFor(criterion.id)!.status : '尚未运行' }}
                    </p>
                    <UButton
                      size="xs"
                      color="neutral"
                      variant="subtle"
                      icon="i-lucide-sparkles"
                      :loading="proposingIds.includes(criterion.id)"
                      :disabled="!boundRubric"
                      @click="runPreflight(criterion)"
                    >
                      {{ proposingIds.includes(criterion.id) ? `依据审计中… ${preflightSeconds(criterion.id)}s` : preflightButtonLabel(criterion.id) }}
                    </UButton>
                  </div>
                  <template v-if="latestProposalFor(criterion.id)">
                    <p
                      v-if="latestProposalFor(criterion.id)!.status === 'failed'"
                      class="mt-2 text-xs text-red-400"
                      :title="latestProposalFor(criterion.id)!.error ?? undefined"
                    >
                      上次依据审计失败：{{ humanizePreflightError(latestProposalFor(criterion.id)!.error) }}
                    </p>
                    <div v-else class="mt-2 space-y-2">
                      <div class="flex flex-wrap items-center justify-between gap-2">
                        <p class="text-xs text-slate-500">
                          AI 提议可能相关，需你判断；「原文引用有效」只表示这句话在材料里。
                        </p>
                        <UButton
                          v-if="acceptableCandidatesFor(criterion.id).length > 0"
                          size="sm"
                          color="primary"
                          icon="i-lucide-check-check"
                          :loading="acceptingBatchCriterionId === criterion.id"
                          :disabled="busy && acceptingBatchCriterionId !== criterion.id"
                          @click="acceptPassedFor(criterion.id)"
                        >
                          {{ confirmCandidatesLabel(criterion.id) }}
                        </UButton>
                      </div>
                      <p v-if="invalidCandidatesSummary(criterion.id)" class="text-xs text-slate-500">
                        {{ invalidCandidatesSummary(criterion.id) }}
                      </p>
                      <ul class="space-y-2">
                      <li
                        v-for="candidate in acceptableCandidatesFor(criterion.id)"
                        :key="candidate.id"
                        class="rounded-md border border-slate-800 p-2"
                      >
                        <p class="font-mono text-xs text-slate-300">
                          “{{ candidate.quote }}” · {{ blockLocation(candidate.block_id) }}
                        </p>
                        <p class="mt-1 text-xs text-slate-500">
                          {{ candidate.rationale }}
                          <span v-if="candidate.risk_note"> · 风险：{{ candidate.risk_note }}</span>
                        </p>
                        <div class="mt-1 flex flex-wrap items-center gap-2">
                          <UBadge color="success" variant="subtle" size="sm">原文引用有效</UBadge>
                        </div>
                        <div class="mt-2 flex flex-wrap items-center gap-2">
                          <UButton
                            size="xs"
                            color="neutral"
                            variant="ghost"
                            :loading="acceptingCandidateId === candidate.id"
                            :disabled="busy"
                            @click="acceptCandidate(candidate)"
                          >
                            接受
                          </UButton>
                          <template v-if="rejectFormId === candidate.id">
                            <input
                              v-model="rejectReasonInput"
                              placeholder="拒绝原因（可选）"
                              class="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
                            />
                            <UButton
                              size="xs"
                              color="neutral"
                              variant="subtle"
                              :loading="rejectingCandidateId === candidate.id"
                              @click="rejectCandidate(candidate)"
                            >
                              确认拒绝
                            </UButton>
                            <UButton size="xs" color="neutral" variant="ghost" :disabled="busy" @click="cancelReject">
                              取消
                            </UButton>
                          </template>
                          <UButton
                            v-else
                            size="xs"
                            color="neutral"
                            variant="ghost"
                            :disabled="busy"
                            @click="askReject(candidate)"
                          >
                            拒绝
                          </UButton>
                        </div>
                      </li>
                      </ul>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </template>

        <template v-else>
          <p v-if="rubrics.length === 0" class="px-3 py-3 text-sm text-slate-500">尚未配置审查标准</p>
          <ul v-else class="divide-y divide-slate-800">
            <li
              v-for="rubric in rubrics"
              :key="`${rubric.id}:${rubric.revision}`"
              class="flex items-center justify-between gap-3 px-3 py-2"
            >
              <div class="min-w-0">
                <p class="truncate text-sm text-slate-200">{{ rubric.title }}</p>
                <p class="mt-0.5 truncate text-xs text-slate-500">
                  {{ rubric.source_note }} · 标准版本 {{ rubric.revision }} · {{ rubric.criteria.length }} 项
                </p>
              </div>
              <UButton size="sm" :loading="bindingBusy" :disabled="busy" @click="bindRubric(rubric)">绑定</UButton>
            </li>
          </ul>
        </template>

        <p v-if="bindingNotice" class="border-t border-slate-800 px-3 py-2 text-xs text-emerald-400">
          {{ bindingNotice }}
        </p>
        <p v-if="linkNotice" class="border-t border-slate-800 px-3 py-2 text-xs text-emerald-400">{{ linkNotice }}</p>
        <p
          v-if="proposalError"
          class="border-t border-slate-800 px-3 py-2 text-xs text-red-400"
          role="alert"
          :title="proposalErrorDetail || undefined"
        >
          {{ proposalError }}
        </p>
        <p v-if="proposalNotice" class="border-t border-slate-800 px-3 py-2 text-xs text-emerald-400">
          {{ proposalNotice }}
        </p>
      </section>

      <!-- 证据区：默认折叠；标题可展开。标注列表 + 反馈；表单在选中的 Block 行内展开。 -->
      <section class="mt-4 rounded-lg border border-slate-800">
        <button
          type="button"
          class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
          :aria-expanded="evidenceOpen"
          @click="toggleEvidence"
        >
          <span class="text-sm font-medium text-slate-300">证据</span>
          <span class="flex items-center gap-2 text-xs text-slate-500">
            {{ annotations.length }} 条标注
            <UIcon :name="evidenceOpen ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'" />
          </span>
        </button>
        <div v-if="evidenceOpen" class="border-t border-slate-800">
          <p v-if="annotationsLoading" class="px-3 py-3 text-sm text-slate-400">正在读取证据标注…</p>
          <p v-else-if="annotationsError" class="px-3 py-3 text-sm text-red-400" role="alert">{{ annotationsError }}</p>
          <template v-else>
          <p v-if="annotations.length === 0" class="px-3 py-3 text-sm text-slate-500">
            还没有已保存的引用。依据审计点「接受」会出现在这里；也可在原文段落行手动圈一句。
          </p>
          <ul v-else class="divide-y divide-slate-800">
            <li v-for="item in annotations" :key="item.id" class="px-3 py-2">
              <p class="font-mono text-sm text-slate-200">“{{ item.source.quote }}”</p>
              <p class="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>{{ blockLocation(item.block_id) }}</span>
                <UBadge :color="item.proposed_by === 'agent' ? 'info' : 'neutral'" variant="subtle" size="sm">
                  {{ item.proposed_by === 'human' ? '人工' : 'AI 建议' }}
                </UBadge>
                <span v-if="item.note">{{ item.note }}</span>
              </p>
              <div class="mt-2 flex flex-wrap items-center gap-2">
                <UButton
                  size="xs"
                  color="neutral"
                  variant="ghost"
                  icon="i-lucide-link"
                  :disabled="busy || !binding"
                  :title="binding ? undefined : '绑定审查标准后可关联'"
                  @click="selectAnnotationToLink(item)"
                >
                  关联
                </UButton>
                <template v-if="confirmDeleteId === item.id">
                  <span class="text-xs text-red-300">确认删除该标注？其关联会一起清除</span>
                  <UButton
                    size="xs"
                    color="error"
                    variant="subtle"
                    :loading="deletingAnnotationId === item.id"
                    @click="deleteAnnotation(item)"
                  >
                    确认删除
                  </UButton>
                  <UButton size="xs" color="neutral" variant="ghost" :disabled="busy" @click="cancelDeleteAnnotation">
                    取消
                  </UButton>
                </template>
                <UButton
                  v-else
                  size="xs"
                  color="neutral"
                  variant="ghost"
                  icon="i-lucide-trash-2"
                  :disabled="busy"
                  @click="askDeleteAnnotation(item)"
                >
                  删除
                </UButton>
              </div>
              <div
                v-if="linkAnnotation && linkAnnotation.id === item.id"
                class="mt-2 rounded-md border border-slate-800 bg-slate-950/60 p-3"
              >
                <p class="text-xs text-slate-500">
                  关联到审查要求（{{ boundRubric ? boundRubric.title : '尚未绑定审查标准' }}）
                </p>
                <select
                  v-model="linkCriterionId"
                  class="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200"
                >
                  <option disabled value="">选择审查要求</option>
                  <option v-for="criterion in boundRubric?.criteria ?? []" :key="criterion.id" :value="criterion.id">
                    {{ criterion.title }}
                  </option>
                </select>
                <textarea
                  v-model="linkRationale"
                  rows="2"
                  placeholder="rationale（必填：为什么这条引用与该项相关）"
                  class="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200"
                ></textarea>
                <div class="mt-2 flex items-center gap-2">
                  <UButton
                    size="sm"
                    :loading="savingLink"
                    :disabled="savingLink || !boundRubric"
                    @click="saveLink"
                  >
                    {{ savingLink ? '正在保存…' : '建立关联' }}
                  </UButton>
                  <UButton size="sm" color="neutral" variant="ghost" :disabled="savingLink" @click="cancelLink">
                    取消
                  </UButton>
                </div>
                <p v-if="linkError" class="mt-2 text-xs text-red-400" role="alert">{{ linkError }}</p>
              </div>
            </li>
          </ul>
        </template>
        <p v-if="deleteAnnotationError" class="border-t border-slate-800 px-3 py-2 text-xs text-red-400" role="alert">
          {{ deleteAnnotationError }}
        </p>
        <p v-if="annotationNotice" class="border-t border-slate-800 px-3 py-2 text-xs text-emerald-400">
          {{ annotationNotice }}
        </p>
        </div>
      </section>

      <!-- 全文 Block：默认折叠；标题可展开。标注/圈句都在 Block 行内。 -->
      <section class="mt-4 rounded-lg border border-slate-800">
        <button
          type="button"
          class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
          :aria-expanded="blocksOpen"
          @click="toggleBlocks"
        >
          <span class="text-sm font-medium text-slate-300">原文段落列表</span>
          <span class="flex items-center gap-2 text-xs text-slate-500">
            共 {{ material.blocks.length }} 个
            <UIcon :name="blocksOpen ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'" />
          </span>
        </button>
        <div v-if="blocksOpen" class="border-t border-slate-800 p-3">
          <BlockList
            :blocks="material.blocks"
            :annotated-counts="annotatedCounts"
            :highlight-block-id="highlightedBlockId"
          >
            <template #cite="{ block }">
              <UButton
                v-if="!selectedBlock || selectedBlock.id !== block.id"
                class="ml-auto shrink-0"
                size="xs"
                color="neutral"
                variant="ghost"
                icon="i-lucide-quote"
                :disabled="busy"
                title="依据审计未找到时，可手动圈一句原文再关联。平时请用上面的接受。"
                @click="selectBlock(block)"
              >
                标注
              </UButton>
              <div v-else class="w-full rounded-md border border-slate-800 bg-slate-950/60 p-3">
                <p class="text-xs text-slate-500">引用 {{ locatorLabel(block.locator) }} · quote 必须是原文子串，可改窄</p>
                <input
                  v-model="quoteInput"
                  class="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-sm text-slate-200"
                />
                <textarea
                  v-model="noteInput"
                  rows="2"
                  placeholder="note（可选）"
                  class="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-200"
                ></textarea>
                <div class="mt-2 flex items-center gap-2">
                  <UButton size="sm" :loading="savingAnnotation" :disabled="savingAnnotation" @click="saveAnnotation">
                    {{ savingAnnotation ? '正在保存…' : '保存标注' }}
                  </UButton>
                  <UButton size="sm" color="neutral" variant="ghost" :disabled="savingAnnotation" @click="cancelSelection">
                    取消
                  </UButton>
                </div>
                <p v-if="annotationError" class="mt-2 text-xs text-red-400" role="alert">{{ annotationError }}</p>
              </div>
            </template>
          </BlockList>
        </div>
      </section>
    </template>
  </main>
</template>
