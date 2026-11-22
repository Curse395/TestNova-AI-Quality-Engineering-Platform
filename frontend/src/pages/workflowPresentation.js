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

export const workflowAgentCatalog = [
  { task_type: 'requirements_analysis', agent_name: 'Requirements analysis agent', capability: 'Maps project evidence into testable requirements', depends_on_types: [] },
  { task_type: 'change_risk_analysis', agent_name: 'Change risk agent', capability: 'Surfaces change impact and risk signals', depends_on_types: [] },
  { task_type: 'test_analysis', agent_name: 'Test analysis agent', capability: 'Reads execution history for quality trends', depends_on_types: [] },
  { task_type: 'bug_analysis', agent_name: 'Bug analysis agent', capability: 'Connects defects and failed runs to requirements', depends_on_types: ['requirements_analysis'] },
  { task_type: 'quality_insights', agent_name: 'Quality insights agent', capability: 'Turns test history into actionable insight', depends_on_types: ['test_analysis'] },
  { task_type: 'test_generation', agent_name: 'Test generation agent', capability: 'Creates evidence-linked test coverage', depends_on_types: ['requirements_analysis', 'bug_analysis'] },
  { task_type: 'deterministic_validation', agent_name: 'Validation service', capability: 'Checks generated cases against quality rules', depends_on_types: ['test_generation'] },
  { task_type: 'review', agent_name: 'Review agent', capability: 'Reviews coverage and validation findings', depends_on_types: ['deterministic_validation'] },
  { task_type: 'aggregation', agent_name: 'Workflow aggregator', capability: 'Waits for all nine task results and builds the outcome', depends_on_types: ['requirements_analysis', 'change_risk_analysis', 'test_analysis', 'bug_analysis', 'quality_insights', 'test_generation', 'deterministic_validation', 'review'] },
  { task_type: 'knowledge_agent', agent_name: 'Knowledge retrieval agent', capability: 'Retrieves cited project context for assistant queries', depends_on_types: [], standalone: true },
]

export const workflowMapLayout = {
  columns: 4,
  sidePadding: 24,
  columnWidth: 216,
  columnGap: 28,
  rowHeight: 96,
  rowGap: 26,
}

export const workflowMapNodes = [
  { id: 'agent_orchestrator', kind: 'orchestrator', label: 'Agent orchestrator', detail: 'Dispatches parallel work · collects agent results', task_type: 'aggregation', col: 1, row: 0 },
  { id: 'requirements_analysis', kind: 'agent', task_type: 'requirements_analysis', col: 0, row: 1 },
  { id: 'change_risk_analysis', kind: 'agent', task_type: 'change_risk_analysis', col: 1, row: 1 },
  { id: 'test_analysis', kind: 'agent', task_type: 'test_analysis', col: 2, row: 1 },
  { id: 'knowledge_agent', kind: 'agent', task_type: 'knowledge_agent', col: 3, row: 1 },
  { id: 'bug_analysis', kind: 'agent', task_type: 'bug_analysis', col: 0, row: 2 },
  { id: 'quality_insights', kind: 'agent', task_type: 'quality_insights', col: 2, row: 2 },
  { id: 'test_generation', kind: 'agent', task_type: 'test_generation', col: 0, row: 3 },
  { id: 'deterministic_validation', kind: 'agent', task_type: 'deterministic_validation', col: 1, row: 3 },
  { id: 'review', kind: 'agent', task_type: 'review', col: 2, row: 3 },
]

export const workflowMapEdges = [
  { from: 'agent_orchestrator', to: 'requirements_analysis', kind: 'dispatch' },
  { from: 'agent_orchestrator', to: 'change_risk_analysis', kind: 'dispatch' },
  { from: 'agent_orchestrator', to: 'test_analysis', kind: 'dispatch' },
  { from: 'requirements_analysis', to: 'bug_analysis', kind: 'dependency', label: 'if relevant evidence' },
  { from: 'requirements_analysis', to: 'test_generation', kind: 'dependency' },
  { from: 'bug_analysis', to: 'test_generation', kind: 'dependency' },
  { from: 'test_analysis', to: 'quality_insights', kind: 'dependency' },
  { from: 'test_generation', to: 'deterministic_validation', kind: 'dependency' },
  { from: 'deterministic_validation', to: 'review', kind: 'dependency' },
  { from: 'review', to: 'test_generation', kind: 'feedback', label: 'revisions' },
]

