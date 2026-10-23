import { apiClient } from './client'

/**
 * Create a chat session for a project.
 *
 * @param {number} projectId
 * @returns {Promise<{ id: number, project_id: number, title: string, created_at: string, updated_at: string }>}
 */
export async function createChatSession(projectId) {
  const { data } = await apiClient.post('/chat/sessions', null, {
    params: { project_id: projectId },
  })
  return data
}

/**
 * List a project's chat sessions.
 *
 * @param {number} projectId
 * @returns {Promise<Array<{ id: number, project_id: number, title: string, created_at: string, updated_at: string }>>}
 */
export async function fetchChatSessions(projectId) {
  const { data } = await apiClient.get('/chat/sessions', {
    params: { project_id: projectId },
  })
  if (!Array.isArray(data)) {
    throw new Error('Unexpected chat session list response.')
  }
  return data
}

/**
 * Load a session and its persisted messages.
 *
 * @param {number} projectId
 * @param {number} sessionId
 * @returns {Promise<{ id: number, project_id: number, title: string, created_at: string, updated_at: string, messages: Array<{ id: number, question: string, answer: string, created_at: string }> }>}
 */
export async function fetchChatSession(projectId, sessionId) {
  const { data } = await apiClient.get(`/chat/sessions/${sessionId}`, {
    params: { project_id: projectId },
  })
  return data
}

/**
 * Delete a project's chat session.
 *
 * @param {number} projectId
 * @param {number} sessionId
 */
export async function deleteChatSession(projectId, sessionId) {
  const { data } = await apiClient.delete(`/chat/sessions/${sessionId}`, {
    params: { project_id: projectId },
  })
  return data
}

/**
 * Send a message in a specific chat session.
 *
 * @param {number} projectId
 * @param {number} sessionId
 * @param {string} question
 * @returns {Promise<{ success: boolean, answer: string, model: string, sources: Array<{ document_id: number, document_name: string, chunk_id: number, score: number }> }>}
 */
export async function sendMessage(projectId, sessionId, question) {
  const { data } = await apiClient.post('/chat/', null, {
    params: { session_id: sessionId, project_id: projectId, question },
  })
  return data
}
