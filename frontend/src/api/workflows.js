import { apiClient } from './client'

export async function fetchWorkflows(projectId) {
  const { data } = await apiClient.get(`/projects/${projectId}/workflows`)
  if (!Array.isArray(data?.data)) throw new Error('Unexpected workflows response.')
  return data.data
}

export async function fetchWorkflow(projectId, workflowId) {
  const { data } = await apiClient.get(`/projects/${projectId}/workflows/${workflowId}`)
  if (!data?.data) throw new Error('Unexpected workflow response.')
  return data.data
}

export async function startWorkflow(projectId, workflow) {
  const { data } = await apiClient.post(`/projects/${projectId}/workflows`, workflow)
  if (!data?.data) throw new Error('Unexpected workflow response.')
  return data.data
}

export async function resumeWorkflow(projectId, workflowId) {
  const { data } = await apiClient.post(
    `/projects/${projectId}/workflows/${workflowId}/resume`,
  )
  if (!data?.data) throw new Error('Unexpected workflow response.')
  return data.data
}
