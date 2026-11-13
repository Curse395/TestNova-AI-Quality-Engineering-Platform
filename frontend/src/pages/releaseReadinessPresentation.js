export const RELEASE_STATES = {
  ready_for_review: 'Ready for review',
  attention_required: 'Attention required',
  blocked: 'Blocked',
  insufficient_evidence: 'Insufficient evidence',
}

const ATTENTION_ORDER = {
  blocker: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
}

export function formatAvailableMetric(value) {
  return value == null ? 'Unavailable' : String(value)
}

export function formatExecutionStatus(status) {
  if (status == null) return 'Missing'
  if (typeof status !== 'string') return String(status)
  return status.trim() || 'Blank'
}

export function sortReleaseConcerns(concerns = []) {
  return concerns
    .map((concern, index) => ({ concern, index }))
    .sort((left, right) => (
      (ATTENTION_ORDER[left.concern.attention] ?? ATTENTION_ORDER.info)
      - (ATTENTION_ORDER[right.concern.attention] ?? ATTENTION_ORDER.info)
      || left.index - right.index
    ))
    .map(({ concern }) => concern)
}
