import { apiClient } from './client'

/**
 * Fetch the full dashboard payload from GET /dashboard/.
 *
 * The backend nests knowledge distribution under `risk.knowledge_distribution`
 * and may use slightly different field spellings than the frontend spec, so we
 * normalize the response into the shape the dashboard consumes.
 */
export async function fetchDashboard() {
  const { data } = await apiClient.get('/dashboard/')

  const payload = data && data.data ? data.data : data

  const knowledgeDistribution = normalizeKnowledgeDistribution(payload)

  return {
    active_projects: payload.active_projects || [],
    quality_center: {
      release_confidence:
        payload.quality_center?.release_confidence ?? 0,
      knowledge_health:
        payload.quality_center?.knowledge_health ?? 0,
      healthy_projects:
        payload.quality_center?.healthy_projects ?? 0,
      medium_risk_projects:
        payload.quality_center?.medium_risk_projects ?? 0,
      high_risk_projects:
        payload.quality_center?.high_risk_projects ?? 0,
      recommendation:
        payload.quality_center?.recommendation ??
        payload.quality_center?.recomendation ??
        '',
    },
    test_generation: {
      coverage_uplift:
        payload.test_generation?.coverage_uplift ?? null,
      flake_reduction:
        payload.test_generation?.flake_reduction ?? null,
      time_saved_minutes:
        payload.test_generation?.time_saved_minutes ?? null,
    },
    overview: {
      total_projects: payload.overview?.total_projects ?? 0,
      total_documents: payload.overview?.total_documents ?? 0,
      total_chunks: payload.overview?.total_chunks ?? 0,
      total_embeddings: payload.overview?.total_embeddings ?? 0,
      overall_coverage: payload.overview?.overall_coverage ?? 0,
    },
    live_health: {
      healthy: payload.live_health?.healthy ?? 0,
      needs_review: payload.live_health?.needs_review ?? 0,
      critical: payload.live_health?.critical ?? 0,
    },
    knowledge_distribution: knowledgeDistribution,
    assistant: {
      suggestions: payload.assistant?.suggestions || [],
    },
    performance_trend: (payload.performance_trend || []).map((entry) => ({
      date: entry.date,
      documents: entry.documents,
      chunks: entry.chunks,
      embeddings: entry.embeddings ?? entry.embedding,
    })),
  }
}

/**
 * Extract and normalize the knowledge distribution array.
 *
 * Prefers the top-level `knowledge_distribution` (frontend spec) but falls back
 * to the backend's nested `risk.knowledge_distribution`.
 *
 * Expected format: [{ name, value }]
 */
function normalizeKnowledgeDistribution(payload) {
  const raw = payload.knowledge_distribution || payload.risk?.knowledge_distribution

  if (!Array.isArray(raw) || raw.length === 0) {
    // Fallback derived from overview counts so the pie chart never renders empty.
    const o = payload.overview || {}
    return [
      { name: 'Documents', value: o.total_documents ?? 0 },
      { name: 'Chunks', value: o.total_chunks ?? 0 },
      { name: 'Embeddings', value: o.total_embeddings ?? 0 },
    ]
  }

  return raw.map((item) => ({
    name: item.name,
    value: item.value,
  }))
}

/**
 * Fetch the dashboard insights payload from GET /dashboard/insights.
 *
 * Normalizes the response shape consumed by the Insights drawer:
 * - release_confidence
 * - summary
 * - issues:   [{ title, description, severity }]
 * - recommendations: [string]
 * - estimated_confidence_after_fix
 */
export async function fetchDashboardInsights() {
  const { data } = await apiClient.get('/dashboard/insights')

  const payload = data && data.data ? data.data : data

  return {
    release_confidence: payload.release_confidence ?? 0,
    summary: payload.summary ?? '',
    issues: Array.isArray(payload.issues) ? payload.issues : [],
    recommendations: Array.isArray(payload.recommendations) ? payload.recommendations : [],
    estimated_confidence_after_fix: payload.estimated_confidence_after_fix ?? 0,
  }
}
