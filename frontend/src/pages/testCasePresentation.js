const REVIEW_STATUS_LABELS = {
  draft: 'Draft',
  approved: 'Approved',
  rejected: 'Rejected',
  other: 'Other',
  missing: 'Missing',
  blank: 'Blank',
}

const TEST_CASE_DISTRIBUTIONS = {
  category: [
    ['positive', 'Positive'],
    ['negative', 'Negative'],
    ['boundary', 'Boundary'],
    ['edge', 'Edge'],
    ['other', 'Other'],
  ],
  priority: [
    ['low', 'Low'],
    ['medium', 'Medium'],
    ['high', 'High'],
    ['critical', 'Critical'],
  ],
  reviewStatus: [
    ['draft', 'Draft'],
    ['approved', 'Approved'],
    ['rejected', 'Rejected'],
  ],
}

function validCounts(counts) {
  if (!counts || typeof counts !== 'object' || Array.isArray(counts)) return []
  return Object.entries(counts).filter(([, value]) => (
    typeof value === 'number' && Number.isFinite(value) && value > 0
  ))
}

function orderedDistribution(counts, distribution) {
  const normalizedCounts = new Map()
  for (const [rawName, count] of validCounts(counts)) {
    const name = rawName.trim().toLowerCase()
    if (!name || name === 'missing' || name === 'blank' || name === 'null' || name === 'undefined') continue
    normalizedCounts.set(name, (normalizedCounts.get(name) || 0) + count)
  }

  return distribution.flatMap(([key, name]) => {
    const value = normalizedCounts.get(key) || 0
    return value > 0 ? [{ name, value }] : []
  })
}

export function testCaseDistributionData(counts, kind) {
  const distribution = TEST_CASE_DISTRIBUTIONS[kind]
  return distribution ? orderedDistribution(counts, distribution) : []
}

export function reviewStatusLabel(status) {
  if (typeof status !== 'string' || !status.trim()) return 'Status unavailable'
  const normalized = status.trim().toLowerCase()
  return REVIEW_STATUS_LABELS[normalized] || `Other (${status.trim()})`
}

export function reviewStatusDistributionData(counts) {
  const rows = orderedDistribution(counts, TEST_CASE_DISTRIBUTIONS.reviewStatus)
  const total = validCounts(counts).reduce((sum, [, count]) => sum + count, 0)
  return rows.map((row) => ({
    ...row,
    percentage: total ? Math.round((row.value / total) * 1000) / 10 : 0,
  }))
}
