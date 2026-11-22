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

export function testCaseHealthDistribution(counts, dimension) {
  const keys = dimension === 'category'
    ? ['positive', 'negative', 'boundary', 'edge']
    : dimension === 'priority'
      ? ['low', 'medium', 'high', 'critical']
      : null
  if (!keys || !counts || typeof counts !== 'object' || Array.isArray(counts)) {
    return undefined
  }
  return Object.fromEntries(keys.map((key) => [
    key,
    Number.isFinite(counts[key]) && counts[key] >= 0 ? counts[key] : null,
  ]))
}

export function qualityContextResult(result) {
  if (
    result?.status === 'available'
    && result.summary
    && typeof result.summary === 'object'
    && !Array.isArray(result.summary)
  ) {
    return { result, error: '' }
  }
  return {
    result: result && typeof result === 'object' && !Array.isArray(result) ? result : null,
    error: typeof result?.error === 'string' && result.error.trim()
      ? result.error
      : 'An evidence-validated AI summary is unavailable.',
  }
}

export function riskSeverityDisplay(counts = {}) {
  const hasCounts = counts && typeof counts === 'object' && !Array.isArray(counts)
  const supported = Object.fromEntries(
    ['critical', 'high', 'medium', 'low'].map((severity) => [
      severity[0].toUpperCase() + severity.slice(1),
      hasCounts && Number.isFinite(counts[severity]) && counts[severity] >= 0
        ? counts[severity]
        : null,
    ]),
  )
  const supportedKeys = new Set(['critical', 'high', 'medium', 'low'])
  const additional = Object.entries(hasCounts ? counts : {}).filter(([severity, count]) => (
    !supportedKeys.has(severity.toLowerCase())
    && Number.isFinite(count)
    && count > 0
  ))
  return { supported, additional }
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
