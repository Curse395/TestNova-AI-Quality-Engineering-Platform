import { apiClient } from './client'

/**
 * Send a message to the AI assistant.
 *
 * @param {number} projectId
 * @param {string} question
 * @returns {Promise<{ success: boolean, answer: string, model: string, sources: Array<{ document_id, document_name, chunk_id, score }> }>}
 */
export async function sendMessage(projectId, question) {
  const { data } = await apiClient.post('/chat/', null, {
    params: { project_id: projectId, question },
  })
  return data
}

/**
 * Load chat history for a project.
 *
 * @param {number} projectId
 * @returns {Promise<Array<{ id: number, question: string, answer: string, created_at: string }>>}
 */
export async function fetchChatHistory(projectId) {
  const { data } = await apiClient.get(`/chat/history/${projectId}`)
  // Backend may return a generator or array — normalise to array
  return Array.isArray(data) ? data : []
}
