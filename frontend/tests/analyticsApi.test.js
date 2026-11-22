import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import { apiClient } from '../src/api/client.js'
import { fetchProjectAnalytics } from '../src/api/projects.js'
import { fetchDashboard } from '../src/api/dashboard.js'

test('project analytics fetch omits execution summary and trend endpoints', async () => {
  const get = mock.method(apiClient, 'get', async (url) => ({ data: { url } }))

  try {
    const result = await fetchProjectAnalytics(12)
    const requestedUrls = get.mock.calls.map(({ arguments: args }) => args[0])

    assert.deepEqual(requestedUrls, [
      '/analytics/overview/12',
      '/analytics/documents/12',
      '/analytics/test-cases/12',
      '/analytics/coverage/12',
      '/analytics/risks/12',
      '/analytics/workflows/12',
    ])
    assert.equal('executions' in result, false)
    assert.equal('executionTrends' in result, false)
  } finally {
    mock.restoreAll()
  }
})

test('dashboard API retains legacy metrics and normalizes measured generation metrics by scope', async () => {
  mock.method(apiClient, 'get', async (url) => ({
    data: url === '/dashboard/' ? {
      active_projects: [{ id: 2, name: 'MediTrack' }],
      overview: {},
      test_generation: {
        coverage_uplift: null,
        flake_reduction: null,
        time_saved_minutes: null,
      },
      test_generation_metrics: {
        workspace: {
          explicit_requirements: 12,
          linked_explicit_requirements: 9,
          requirement_case_coverage_percent: 75,
          persisted_ai_generated_test_cases: 106,
          generation_runs_with_saved_cases: 18,
        },
        by_project: {
          2: {
            explicit_requirements: 4,
            linked_explicit_requirements: 3,
            requirement_case_coverage_percent: 75,
            persisted_ai_generated_test_cases: 40,
            generation_runs_with_saved_cases: 6,
          },
        },
      },
    } : {},
  }))

  try {
    const result = await fetchDashboard()
    assert.equal(result.test_generation.coverage_uplift, null)
    assert.equal(result.test_generation_metrics.workspace.persisted_ai_generated_test_cases, 106)
    assert.equal(result.test_generation_metrics.by_project['2'].generation_runs_with_saved_cases, 6)
  } finally {
    mock.restoreAll()
  }
})
