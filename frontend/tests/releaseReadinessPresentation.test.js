import test from 'node:test'
import assert from 'node:assert/strict'
import {
  formatAvailableMetric,
  formatExecutionStatus,
  RELEASE_STATES,
  sortReleaseConcerns,
} from '../src/pages/releaseReadinessPresentation.js'

test('release assessment states use explicit non-production labels', () => {
  assert.deepEqual(RELEASE_STATES, {
    ready_for_review: 'Ready for review',
    attention_required: 'Attention required',
    blocked: 'Blocked',
    insufficient_evidence: 'Insufficient evidence',
  })
  assert.equal(RELEASE_STATES.ready_for_review.includes('production'), false)
})

test('unavailable values remain distinct from measured zero', () => {
  assert.equal(formatAvailableMetric(null), 'Unavailable')
  assert.equal(formatAvailableMetric(undefined), 'Unavailable')
  assert.equal(formatAvailableMetric(0), '0')
})

test('missing, blank, and recognized execution statuses remain distinguishable', () => {
  assert.equal(formatExecutionStatus(null), 'Missing')
  assert.equal(formatExecutionStatus('  '), 'Blank')
  assert.equal(formatExecutionStatus(' passed '), 'passed')
})

test('outstanding concerns are ordered by severity without dropping evidence', () => {
  const concerns = [
    { id: 'low', attention: 'low', evidence_ids: [] },
    { id: 'blocker', attention: 'blocker', evidence_ids: ['run:1'] },
    { id: 'high', attention: 'high', evidence_ids: ['risk:1'] },
    { id: 'medium', attention: 'medium', evidence_ids: [] },
  ]

  assert.deepEqual(
    sortReleaseConcerns(concerns).map(({ id }) => id),
    ['blocker', 'high', 'medium', 'low'],
  )
  assert.deepEqual(sortReleaseConcerns(concerns)[0].evidence_ids, ['run:1'])
})
