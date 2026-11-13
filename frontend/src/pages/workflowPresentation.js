const statusStyles = {
  pending: 'border-slate-600 bg-slate-800 text-slate-300',
  running: 'border-sky-500/30 bg-sky-500/10 text-sky-200',
  completed: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200',
  partial: 'border-amber-500/30 bg-amber-500/10 text-amber-200',
  skipped: 'border-slate-600 bg-slate-800 text-slate-400',
  blocked: 'border-orange-500/30 bg-orange-500/10 text-orange-200',
  failed: 'border-rose-500/30 bg-rose-500/10 text-rose-200',
  retrying: 'border-amber-500/30 bg-amber-500/10 text-amber-200',
  interrupted: 'border-orange-500/30 bg-orange-500/10 text-orange-200',
  partially_completed: 'border-amber-500/30 bg-amber-500/10 text-amber-200',
}

const knownStatuses = new Set(Object.keys(statusStyles))
const sensitiveKeyPattern = /api[\s_-]?key|authorization|credential|password|secret|token|private[\s_-]?key/i
const stackTracePattern = /traceback \(most recent call last\)|stack trace|sqlalchemy\.|sqlite3\.|postgresql.*(?:error|exception)|\bFile\s+["'][^"']+["'].*\bline\s+\d+|^\s*at\s+\S+/i
const secretValuePattern = /\b(api[_ -]?key|authorization|credential|password|secret|token)\b\s*[:=]\s*(?:Bearer\s+)?["']?[^,\s"'`]+["']?/gi
const bearerPattern = /\bBearer\s+[A-Za-z0-9._~+/-]+=*/gi
const providerKeyPattern = /\b(?:AIza[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{16,})\b/g

export function statusPresentation(status) {
  if (!knownStatuses.has(status)) {
    return { label: 'Unknown status', className: 'border-slate-700 bg-slate-900 text-slate-400' }
  }
  const label = status === 'partial' || status === 'partially_completed'
    ? 'partially completed'
    : status.replaceAll('_', ' ')
  return { label, className: statusStyles[status] }
}

export function isWorkflowActive(status) {
  return status === 'pending' || status === 'running'
}

export function isWorkflowTerminal(status) {
  return ['completed', 'partially_completed', 'failed'].includes(status)
}

export function isTaskTerminal(status) {
  return ['completed', 'partial', 'skipped', 'failed'].includes(status)
}

export function getTaskStatus(task) {
  if (
    task?.status === 'skipped'
    && task.error_details?.code === 'DEPENDENCY_NOT_SATISFIED'
  ) return 'blocked'
  return task?.status
}

export function isCurrentWorkflowProject(requestedProjectId, selectedProjectId) {
  return String(requestedProjectId ?? '') === String(selectedProjectId ?? '')
}

export function selectAvailableProjectId(projects, requestedProjectId) {
  if (!Array.isArray(projects) || projects.length === 0) return ''
  const requestedProject = projects.find(
    (project) => String(project.id) === String(requestedProjectId ?? ''),
  )
  return String(requestedProject?.id ?? projects[0].id)
}

export function workflowTestCasesPageUrl(projectId) {
  return `/test-cases?project_id=${encodeURIComponent(projectId)}`
}

export function workflowGeneratedCases(workflow) {
  const result = workflow?.final_output?.results?.test_generation
  if (Array.isArray(result?.test_cases)) return result.test_cases

  const generationTask = workflow?.tasks?.find((task) => task.task_type === 'test_generation')
  const taskCases = generationTask?.output_data?.structured_data?.test_cases
  return Array.isArray(taskCases) ? taskCases : []
}

export function testCaseEvidenceSources(testCase) {
  if (Array.isArray(testCase?.evidence) && testCase.evidence.length > 0) {
    return testCase.evidence.map((source) => ({ ...source, sourceUnavailable: false }))
  }
  if (Array.isArray(testCase?.evidence_chunk_ids)) {
    return testCase.evidence_chunk_ids.map((chunkId) => ({
      chunk_id: chunkId,
      sourceUnavailable: true,
    }))
  }
  return []
}

export function safeWorkflowText(value, fallback = '') {
  if (typeof value !== 'string') return fallback
  const flattened = value.replace(/[\r\n\t]+/g, ' ').trim()
  if (!flattened) return fallback
  if (stackTracePattern.test(flattened)) return 'Detailed diagnostic information is withheld.'
  return flattened
    .replace(secretValuePattern, '$1=[redacted]')
    .replace(bearerPattern, 'Bearer [redacted]')
    .replace(providerKeyPattern, '[redacted]')
    .slice(0, 1000)
}

export function safeTaskDiagnostic(error) {
  if (!error || typeof error !== 'object') return null
  const code = typeof error.code === 'string' && /^[A-Z][A-Z0-9_]{0,79}$/.test(error.code)
    ? error.code
    : null
  const message = safeWorkflowText(error.message)
  if (!code && !message) return null
  return {
    code,
    message: message || 'Detailed diagnostic information is withheld.',
  }
}

export function safeWorkflowOutput(value, key = '', depth = 0) {
  if (sensitiveKeyPattern.test(key)) return '[redacted]'
  if (typeof value === 'string') return safeWorkflowText(value, '')
  if (value === null || typeof value === 'number' || typeof value === 'boolean') return value
  if (Array.isArray(value)) {
    if (depth >= 6) return '[truncated]'
    return value.slice(0, 100).map((item) => safeWorkflowOutput(item, '', depth + 1))
  }
  if (!value || typeof value !== 'object') return undefined
  if (depth >= 6) return '[truncated]'
  return Object.fromEntries(
    Object.entries(value)
      .slice(0, 100)
      .map(([childKey, childValue]) => [
        childKey,
        safeWorkflowOutput(childValue, childKey, depth + 1),
      ])
      .filter(([, childValue]) => childValue !== undefined),
  )
}
