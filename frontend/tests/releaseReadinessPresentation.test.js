import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  formatAvailableMetric,
  qualityContextResult,
  riskSeverityDisplay,
  RELEASE_STATES,
  sortReleaseConcerns,
  testCaseHealthDistribution,
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

test('Test-case health distributions retain only supported categories and priorities with their existing counts', () => {
  assert.deepEqual(testCaseHealthDistribution({
    positive: 8,
    negative: 4,
    boundary: 3,
    edge: 1,
    other: 9,
    missing: 2,
    blank: 5,
  }, 'category'), {
    positive: 8,
    negative: 4,
    boundary: 3,
    edge: 1,
  })
  assert.deepEqual(testCaseHealthDistribution({
    low: 2,
    medium: 5,
    high: 7,
    critical: 1,
    other: 8,
    missing: 4,
    blank: 3,
  }, 'priority'), {
    low: 2,
    medium: 5,
    high: 7,
    critical: 1,
  })
  assert.deepEqual(testCaseHealthDistribution({ positive: 0, negative: 0, boundary: 0, edge: 0, other: 4 }, 'category'), {
    positive: 0,
    negative: 0,
    boundary: 0,
    edge: 0,
  })
  assert.equal(testCaseHealthDistribution(undefined, 'category'), undefined)
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

test('risk severity display keeps supported levels and safely separates unclassified counts', () => {
  assert.deepEqual(riskSeverityDisplay({
    critical: 1,
    high: 2,
    medium: 3,
    low: 4,
    unclassified: 0,
  }), {
    supported: { Critical: 1, High: 2, Medium: 3, Low: 4 },
    additional: [],
  })
  assert.deepEqual(riskSeverityDisplay({ high: 1, unclassified: 2, custom: 1 }).additional, [
    ['unclassified', 2],
    ['custom', 1],
  ])
  assert.deepEqual(riskSeverityDisplay(null).supported, {
    Critical: null,
    High: null,
    Medium: null,
    Low: null,
  })
})

test('quality context accepts the structured success contract and keeps unavailable responses safe', () => {
  const successful = {
    status: 'available',
    summary: { overall_summary: { statement: 'Persisted evidence supports this summary.' } },
  }
  assert.deepEqual(qualityContextResult(successful), { result: successful, error: '' })

  assert.deepEqual(qualityContextResult({
    status: 'unavailable',
    error: 'Quality summary is temporarily unavailable.',
  }), {
    result: { status: 'unavailable', error: 'Quality summary is temporarily unavailable.' },
    error: 'Quality summary is temporarily unavailable.',
  })
  assert.equal(qualityContextResult({ status: 'unavailable' }).error, 'An evidence-validated AI summary is unavailable.')
  assert.equal(qualityContextResult({ status: 'available', summary: null }).error, 'An evidence-validated AI summary is unavailable.')
  assert.equal(qualityContextResult({ status: 'available', summary: 'malformed' }).error, 'An evidence-validated AI summary is unavailable.')
})

test('release readiness disclosures are independently collapsed and workflow snapshots stay off this page', () => {
  const page = readFileSync(new URL('../src/pages/ReleaseReadinessPage.jsx', import.meta.url), 'utf8')
  const disclosures = [...page.matchAll(/<details\b([^>]*)>/g)]
  assert.equal(disclosures.length, 3)
  assert.ok(disclosures.every(([, attributes]) => !/\bopen\b|\bname\s*=/.test(attributes)))
  assert.match(page, /<summary[^>]*>[\s\S]*?concern\.title[\s\S]*?concern\.attention/)
  assert.match(page, /concern\.explanation[\s\S]*?concern\.source[\s\S]*?concern\.evidence_ids[\s\S]*?concern\.next_action/)
  assert.match(page, /\['pending', 'running', 'completed', 'partially_completed', 'failed', 'other'\]/)
  assert.doesNotMatch(page, /workflows\.workflows\.map/)
  assert.match(page, /Findings by assessed severity[\s\S]*?Findings by category/)
  assert.match(page, /Individual risk findings \(/)
  assert.match(page, /Findings by category[\s\S]*?<details className="group mt-4 border-t border-slate-800 pt-3">[\s\S]*?group-open:hidden[\s\S]*?group-open:inline/)
  assert.match(page, /risk\.description[\s\S]*?risk\.explanation[\s\S]*?risk\.evidence_references/)
  assert.doesNotMatch(page, /<Card title="Execution health"|Execution runs by day|Pass rate by day/)
})
