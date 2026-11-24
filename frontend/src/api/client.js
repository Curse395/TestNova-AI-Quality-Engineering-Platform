import axios from 'axios'

import { getApiErrorMessage, handleUnauthorizedResponse } from './errorMessage.js'

export { getApiErrorMessage }

// Vercel proxies the FastAPI function at /api. Local development can still
// point VITE_API_BASE_URL at the directly running backend.
const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL || '/api'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Attach the JWT token to every request if present.
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Normalize any 401 responses into a clear error for callers.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    handleUnauthorizedResponse(error)
    return Promise.reject(error)
  },
)
