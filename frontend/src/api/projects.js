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

export async function fetchProjectAnalytics(projectId) {
  const [overview, documents] = await Promise.all([
    apiClient.get(`/analytics/overview/${projectId}`),
    apiClient.get(`/analytics/documents/${projectId}`),
  ])
  return { overview: overview.data, documents: documents.data }
}

export async function fetchProjectDocuments(projectId) {
  const { data } = await apiClient.get(`/uploads/project/${projectId}`)
  if (!Array.isArray(data?.data)) {
    throw new Error('Unexpected documents response.')
  }
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
