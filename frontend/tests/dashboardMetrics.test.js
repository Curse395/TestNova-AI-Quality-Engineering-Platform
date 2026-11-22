import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import {
  selectTestGenerationMetrics,
  testGenerationMetricRows,
} from '../src/pages/dashboardMetrics.js'

test('test generation metric selection supports workspace and selected project scopes', () => {
  const source = {
    workspace: { persisted_ai_generated_test_cases: 10 },
    by_project: { '2': { persisted_ai_generated_test_cases: 4 } },
  }
  assert.deepEqual(selectTestGenerationMetrics(source, 'workspace', '2'), {
    metrics: source.workspace,
    scopeLabel: 'Workspace',
  })
  assert.deepEqual(selectTestGenerationMetrics(source, 'project', '2'), {
    metrics: source.by_project['2'],
    scopeLabel: 'Selected project',
  })
  assert.equal(selectTestGenerationMetrics(source, 'project', '99').metrics, null)
})

test('test generation card presents current traceability and persisted generation counts with definitions', () => {
  const rows = testGenerationMetricRows({
    explicit_requirements: 12,
    linked_explicit_requirements: 9,
    requirement_case_coverage_percent: 75,
    persisted_ai_generated_test_cases: 106,
    generation_runs_with_saved_cases: 18,
  })
  assert.deepEqual(rows.map(({ label, value }) => ({ label, value })), [
    { label: 'Current requirement case coverage', value: '75%' },
    { label: 'Persisted AI-generated test cases', value: '106' },
    { label: 'Generation workflows with saved cases', value: '18' },
  ])
  assert.match(rows[0].detail, /9 of 12/)
  assert.match(rows[0].detail, /not coverage uplift/)
  assert.match(rows[1].detail, /does not imply execution or passing/)
  assert.match(rows[2].detail, /retries within one workflow count once/)
})

test('empty persisted metrics display measured zero counts and unavailable coverage without a denominator', () => {
  const rows = testGenerationMetricRows({
    explicit_requirements: 0,
    linked_explicit_requirements: 0,
    requirement_case_coverage_percent: null,
    persisted_ai_generated_test_cases: 0,
    generation_runs_with_saved_cases: 0,
  })
  assert.deepEqual(rows.map(({ value }) => value), ['Unavailable', '0', '0'])
  assert.match(rows[0].detail, /No explicit requirements/)
  assert.deepEqual(testGenerationMetricRows(null).map(({ value }) => value), [
    'Unavailable', 'Unavailable', 'Unavailable',
  ])
})

test('Overview dashboard renders measured metrics and explanations instead of unsupported uplift claims', () => {
  const page = readFileSync(new URL('../src/pages/DashboardPage.jsx', import.meta.url), 'utf8')
  const metricPresentation = readFileSync(new URL('../src/pages/dashboardMetrics.js', import.meta.url), 'utf8')
  assert.match(metricPresentation, /Current requirement case coverage/)
  assert.match(metricPresentation, /Persisted AI-generated test cases/)
  assert.match(metricPresentation, /Generation workflows with saved cases/)
  assert.match(page, /Workspace/)
  assert.match(page, /Selected project/)
  assert.match(page, /generationMetricRows\.map/)
  assert.doesNotMatch(page + metricPresentation, /Coverage uplift|Flake reduction|Time saved/)
})
