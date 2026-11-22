import { apiClient } from './client.js'

let dashboardCache = null

export function getCachedDashboard() {
  return dashboardCache
}

export function clearDashboardCache() {
  dashboardCache = null
}

export async function fetchDashboard({ signal } = {}) {
  const { data } = await apiClient.get('/dashboard/', { signal })
  const payload = data && data.data ? data.data : data

  dashboardCache = {
    active_projects: Array.isArray(payload.active_projects)
      ? payload.active_projects
      : null,
    overview: {
      total_projects: payload.overview?.total_projects ?? null,
      total_documents: payload.overview?.total_documents ?? null,
      documents_with_chunks: payload.overview?.documents_with_chunks ?? null,
      total_chunks: payload.overview?.total_chunks ?? null,
      total_embeddings: payload.overview?.total_embeddings ?? null,
      document_chunk_coverage:
        payload.overview?.document_chunk_coverage ?? null,
      embedding_coverage: payload.overview?.embedding_coverage ?? null,
    },
    test_generation: {
      coverage_uplift: payload.test_generation?.coverage_uplift ?? null,
      flake_reduction: payload.test_generation?.flake_reduction ?? null,
      time_saved_minutes: payload.test_generation?.time_saved_minutes ?? null,
    },
    test_generation_metrics: normalizeTestGenerationMetrics(
      payload.test_generation_metrics,
    ),
    assistant: {
      suggestions: Array.isArray(payload.assistant?.suggestions)
        ? payload.assistant.suggestions
        : [],
    },
    knowledge_history: Array.isArray(payload.knowledge_history)
      ? payload.knowledge_history.map((entry) => ({
          date: entry.date,
          documents: entry.documents,
          chunks: entry.chunks,
          embeddings: entry.embeddings,
        }))
      : null,
  }
  return dashboardCache
}

function normalizeTestGenerationMetrics(metrics) {
  const normalizeScope = (scope) => scope && typeof scope === 'object'
    ? {
        explicit_requirements: scope.explicit_requirements ?? null,
        linked_explicit_requirements: scope.linked_explicit_requirements ?? null,
        requirement_case_coverage_percent:
          scope.requirement_case_coverage_percent ?? null,
        persisted_ai_generated_test_cases:
          scope.persisted_ai_generated_test_cases ?? null,
        generation_runs_with_saved_cases:
          scope.generation_runs_with_saved_cases ?? null,
      }
    : null

  const byProject = {}
  if (metrics?.by_project && typeof metrics.by_project === 'object') {
    for (const [projectId, values] of Object.entries(metrics.by_project)) {
      byProject[projectId] = normalizeScope(values)
    }
  }

  return {
    workspace: normalizeScope(metrics?.workspace),
    by_project: byProject,
  }
}

export async function fetchDashboardInsights() {
  const { data } = await apiClient.get('/dashboard/insights')
  const payload = data && data.data ? data.data : data

  return {
    summary: payload.summary ?? null,
    issues: Array.isArray(payload.issues) ? payload.issues : [],
    recommendations: Array.isArray(payload.recommendations)
      ? payload.recommendations
      : [],
  }
}