export function buildWorkflowAgentMap(tasks = []) {
  const taskByType = new Map(tasks.map((task) => [task.task_type, task]))
  const nodes = workflowMapNodes.map((node) => {
    const agent = workflowAgentCatalog.find((item) => item.task_type === node.task_type)
    const task = taskByType.get(node.task_type)
    return {
      ...node,
      ...(agent || {}),
      ...(node.kind === 'orchestrator' ? { ...node } : {}),
      ...(task ? { ...task, workflowTaskId: task.id } : {
        status: agent?.standalone ? 'available' : tasks.length ? 'not_in_run' : 'standby',
        workflowTaskId: null,
      }),
      id: node.id,
    }
  })
  const knownTypes = new Set(workflowAgentCatalog.map((agent) => agent.task_type))
  const unknownTasks = tasks.filter((task) => !knownTypes.has(task.task_type))
  const extraNodes = unknownTasks.map((task, index) => ({
    ...task,
    id: `additional-agent-${task.id}`,
    agent_name: task.agent_name || 'Workflow agent',
    kind: 'agent',
    capability: task.task_type?.replaceAll('_', ' ') || 'Additional workflow task',
    workflowTaskId: task.id,
    col: index % workflowMapLayout.columns,
    row: 4 + Math.floor(index / workflowMapLayout.columns),
  }))
  const taskEdges = workflowMapEdges.flatMap((edge) => {
    const source = edge.from === 'agent_orchestrator'
      ? taskByType.get(edge.to)
      : taskByType.get(edge.from)
    const target = edge.from === 'agent_orchestrator'
      ? taskByType.get(edge.from)
      : edge.to === 'agent_orchestrator'
        ? taskByType.get('aggregation')
        : taskByType.get(edge.to)
    if (!source || !target) return []
    const sourceDelivered = ['completed', 'partial'].includes(source.status)
    return [{
      ...edge,
      active: edge.kind === 'dispatch'
        ? ['running', 'retrying'].includes(source.status)
        : edge.kind === 'feedback'
          ? ['completed', 'failed', 'retrying'].includes(source.status) && ['running', 'retrying'].includes(target.status)
          : sourceDelivered && ['running', 'retrying'].includes(target.status),
    }]
  })
  return {
    nodes: [...nodes, ...extraNodes],
    edges: workflowMapEdges.map((edge) => ({
      ...edge,
      active: taskEdges.some((activeEdge) => activeEdge.from === edge.from && activeEdge.to === edge.to && activeEdge.active),
    })),
  }
}

export function buildWorkflowAgentDiagram(tasks = []) {
  const taskByType = new Map(tasks.map((task) => [task.task_type, task]))
  const showingBlueprint = tasks.length === 0
  const diagram = workflowAgentCatalog.map((agent) => {
    const persistedTask = taskByType.get(agent.task_type)
    if (persistedTask) {
      return { ...agent, ...persistedTask, workflowTaskId: persistedTask.id }
    }
    return {
      ...agent,
      id: `blueprint-${agent.task_type}`,
      status: agent.standalone ? 'available' : showingBlueprint ? 'standby' : 'not_in_run',
      workflowTaskId: null,
    }
  })

  const knownTypes = new Set(workflowAgentCatalog.map((agent) => agent.task_type))
  const unlistedTasks = tasks.filter((task) => !knownTypes.has(task.task_type))
  return [
    ...diagram,
    ...unlistedTasks.map((task) => ({
      ...task,
      agent_name: task.agent_name || 'Workflow agent',
      capability: task.task_type?.replaceAll('_', ' ') || 'Additional workflow task',
      depends_on_types: [],
      workflowTaskId: task.id,
    })),
  ]
}

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
