function collectMessage(value) {
  if (typeof value === 'string') return value.trim() || null
  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = collectMessage(item)
      if (nested) return nested
    }
    return null
  }
  if (value && typeof value === 'object') {
    const nested =
      collectMessage(value.message)
      || collectMessage(value.msg)
      || collectMessage(value.detail)
      || collectMessage(value.error)
      || collectMessage(value.errors)
    if (nested) return nested
    return JSON.stringify(value)
  }
  return null
}

export function getApiErrorMessage(error, fallback) {
  const response = error?.response?.data
  const message = collectMessage(response?.detail)
    || collectMessage(response?.message)
    || collectMessage(response?.errors)
  if (message) return message
  if (error?.response?.status === 403) {
    return 'You do not have permission to access this resource.'
  }
  if (error?.response?.status === 429) {
    return 'Too many requests. Please try again shortly.'
  }
  return fallback
}

export function handleUnauthorizedResponse(error) {
  if (error?.response?.status !== 401) return false

  localStorage.removeItem('access_token')
  window.dispatchEvent(new Event('testnova:unauthorized'))
  return true
}
