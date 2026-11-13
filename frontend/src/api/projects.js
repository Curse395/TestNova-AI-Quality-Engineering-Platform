import { apiClient } from './client'

export async function fetchProjects() {
  const { data } = await apiClient.get('/projects/')
  if (!Array.isArray(data?.data)) {
    throw new Error('Unexpected projects response.')
  }
  return data.data
}

export async function createProject(project) {
  const { data } = await apiClient.post('/projects/', project)
  return data.data
}

export async function deleteProject(projectId) {
  const { data } = await apiClient.delete(`/projects/${projectId}`)
  return data.data
}

export async function fetchProjectAnalytics(
  projectId,
  bucket = 'day',
  dateRange = {},
) {
  const [overview, documents, testCases, coverage, executions, executionTrends, risks, workflowMonitoring] = await Promise.all([
    apiClient.get(`/analytics/overview/${projectId}`),
    apiClient.get(`/analytics/documents/${projectId}`),
    apiClient.get(`/analytics/test-cases/${projectId}`),
    apiClient.get(`/analytics/coverage/${projectId}`),
    apiClient.get(`/analytics/executions/${projectId}`, {
      params: dateRange,
    }),
    apiClient.get(`/analytics/execution-trends/${projectId}`, {
      params: { bucket, ...dateRange },
    }),
    apiClient.get(`/analytics/risks/${projectId}`),
    apiClient.get(`/analytics/workflows/${projectId}`),
  ])
  return {
    overview: overview.data,
    documents: documents.data,
    testCases: testCases.data,
    coverage: coverage.data,
    executions: executions.data,
    executionTrends: executionTrends.data,
    risks: risks.data,
    workflowMonitoring: workflowMonitoring.data,
  }
}

export async function generateProjectQualitySummary(projectId) {
  const { data } = await apiClient.post(`/analytics/quality-summary/${projectId}`)
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Unexpected quality summary response.')
  }
  return data
}

export async function fetchProjectReleaseReadiness(projectId) {
  const { data } = await apiClient.get(`/analytics/release-readiness/${projectId}`)
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Unexpected release readiness response.')
  }
  return data
}

export async function fetchProjectDocuments(projectId) {
  const { data } = await apiClient.get(`/uploads/project/${projectId}`)
  if (!Array.isArray(data?.data)) {
    throw new Error('Unexpected documents response.')
  }
  return data.data
}

export async function fetchProjectTestCases(projectId) {
  const { data } = await apiClient.get(`/projects/${projectId}/test-cases`)
  if (!Array.isArray(data?.data)) {
    throw new Error('Unexpected test cases response.')
  }
  return data.data
}

export async function fetchProjectTestCase(projectId, testCaseId) {
  const { data } = await apiClient.get(`/projects/${projectId}/test-cases/${testCaseId}`)
  const testCase = data?.data ?? data
  if (!testCase || typeof testCase !== 'object' || Array.isArray(testCase)) {
    throw new Error('Unexpected test case response.')
  }
  return testCase
}

export async function updateProjectTestCase(projectId, testCaseId, changes) {
  const { data } = await apiClient.patch(
    `/projects/${projectId}/test-cases/${testCaseId}`,
    changes,
  )
  const testCase = data?.data ?? data
  if (!testCase || typeof testCase !== 'object' || Array.isArray(testCase)) {
    throw new Error('Unexpected test case response.')
  }
  return testCase
}

export async function deleteProjectTestCase(projectId, testCaseId) {
  const { data } = await apiClient.delete(`/projects/${projectId}/test-cases/${testCaseId}`)
  return data?.data ?? data
}

export async function fetchProjectTestCaseGenerationRuns(projectId) {
  const { data } = await apiClient.get(`/projects/${projectId}/test-case-generation-runs`)
  if (!Array.isArray(data?.data)) {
    throw new Error('Unexpected test case generation runs response.')
  }
  return data.data
}

export async function evaluateProjectTestCaseGenerationRun(projectId, runId) {
  const { data } = await apiClient.post(
    `/projects/${projectId}/test-case-generation-runs/${runId}/evaluate`,
  )
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Unexpected generation run evaluation response.')
  }
  return data
}

export async function deleteProjectDocument(documentId) {
  const { data } = await apiClient.delete(`/uploads/${documentId}`)
  return data.data
}

export async function uploadAndProcessDocument(projectId, file, sourceType) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('source_type', sourceType)
  const { data: uploaded } = await apiClient.post('/uploads/', formData, {
    params: { project_id: projectId },
    headers: { 'Content-Type': 'multipart/form-data' },
  })

  const document = uploaded.data
  await apiClient.post(`/documents/${document.id}/process`)
  await apiClient.post('/embeddings/regenerate', null, {
    params: { project_id: projectId, document_id: document.id },
  })
  return document
}
