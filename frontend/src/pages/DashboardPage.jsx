import { lazy, memo, Suspense, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, CircleDot, Cpu, GitBranch, RefreshCw, Sparkles, TrendingUp } from 'lucide-react'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import Modal from '../components/ui/Modal'
import { fetchDashboard, fetchDashboardInsights, getCachedDashboard } from '../api/dashboard'
import { fetchWorkflow, fetchWorkflows } from '../api/workflows'
import { buildWorkflowAgentMap, isWorkflowActive, safeTaskDiagnostic, safeWorkflowOutput, workflowAgentCatalog, workflowMapLayout } from './workflowPresentation'
import { selectTestGenerationMetrics, testGenerationMetricRows } from './dashboardMetrics'

const KnowledgeHistoryChart = lazy(() => import('./KnowledgeHistoryChart'))
const displayCount = (value) => value == null ? 'Unavailable' : value
const displayPercent = (value) => value == null ? 'Unavailable' : `${value}%`
const DashboardPage = () => {
  const [data, setData] = useState(getCachedDashboard)
  const [loading, setLoading] = useState(() => !getCachedDashboard())
  const [error, setError] = useState(null)
  const navigate = useNavigate()

  // Insights drawer state.
  const [insightsOpen, setInsightsOpen] = useState(false)
  const [insights, setInsights] = useState(null)
  const [insightsLoading, setInsightsLoading] = useState(false)
  const [insightsError, setInsightsError] = useState(null)
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [generationMetricScope, setGenerationMetricScope] = useState('workspace')

  useEffect(() => {
    const controller = new AbortController()

    async function loadDashboard() {
      try {
        const payload = await fetchDashboard({ signal: controller.signal })
        if (!controller.signal.aborted) {
          setData(payload)
          setError(null)
        }
      } catch (err) {
        // No valid session (missing/expired token) → send the user to sign in.
        if (err?.response?.status === 401) {
          if (!controller.signal.aborted) navigate('/login', { replace: true })
          return
        }
        if (!controller.signal.aborted) {
          setError('We could not load your dashboard right now. Please try again.')
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    loadDashboard()
    return () => controller.abort()
  }, [navigate])

  useEffect(() => {
    const projects = data?.active_projects
    if (!Array.isArray(projects) || projects.length === 0) {
      setSelectedProjectId('')
      return
    }

    setSelectedProjectId((current) =>
      projects.some((project) => String(project.id) === current)
        ? current
        : projects.some((project) => String(project.id) === localStorage.getItem('testnova-active-project-id'))
          ? localStorage.getItem('testnova-active-project-id')
          : String(projects[0].id),
    )
  }, [data])

  useEffect(() => {
    if (selectedProjectId) {
      localStorage.setItem('testnova-active-project-id', selectedProjectId)
    }
  }, [selectedProjectId])

  const openInsights = async () => {
    setInsightsOpen(true)
    setInsights(null)
    setInsightsError(null)
    setInsightsLoading(true)
    try {
      const payload = await fetchDashboardInsights()
      setInsights(payload)
      setInsightsError(null)
    } catch (err) {
      if (err?.response?.status === 401) {
        navigate('/login', { replace: true })
        return
      }
      setInsightsError('We could not load your insights right now. Please try again.')
    } finally {
      setInsightsLoading(false)
    }
  }

  const closeInsights = () => {
    setInsightsOpen(false)
  }

  if (loading) {
    return <DashboardSkeleton />
  }

  if (error && !data) {
    return (
      <div className="workspace-page mission-page min-h-full text-slate-100">
        <Navbar title="Quality command" subtitle="Agentic operations" />
        <div className="page-content flex min-h-[60vh] items-center justify-center">
          <div className="flex w-full max-w-md flex-col items-center gap-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 p-8 text-center">
            <p className="text-sm text-rose-200">{error}</p>
            <Button type="button" variant="secondary" onClick={() => window.location.reload()}>
              Retry
            </Button>
          </div>
        </div>
      </div>
    )
  }

  // Defensive fallback so the dashboard never reads from null data.
  const safeData = data || {
    active_projects: null,
    test_generation: { coverage_uplift: null, flake_reduction: null, time_saved_minutes: null },
    test_generation_metrics: { workspace: null, by_project: {} },
    overview: { total_projects: null, total_documents: null, documents_with_chunks: null, total_chunks: null, total_embeddings: null, document_chunk_coverage: null, embedding_coverage: null },
    assistant: { suggestions: [] },
    knowledge_history: null,
  }

  const overviewCards = [
    { label: 'Total Projects', value: safeData.overview.total_projects, tone: 'text-sky-400', icon: 'projects' },
    { label: 'Total Documents', value: safeData.overview.total_documents, tone: 'text-indigo-400', icon: 'documents' },
    { label: 'Total Chunks', value: safeData.overview.total_chunks, tone: 'text-violet-400', icon: 'chunks' },
    { label: 'Total Embeddings', value: safeData.overview.total_embeddings, tone: 'text-emerald-400', icon: 'embeddings' },
  ]
  const generationMetricSelection = selectTestGenerationMetrics(
    safeData.test_generation_metrics,
    generationMetricScope,
    selectedProjectId,
  )
  const generationMetricRows = testGenerationMetricRows(
    generationMetricSelection.metrics,
  )

  return (
    <div className="workspace-page mission-page text-slate-100">
      <div className="page-content flex flex-col gap-6">
        <Navbar title="Quality command" subtitle="Agentic operations" />

        <section className="mission-intro" aria-labelledby="mission-heading">
          <div>
            <p className="mission-kicker"><CircleDot size={13} /> Agentic quality workspace</p>
            <h2 className="mission-heading" id="mission-heading">From product signal to release confidence.</h2>
            <p className="mission-description">Bring project evidence, autonomous QA workflows and release decisions into one connected operating view.</p>
          </div>
          <div className="mission-actions">
            {Array.isArray(safeData.active_projects) && safeData.active_projects.length > 0 && (
              <label className="sr-only" htmlFor="mission-project">Project focus</label>
            )}
            {Array.isArray(safeData.active_projects) && safeData.active_projects.length > 0 && (
              <select
                id="mission-project"
                className="project-select"
                value={selectedProjectId}
                onChange={(event) => {
                  localStorage.setItem('testnova-active-project-id', event.target.value)
                  setSelectedProjectId(event.target.value)
                }}
              >
                {safeData.active_projects.map((project) => (
                  <option key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            )}
            <Button
              type="button"
              variant="secondary"
              className="gap-2 whitespace-nowrap"
              onClick={() => navigate('/assistant')}
            >
              <Sparkles size={15} />
              Ask Nova
            </Button>
            <Button
              type="button"
              className="gap-2 whitespace-nowrap"
              onClick={() => navigate(selectedProjectId
                ? `/workflows?project_id=${encodeURIComponent(selectedProjectId)}`
                : '/workflows')}
            >
              <GitBranch size={16} />
              Open workflows
            </Button>
          </div>
        </section>

        {error && (
          <div className="flex items-center justify-between gap-4 rounded-3xl border border-rose-500/30 bg-rose-500/10 px-5 py-4 text-sm text-rose-200">
            <span>{error}</span>
            <Button variant="secondary" onClick={() => window.location.reload()}>
              Retry
            </Button>
          </div>
        )}

        <OrchestrationPanel
          project={safeData.active_projects?.find((item) => String(item.id) === selectedProjectId)}
          projectUnavailable={safeData.active_projects === null}
        />

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {overviewCards.map((card) => (
            <Card key={card.label} className="metric-card !p-4">
              <div className="flex items-center justify-between">
                <p className="text-xs text-slate-400">{card.label}</p>
                <OverviewIcon name={card.icon} />
              </div>
              <p className="metric-card-value mt-3">{displayCount(card.value)}</p>
              <p className="metric-card-label">Across your workspace</p>
            </Card>
          ))}
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <Card title="Workspace coverage" subtitle="Document-to-chunk and chunk-to-embedding coverage are separate ratios.">
            <div className="space-y-5">
              <CoverageMetric
                label="Documents with chunks"
                detail={`${displayCount(safeData.overview.documents_with_chunks)} of ${displayCount(safeData.overview.total_documents)} documents`}
                value={safeData.overview.document_chunk_coverage}
              />
              <CoverageMetric
                label="Chunks with embeddings"
                detail={`${displayCount(safeData.overview.total_embeddings)} of ${displayCount(safeData.overview.total_chunks)} chunks`}
                value={safeData.overview.embedding_coverage}
              />
            </div>
            <Button className="mt-5" onClick={openInsights} disabled={insightsLoading}>
              {insightsLoading ? 'Loading…' : 'View knowledge insights'}
            </Button>
          </Card>

          <Card title="Test generation metrics" subtitle="Measured from persisted requirements, cases and generation records. No baseline uplift or time-saved estimate is stored.">
            <div className="mb-3 flex items-center justify-between gap-3 text-xs text-slate-400">
              <label htmlFor="generation-metric-scope">Scope</label>
              <select
                id="generation-metric-scope"
                value={generationMetricScope}
                onChange={(event) => setGenerationMetricScope(event.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-950/80 px-2 py-1 text-slate-200"
              >
                <option value="workspace">Workspace</option>
                <option value="project" disabled={!selectedProjectId}>Selected project</option>
              </select>
            </div>
            <p className="mb-3 text-xs text-slate-500">
              {generationMetricSelection.scopeLabel === 'Selected project'
                ? safeData.active_projects?.find((project) => String(project.id) === selectedProjectId)?.name || 'Selected project'
                : 'Across your owned workspace projects'}
            </p>
            <div className="space-y-3 text-sm text-slate-300">
              {generationMetricRows.map((metric) => (
                <MetricRow key={metric.label} {...metric} />
              ))}
            </div>
          </Card>
        </div>

        <div className="grid gap-6">
          <Card title="Knowledge indexing history" subtitle="Count snapshots recorded when document, chunk, or embedding totals change; this is not test-execution performance." className="h-full">
            {safeData.knowledge_history === null ? (
              <p className="flex h-72 items-center justify-center text-sm text-slate-400">Knowledge history is unavailable.</p>
            ) : safeData.knowledge_history.length === 0 ? (
              <p className="flex h-72 items-center justify-center text-sm text-slate-400">No knowledge snapshots have been recorded yet.</p>
            ) : (
              <DeferredKnowledgeHistoryChart data={safeData.knowledge_history} />
            )}
          </Card>
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <Card title="Projects" subtitle="Document, chunk, and embedding counts" action={<Button variant="ghost" onClick={() => navigate('/projects')}>See all</Button>}>
            <div className="space-y-3">
              {safeData.active_projects === null ? (
                <p className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
                  Project analytics are unavailable.
                </p>
              ) : safeData.active_projects.length === 0 ? (
                <p className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
                  No active projects yet.
                </p>
              ) : (
                safeData.active_projects.map((project) => (
                  <div key={project.id} className="flex items-center justify-between rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-3">
                    <div>
                      <p className="font-medium text-slate-100">{project.name}</p>
                      <p className="text-sm text-slate-400">{displayCount(project.documents)} documents · {displayCount(project.chunks)} chunks · {displayCount(project.embeddings)} embeddings</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-slate-400">Documents with chunks: {displayPercent(project.document_chunk_coverage)}</p>
                      <p className="text-sm text-slate-400">Chunks with embeddings: {displayPercent(project.embedding_coverage)}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>

          <Card title="Workspace recommendations" subtitle="Suggested knowledge-base actions" action={<Button variant="ghost" onClick={() => navigate('/assistant')}>Open chat</Button>}>
            <div className="space-y-3">
              {safeData.assistant.suggestions.length === 0 ? (
                <p className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
                  No suggestions right now.
                </p>
              ) : (
                safeData.assistant.suggestions.map((suggestion, index) => {
                  const title = typeof suggestion === 'string' ? suggestion : suggestion.title
                  const description = typeof suggestion === 'object' ? suggestion.description : null
                  const priority = typeof suggestion === 'object' ? suggestion.priority : null
                  const priorityColor = priority === 'High' ? 'text-rose-400 bg-rose-500/10' : priority === 'Medium' ? 'text-amber-400 bg-amber-500/10' : 'text-sky-400 bg-sky-500/10'
                  return (
                    <div key={index} className="flex items-start gap-3 rounded-2xl border border-slate-800 bg-slate-950/70 p-3">
                      <div className="rounded-xl bg-sky-500/10 p-2 text-sky-400"><Cpu size={16} /></div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-slate-100">{title}</p>
                          {priority && <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${priorityColor}`}>{priority}</span>}
                        </div>
                        {description && <p className="mt-1 text-sm text-slate-400">{description}</p>}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </Card>
        </div>

        <InsightsModal
          open={insightsOpen}
          onClose={closeInsights}
          loading={insightsLoading}
          error={insightsError}
          insights={insights}
          onRetry={openInsights}
        />
      </div>
    </div>
  )
}

const workflowStatusTone = (status) => {
  if (status === 'completed') return 'text-emerald-500 bg-emerald-500/10'
  if (status === 'failed') return 'text-rose-500 bg-rose-500/10'
  if (status === 'running' || status === 'pending') return 'text-sky-500 bg-sky-500/10'
  if (status === 'partially_completed') return 'text-amber-500 bg-amber-500/10'
  return 'text-slate-400 bg-slate-500/10'
}

function taskDuration(task) {
  if (!task?.started_at) return 'Not started'
  const start = Date.parse(task.started_at)
  const end = task.completed_at ? Date.parse(task.completed_at) : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return 'Unavailable'
  const seconds = Math.floor((end - start) / 1000)
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

const OrchestrationPanel = memo(function OrchestrationPanel({ project, projectUnavailable }) {
  const navigate = useNavigate()
  const reduceMotion = useReducedMotion()
  const [workflow, setWorkflow] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedTaskId, setSelectedTaskId] = useState(null)
  const [workflowRefresh, setWorkflowRefresh] = useState(0)
  const projectId = project?.id

  useEffect(() => {
    if (!projectId) {
      setWorkflow(null)
      setError('')
      setLoading(false)
      setSelectedTaskId(null)
      return undefined
    }

    let cancelled = false
    setLoading(true)
    setError('')
    setSelectedTaskId(null)

    async function loadLatestWorkflow() {
      try {
        const workflows = await fetchWorkflows(Number(projectId))
        const latest = workflows[0]
          ? await fetchWorkflow(Number(projectId), workflows[0].id)
          : null
        if (!cancelled) setWorkflow(latest)
      } catch (requestError) {
        if (requestError?.response?.status === 401) {
          if (!cancelled) navigate('/login', { replace: true })
        } else if (!cancelled) {
          setWorkflow(null)
          setError('Workflow activity could not be loaded for this project.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadLatestWorkflow()
    return () => { cancelled = true }
  }, [navigate, projectId, workflowRefresh])

  useEffect(() => {
    if (!projectId || !workflow || !isWorkflowActive(workflow.status)) return undefined

    let active = true
    let refreshing = false
    const timer = window.setInterval(async () => {
      if (refreshing || document.visibilityState === 'hidden') return
      refreshing = true
      try {
        const latest = await fetchWorkflow(Number(projectId), workflow.id)
        if (active) {
          setError('')
          setWorkflow((current) => (
            current
              && current.id === latest.id
              && current.updated_at
              && latest.updated_at
              && current.updated_at === latest.updated_at
              ? current
              : latest
          ))
        }
      } catch (requestError) {
        if (requestError?.response?.status === 401) {
          if (active) navigate('/login', { replace: true })
        } else if (active) {
          setError('Workflow activity could not be refreshed.')
        }
      } finally {
        refreshing = false
      }
    }, 5000)

    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [navigate, projectId, workflow])

  const refreshWorkflow = () => setWorkflowRefresh((current) => current + 1)
  const openWorkflows = () => navigate(projectId
    ? `/workflows?project_id=${encodeURIComponent(projectId)}`
    : '/workflows')
  const live = isWorkflowActive(workflow?.status)
  const tasks = Array.isArray(workflow?.tasks) ? workflow.tasks : []
  const showingBlueprint = !workflow
  const { nodes: mapNodes, edges: mapEdges } = buildWorkflowAgentMap(tasks)
  const selectedTask = tasks.find((task) => String(task.id) === String(selectedTaskId))
  const selectedDiagnostic = safeTaskDiagnostic(selectedTask?.error_details)
  const taskOutput = selectedTask?.output_data == null
    ? null
    : safeWorkflowOutput(selectedTask.output_data)
  const taskAttempts = Array.isArray(selectedTask?.attempts) ? selectedTask.attempts : []
  const taskNames = new Map(tasks.map((task) => [String(task.id), task.agent_name?.replaceAll('_', ' ') || 'Agent']))
  const diagramRows = Math.max(...mapNodes.map((node) => node.row)) + 1
  const mapWidth = workflowMapLayout.sidePadding * 2
    + workflowMapLayout.columns * workflowMapLayout.columnWidth
    + (workflowMapLayout.columns - 1) * workflowMapLayout.columnGap
  const mapHeight = diagramRows * workflowMapLayout.rowHeight
    + (diagramRows - 1) * workflowMapLayout.rowGap
  const nodeById = new Map(mapNodes.map((node) => [node.id, node]))
  const pointFor = (node, edge, source) => {
    const x = workflowMapLayout.sidePadding
      + node.col * (workflowMapLayout.columnWidth + workflowMapLayout.columnGap)
    const y = node.row * (workflowMapLayout.rowHeight + workflowMapLayout.rowGap)
    const other = nodeById.get(source ? edge.to : edge.from)
    if (node.row === other.row) {
      const sourceIsLeft = node.col < other.col
      return {
        x: x + (source === sourceIsLeft ? workflowMapLayout.columnWidth : 0),
        y: y + workflowMapLayout.rowHeight / 2,
      }
    }
    const forward = other.row >= node.row
    const useBottomEdge = source ? forward : !forward
    return {
      x: x + workflowMapLayout.columnWidth / 2,
      y: y + (useBottomEdge ? workflowMapLayout.rowHeight : 0),
    }
  }
  const edgePath = (edge) => {
    const source = nodeById.get(edge.from)
    const target = nodeById.get(edge.to)
    if (!source || !target) return null
    if (edge.from === 'requirements_analysis' && edge.to === 'test_generation') {
      const sourceY = source.row * (workflowMapLayout.rowHeight + workflowMapLayout.rowGap)
        + workflowMapLayout.rowHeight / 2
      const targetY = target.row * (workflowMapLayout.rowHeight + workflowMapLayout.rowGap)
        + workflowMapLayout.rowHeight / 2
      const nodeLeft = workflowMapLayout.sidePadding
      const routeX = nodeLeft / 2
      return `M ${nodeLeft} ${sourceY} C ${routeX} ${sourceY}, ${routeX} ${targetY}, ${nodeLeft} ${targetY}`
    }
    if (edge.kind === 'feedback') {
      const generation = nodeById.get('test_generation')
      const generationX = workflowMapLayout.sidePadding
        + generation.col * (workflowMapLayout.columnWidth + workflowMapLayout.columnGap)
        + workflowMapLayout.columnWidth / 2
      const sourceX = workflowMapLayout.sidePadding
        + source.col * (workflowMapLayout.columnWidth + workflowMapLayout.columnGap)
        + workflowMapLayout.columnWidth / 2
      const bottom = mapHeight
      return `M ${sourceX} ${bottom} C ${sourceX} ${bottom + 28}, ${generationX} ${bottom + 28}, ${generationX} ${bottom}`
    }
    const from = pointFor(source, edge, true)
    const to = pointFor(target, edge, false)
    const controlY = from.y + (to.y - from.y) / 2
    return `M ${from.x} ${from.y} C ${from.x} ${controlY}, ${to.x} ${controlY}, ${to.x} ${to.y}`
  }

  return (
    <Card
      title="Agent orchestration"
      subtitle={project
        ? live
          ? `Live agent execution for ${project.name}`
          : workflow
            ? `Latest persisted workflow for ${project.name}`
            : `Workflow blueprint for ${project.name}`
        : 'Project workflow activity'}
      className="orchestration-card"
      action={(
        <div className="orchestration-actions">
          {live && (
            <span className="live-workflow-indicator" role="status">
              <span className="live-workflow-dot" />
              Live · 5s refresh
            </span>
          )}
          <Button
            type="button"
            variant="ghost"
            className="gap-2"
            onClick={refreshWorkflow}
            disabled={loading || !project}
            aria-label="Refresh workflow activity"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>
      )}
    >
      {error && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-500/25 bg-rose-500/5 px-4 py-3 text-sm text-rose-500" role="alert">
          <p>{error}</p>
          <Button type="button" variant="secondary" onClick={refreshWorkflow}>Try again</Button>
        </div>
      )}
      {!project && (
        <p className="mb-4 rounded-xl border border-slate-800/80 bg-slate-950/20 px-4 py-3 text-xs text-slate-400">
          {projectUnavailable ? 'Project activity is unavailable.' : 'Create a project to connect this agent workflow to your product evidence.'}
        </p>
      )}

      <div className="orchestration-heading mb-4 rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="brand-mark h-9 w-9 rounded-xl"><GitBranch size={16} /></span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-100">
              {workflow
                ? `Workflow #${workflow.id} · ${(workflow.workflow_type || 'quality workflow').replaceAll('_', ' ')}`
                : 'The full agent execution path'}
            </p>
            <p className="mt-0.5 text-xs text-slate-400">
              {showingBlueprint
                ? 'The orchestrator fans out analysis; agents hand off work through explicit dependencies, with reviewer feedback looping into generation.'
                : `${tasks.length} persisted workflow tasks · select an agent to inspect its inputs, dependencies, attempts, and output`}
              {loading ? ' · refreshing' : ''}
            </p>
          </div>
        </div>
        {workflow ? (
          <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs capitalize ${workflowStatusTone(workflow.status)}`}>
            {(workflow.status || 'unknown').replaceAll('_', ' ')}
          </span>
        ) : (
          <span className="workflow-blueprint-badge">LIVE DEPENDENCY MAP</span>
        )}
      </div>

      <div className="workflow-map-legend" aria-label="Workflow diagram legend">
        <span><i className="workflow-legend-line workflow-legend-dispatch" /> Orchestrator dispatch</span>
        <span><i className="workflow-legend-line workflow-legend-dependency" /> Agent dependency</span>
        <span><i className="workflow-legend-line workflow-legend-feedback" /> Reviewer feedback</span>
      </div>

      <div
        className="workflow-map-viewport"
        data-live={live}
        data-blueprint={showingBlueprint}
        role="group"
        aria-label={live ? 'Live agent workflow dependency map' : 'Agent workflow dependency map'}
        tabIndex={0}
      >
        <div className="workflow-map-canvas" style={{ width: mapWidth, height: mapHeight + 30 }}>
          <svg
            className="workflow-map-links"
            viewBox={`0 0 ${mapWidth} ${mapHeight + 30}`}
            width={mapWidth}
            height={mapHeight + 30}
            aria-hidden="true"
          >
            <defs>
              <marker id="workflow-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 8 4 L 0 8 z" />
              </marker>
            </defs>
            {mapEdges.map((edge) => {
              const path = edgePath(edge)
              if (!path) return null
              return (
                <path
                  key={`${edge.from}-${edge.to}`}
                  className="workflow-map-edge"
                  d={path}
                  data-kind={edge.kind}
                  data-active={live && edge.active}
                  markerEnd="url(#workflow-arrow)"
                />
              )
            })}
          </svg>

          <div className="workflow-map-grid" style={{ left: workflowMapLayout.sidePadding, width: mapWidth - workflowMapLayout.sidePadding * 2, gridTemplateColumns: `repeat(${workflowMapLayout.columns}, ${workflowMapLayout.columnWidth}px)`, gridTemplateRows: `repeat(${diagramRows}, ${workflowMapLayout.rowHeight}px)`, columnGap: workflowMapLayout.columnGap, rowGap: workflowMapLayout.rowGap }}>
            {mapNodes.map((node) => {
              const interactive = Boolean(node.workflowTaskId)
              const status = node.status || 'unknown'
              const selected = String(node.workflowTaskId) === String(selectedTaskId)
              const AgentNode = interactive ? 'button' : 'div'
              const label = node.kind === 'orchestrator'
                ? node.label
                : node.agent_name.replaceAll('_', ' ')
              const detail = node.kind === 'orchestrator' ? node.detail : node.capability
              const badge = node.kind === 'orchestrator'
                ? showingBlueprint ? 'Coordinates agents' : status.replaceAll('_', ' ')
                : node.standalone
                  ? 'On demand'
                  : status === 'not_in_run'
                    ? 'Not in run'
                    : showingBlueprint
                      ? 'Ready'
                      : status.replaceAll('_', ' ')
              return (
                <AgentNode
                  key={node.id}
                  {...(interactive ? {
                    type: 'button',
                    onClick: () => setSelectedTaskId(node.workflowTaskId),
                    'aria-pressed': selected,
                  } : {})}
                  className={`workflow-map-node workflow-map-node-${node.kind}`}
                  data-status={status}
                  data-task-type={node.task_type}
                  data-selected={selected}
                  style={{
                    gridColumn: node.col + 1,
                    gridRow: node.row + 1,
                  }}
                  title={interactive ? `Inspect ${label}` : undefined}
                >
                  <span className="workflow-map-node-top">
                    <span className="workflow-map-node-mark">{node.kind === 'orchestrator' ? 'ORC' : String(workflowAgentCatalog.findIndex((agent) => agent.task_type === node.task_type) + 1).padStart(2, '0')}</span>
                    <span className="workflow-map-node-title">{label}</span>
                    <span className="workflow-map-node-badge" data-status={status}>{badge}</span>
                  </span>
                  <span className="workflow-map-node-detail">{detail}</span>
                </AgentNode>
              )
            })}
          </div>
        </div>
      </div>

      {showingBlueprint && project && !error && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500">Only agent roles and the orchestrator are shown. Knowledge retrieval is available to the assistant on demand.</p>
          <Button type="button" className="gap-2" onClick={openWorkflows}>
            <GitBranch size={15} />
            Start a workflow
          </Button>
        </div>
      )}

      <aside className="inspector-panel mt-4" aria-live="polite">
        <AnimatePresence mode="wait" initial={false}>
          {selectedTask ? (
            <motion.div
              key={selectedTask.id}
              className="space-y-4"
              initial={reduceMotion ? false : { opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, x: -5 }}
              transition={{ duration: reduceMotion ? 0 : 0.16 }}
            >
              <div className="inspector-heading">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Agent inspector</p>
                <span className="agent-status-dot" data-status={selectedTask.status || 'unknown'} />
              </div>
              <div>
                <h3 className="text-base font-semibold capitalize text-slate-100">{(selectedTask.agent_name || 'Agent').replaceAll('_', ' ')}</h3>
                <p className="mt-1 text-xs capitalize text-slate-400">{(selectedTask.task_type || 'task').replaceAll('_', ' ')}</p>
              </div>
              <dl className="grid gap-3 text-xs sm:grid-cols-2">
                <div>
                  <dt className="text-slate-500">Current state</dt>
                  <dd className="mt-1 capitalize text-slate-200">{(selectedTask.status || 'unknown').replaceAll('_', ' ')}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Duration · attempts</dt>
                  <dd className="mt-1 text-slate-300">{taskDuration(selectedTask)} · {selectedTask.attempt_count ?? 0}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Task context</dt>
                  <dd className="mt-1 leading-relaxed text-slate-300">{selectedTask.input_summary || 'Task-specific inputs'}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">Depends on</dt>
                  <dd className="mt-1 leading-relaxed text-slate-300">
                    {(selectedTask.depends_on_task_ids || []).length
                      ? selectedTask.depends_on_task_ids.map((id) => taskNames.get(String(id)) || `Task ${id}`).join(', ')
                      : 'No upstream task'}
                  </dd>
                </div>
              </dl>
              <details className="border-t border-slate-700/70 pt-3">
                <summary className="cursor-pointer text-xs font-medium text-slate-300">Execution history ({taskAttempts.length})</summary>
                {taskAttempts.length === 0 ? (
                  <p className="mt-2 text-xs text-slate-500">No attempt records are available.</p>
                ) : (
                  <ol className="mt-2 space-y-2">
                    {taskAttempts.map((attempt, index) => (
                      <li key={`${selectedTask.id}-${attempt.attempt_number ?? index}`} className="rounded-lg bg-slate-900/70 p-2 text-xs text-slate-400">
                        Attempt {attempt.attempt_number ?? index + 1} · {(attempt.status || 'unknown').replaceAll('_', ' ')}
                        {attempt.started_at ? ` · ${new Date(attempt.started_at).toLocaleString()}` : ''}
                        {safeTaskDiagnostic(attempt.error_details)?.message && (
                          <p className="mt-1 text-rose-500">{safeTaskDiagnostic(attempt.error_details).message}</p>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </details>
              {taskOutput != null && (
                <details className="border-t border-slate-700/70 pt-3">
                  <summary className="cursor-pointer text-xs font-medium text-slate-300">Output record</summary>
                  <pre className="testnova-scroll mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-900/70 p-3 text-[10px] leading-relaxed text-slate-400">
                    {JSON.stringify(taskOutput, null, 2)}
                  </pre>
                </details>
              )}
              {selectedDiagnostic?.message && (
                <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 p-3 text-xs text-rose-500">
                  {selectedDiagnostic.message}
                </div>
              )}
            </motion.div>
          ) : (
            <div className="inspector-empty">
              <div className="max-w-[620px]">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">
                  {showingBlueprint ? 'How the agents coordinate' : 'Agent inspector'}
                </p>
                <p className="mt-2 text-xs leading-relaxed">
                  {showingBlueprint
                    ? 'Requirements, change-risk, and test-history analysis run in parallel and write to shared context. Bug analysis is optional evidence enrichment; test generation can proceed directly from requirements when no relevant defect or failed-run evidence is found. Validation and reviewer feedback complete the loop before aggregation.'
                    : 'Select an agent in the map to inspect its persisted state, upstream dependencies, attempts, and output.'}
                </p>
              </div>
            </div>
          )}
        </AnimatePresence>
      </aside>
    </Card>
  )
})



const OverviewIcon = ({ name }) => {
  const icons = {
    projects: <CheckCircle2 size={16} className="text-sky-400" />,
    documents: <Cpu size={16} className="text-sky-500" />,
    chunks: <Cpu size={16} className="text-emerald-500" />,
    embeddings: <Sparkles size={16} className="text-sky-600" />,
    coverage: <TrendingUp size={16} className="text-cyan-400" />,
  }
  return icons[name] || null
}

const CoverageMetric = ({ label, detail, value }) => (
  <div>
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-sm font-medium text-slate-200">{label}</p>
        <p className="mt-1 text-xs text-slate-500">{detail}</p>
      </div>
      <p className="text-sm font-semibold text-slate-100">{displayPercent(value)}</p>
    </div>
    <div className="mt-2 h-2 rounded-full bg-slate-800">
      {value != null && (
        <div
          className="h-2 rounded-full bg-sky-400"
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      )}
    </div>
  </div>
)

const MetricRow = ({ label, value, detail }) => (
  <div className="flex items-start justify-between gap-3 rounded-2xl bg-slate-900/80 p-3">
    <span className="min-w-0">
      <span className="block">{label}</span>
      <span className="mt-1 block text-xs leading-relaxed text-slate-500">{detail}</span>
    </span>
    <span className="shrink-0 font-medium text-slate-200">{value}</span>
  </div>
)

const InsightsModal = ({ open, onClose, loading, error, insights, onRetry }) => {
  return (
    <Modal open={open} onClose={onClose} title="Knowledge Insights" subtitle="Workspace document, chunk, and embedding metrics">
      {loading ? (
        <div className="space-y-4">
          <div className="h-24 animate-pulse rounded-2xl bg-slate-800/70" />
          <div className="h-32 animate-pulse rounded-2xl bg-slate-800/70" />
          <div className="h-24 animate-pulse rounded-2xl bg-slate-800/70" />
        </div>
      ) : error ? (
        <div className="flex flex-col items-center gap-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-5 py-6 text-center">
          <p className="text-sm text-rose-200">{error}</p>
          <Button variant="secondary" onClick={onRetry}>Retry</Button>
        </div>
      ) : insights ? (
        <div className="space-y-5">
          <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Summary</p>
            <p className="mt-2 text-sm text-slate-200">{insights.summary}</p>
          </div>

          {insights.issues.length > 0 && (
            <div>
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Issues</p>
              <div className="space-y-3">
                {insights.issues.map((issue, idx) => (
                  <IssueRow key={idx} issue={issue} />
                ))}
              </div>
            </div>
          )}

          {insights.recommendations.length > 0 && (
            <div>
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Recommendations</p>
              <ul className="space-y-2">
                {insights.recommendations.map((rec, idx) => (
                  <li
                    key={idx}
                    className="flex items-start gap-3 rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-sm text-slate-200"
                  >
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-sky-400" />
                    {rec}
                  </li>
                ))}
              </ul>
            </div>
          )}

        </div>
      ) : null}
    </Modal>
  )
}

const IssueRow = ({ issue }) => {
  const severityColor =
    issue.severity === 'High'
      ? 'text-rose-400 bg-rose-500/10'
      : issue.severity === 'Medium'
      ? 'text-amber-400 bg-amber-500/10'
      : 'text-sky-400 bg-sky-500/10'
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
      <AlertTriangle className="mt-0.5 shrink-0 text-amber-400" size={18} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-semibold text-slate-100">{issue.title}</p>
          <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${severityColor}`}>{issue.severity}</span>
        </div>
        <p className="mt-1 text-sm text-slate-400">{issue.description}</p>
      </div>
    </div>
  )
}

const SkeletonBlock = ({ className = '' }) => (
  <div className={`animate-pulse rounded-2xl bg-slate-800/60 ${className}`} />
)

const DeferredKnowledgeHistoryChart = ({ data }) => {
  const containerRef = useRef(null)
  const [nearViewport, setNearViewport] = useState(false)

  useEffect(() => {
    if (nearViewport || !containerRef.current) return undefined

    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setNearViewport(true)
        observer.disconnect()
      }
    }, { rootMargin: '240px' })

    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [nearViewport])

  return (
    <div ref={containerRef} className="h-72">
      {nearViewport ? (
        <Suspense fallback={<SkeletonBlock className="h-full" />}>
          <KnowledgeHistoryChart data={data} />
        </Suspense>
      ) : (
        <SkeletonBlock className="h-full" />
      )}
    </div>
  )
}

const DashboardSkeleton = () => {
  return (
    <div className="workspace-page mission-page text-slate-100">
      <div className="page-content flex flex-col gap-6">
        <Navbar title="Quality command" subtitle="Agentic operations" />

        <section className="mission-intro" aria-hidden="true">
          <div className="mission-skeleton-copy">
            <SkeletonBlock className="h-3 w-36" />
            <SkeletonBlock className="mt-4 h-10 w-full max-w-xl" />
            <SkeletonBlock className="mt-3 h-4 w-full max-w-lg" />
          </div>
          <div className="mission-skeleton-actions">
            <SkeletonBlock className="col-span-2 h-10 w-full" />
            <SkeletonBlock className="h-10 w-full" />
            <SkeletonBlock className="h-10 w-full" />
          </div>
        </section>

        <div className="surface-card orchestration-card dashboard-orchestration-skeleton p-5" aria-hidden="true">
          <div className="flex items-center justify-between gap-4">
            <div className="w-full max-w-md">
              <SkeletonBlock className="h-4 w-44" />
              <SkeletonBlock className="mt-2 h-3 w-full" />
            </div>
            <SkeletonBlock className="h-8 w-20 shrink-0" />
          </div>
          <SkeletonBlock className="mt-5 h-12 w-full" />
          <div className="mt-5 grid grid-cols-3 gap-4">
            {[0, 1, 2].map((item) => <SkeletonBlock key={item} className="h-3 w-28" />)}
          </div>
          <SkeletonBlock className="mt-4 h-[490px] w-full rounded-[21px]" />
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="surface-card metric-card !p-4" aria-hidden="true">
              <SkeletonBlock className="h-3 w-20" />
              <SkeletonBlock className="mt-3 h-7 w-14" />
              <SkeletonBlock className="mt-3 h-3 w-32" />
            </div>
          ))}
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="surface-card h-[250px] p-5" aria-hidden="true">
            <SkeletonBlock className="h-4 w-44" />
            <SkeletonBlock className="mt-2 h-3 w-64" />
            <SkeletonBlock className="mt-7 h-12 w-full" />
            <SkeletonBlock className="mt-5 h-12 w-full" />
          </div>
          <div className="surface-card h-[250px] p-5" aria-hidden="true">
            <SkeletonBlock className="h-4 w-44" />
            <SkeletonBlock className="mt-2 h-3 w-64" />
            <SkeletonBlock className="mt-7 h-10 w-full" />
            <SkeletonBlock className="mt-3 h-10 w-full" />
            <SkeletonBlock className="mt-3 h-10 w-full" />
          </div>
        </div>

        <div className="surface-card p-5" aria-hidden="true">
          <SkeletonBlock className="h-4 w-48" />
          <SkeletonBlock className="mt-2 h-3 w-3/4" />
          <SkeletonBlock className="mt-5 h-72 w-full" />
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          {[0, 1].map((item) => (
            <div key={item} className="surface-card h-64 p-5" aria-hidden="true">
              <SkeletonBlock className="h-4 w-40" />
              <SkeletonBlock className="mt-2 h-3 w-56" />
              <SkeletonBlock className="mt-6 h-24 w-full" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default DashboardPage
