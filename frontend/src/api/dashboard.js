import { apiClient } from './client'

export async function fetchDashboard() {
  const { data } = await apiClient.get('/dashboard/')
  const payload = data && data.data ? data.data : data

  return {
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
