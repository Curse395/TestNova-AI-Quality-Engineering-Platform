import { useEffect, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, CircleDot, Cpu, GitBranch, RefreshCw, Sparkles, TrendingUp } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer, CartesianGrid, Tooltip, XAxis, YAxis, Legend } from 'recharts'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import Modal from '../components/ui/Modal'
import { fetchDashboard, fetchDashboardInsights } from '../api/dashboard'
import { fetchWorkflow, fetchWorkflows } from '../api/workflows'
import { isWorkflowActive, safeTaskDiagnostic, safeWorkflowOutput } from './workflowPresentation'

const displayCount = (value) => value == null ? 'Unavailable' : value
const displayPercent = (value) => value == null ? 'Unavailable' : `${value}%`

const DashboardPage = () => {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const navigate = useNavigate()

  // Insights drawer state.
  const [insightsOpen, setInsightsOpen] = useState(false)
  const [insights, setInsights] = useState(null)
  const [insightsLoading, setInsightsLoading] = useState(false)
  const [insightsError, setInsightsError] = useState(null)
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [workflow, setWorkflow] = useState(null)
  const [workflowLoading, setWorkflowLoading] = useState(false)
  const [workflowError, setWorkflowError] = useState('')
  const [selectedTaskId, setSelectedTaskId] = useState(null)
  const [workflowRefresh, setWorkflowRefresh] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function loadDashboard() {
      try {
        const payload = await fetchDashboard()
        if (!cancelled) {
          setData(payload)
          setError(null)
        }
      } catch (err) {
        // No valid session (missing/expired token) → send the user to sign in.
        if (err?.response?.status === 401) {
          if (!cancelled) navigate('/login', { replace: true })
          return
        }
        if (!cancelled) {
          setError('We could not load your dashboard right now. Please try again.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadDashboard()
    return () => {
      cancelled = true
    }
  }, [navigate])

  useEffect(() => {
    const projects = data?.active_projects
    if (!Array.isArray(projects) || projects.length === 0) {
      setSelectedProjectId('')
      setWorkflow(null)
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

  useEffect(() => {
    if (!selectedProjectId) {
      setWorkflow(null)
      setWorkflowError('')
      setWorkflowLoading(false)
      setSelectedTaskId(null)
      return undefined
    }

    let cancelled = false
    setWorkflowLoading(true)
    setWorkflowError('')
    setSelectedTaskId(null)

    async function loadLatestWorkflow() {
      try {
        const workflows = await fetchWorkflows(Number(selectedProjectId))
        const latest = workflows[0]
          ? await fetchWorkflow(Number(selectedProjectId), workflows[0].id)
          : null
        if (!cancelled) setWorkflow(latest)
      } catch (requestError) {
        if (requestError?.response?.status === 401) {
          if (!cancelled) navigate('/login', { replace: true })
        } else if (!cancelled) {
          setWorkflow(null)
          setWorkflowError('Workflow activity could not be loaded for this project.')
        }
      } finally {
        if (!cancelled) setWorkflowLoading(false)
      }
    }

    loadLatestWorkflow()
    return () => { cancelled = true }
  }, [navigate, selectedProjectId, workflowRefresh])

  useEffect(() => {
    if (!selectedProjectId || !workflow || !['pending', 'running'].includes(workflow.status)) {
      return undefined
    }

    let active = true
    let refreshing = false
    const timer = window.setInterval(async () => {
      if (refreshing) return
      refreshing = true
      try {
        const latest = await fetchWorkflow(Number(selectedProjectId), workflow.id)
        if (active) setWorkflow(latest)
      } catch (requestError) {
        if (requestError?.response?.status === 401) {
          if (active) navigate('/login', { replace: true })
        } else if (active) {
          setWorkflowError('Workflow activity could not be refreshed.')
        }
      } finally {
        refreshing = false
      }
    }, 4000)

    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [navigate, selectedProjectId, workflow])

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
        <Navbar title="Mission Control" subtitle="Project intelligence" />
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

  return (
    <div className="workspace-page mission-page text-slate-100">
      <div className="page-content flex flex-col gap-6">
        <Navbar title="Mission Control" subtitle="Project intelligence" />

        <section className="mission-intro" aria-labelledby="mission-heading">
          <div>
            <p className="mission-kicker"><CircleDot size={13} /> Quality engineering overview</p>
            <h2 className="mission-heading" id="mission-heading">A clear view of quality, from evidence to execution.</h2>
            <p className="mission-description">Project knowledge and persisted workflow activity, grounded in your workspace data.</p>
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
          workflow={workflow}
          loading={workflowLoading}
          error={workflowError}
          selectedTaskId={selectedTaskId}
          onSelectTask={setSelectedTaskId}
          onRefresh={() => setWorkflowRefresh((current) => current + 1)}
          onOpenWorkflows={() => navigate(selectedProjectId
            ? `/workflows?project_id=${encodeURIComponent(selectedProjectId)}`
            : '/workflows')}
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

          <Card title="Test generation metrics" subtitle="No measurements are currently available.">
            <div className="space-y-3 text-sm text-slate-300">
              <MetricRow label="Coverage uplift" value={safeData.test_generation.coverage_uplift == null ? 'Unavailable' : `${safeData.test_generation.coverage_uplift}%`} />
              <MetricRow label="Flake reduction" value={safeData.test_generation.flake_reduction == null ? 'Unavailable' : `${safeData.test_generation.flake_reduction}%`} />
              <MetricRow label="Time saved" value={safeData.test_generation.time_saved_minutes == null ? 'Unavailable' : `${safeData.test_generation.time_saved_minutes} minutes`} />
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
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={safeData.knowledge_history}>
                    <CartesianGrid stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="date" stroke="var(--muted)" tickFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} />
                    <YAxis stroke="var(--muted)" allowDecimals={false} />
                    <Tooltip contentStyle={{ background: 'var(--surface)', borderColor: 'var(--border)', borderRadius: 12, color: 'var(--foreground)' }} />
                    <Legend />
                    <Line type="monotone" dataKey="documents" stroke="var(--accent-strong)" strokeWidth={2} dot={{ r: 3 }} />
                    <Line type="monotone" dataKey="chunks" stroke="#8aa592" strokeWidth={2} dot={{ r: 3 }} />
                    <Line type="monotone" dataKey="embeddings" stroke="#b2c4b8" strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
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

function OrchestrationPanel({
  project,
  projectUnavailable,
  workflow,
  loading,
  error,
  selectedTaskId,
  onSelectTask,
  onRefresh,
  onOpenWorkflows,
}) {
  const reduceMotion = useReducedMotion()
  const live = isWorkflowActive(workflow?.status)
  const tasks = Array.isArray(workflow?.tasks) ? workflow.tasks : []
  const selectedTask = tasks.find((task) => String(task.id) === String(selectedTaskId))
  const selectedDiagnostic = safeTaskDiagnostic(selectedTask?.error_details)
  const taskOutput = selectedTask?.output_data == null
    ? null
    : safeWorkflowOutput(selectedTask.output_data)
  const taskAttempts = Array.isArray(selectedTask?.attempts) ? selectedTask.attempts : []
  const taskNames = new Map(tasks.map((task) => [String(task.id), task.agent_name?.replaceAll('_', ' ') || 'Agent']))
  const rows = Math.max(1, Math.ceil(tasks.length / 3))

  return (
    <Card
      title="Agent orchestration"
      subtitle={project
        ? live
          ? `Live agent execution for ${project.name}`
          : `Latest persisted workflow for ${project.name}`
        : 'Project workflow activity'}
      className="orchestration-card"
      action={(
        <div className="orchestration-actions">
          {live && (
            <span className="live-workflow-indicator" role="status">
              <span className="live-workflow-dot" />
              Live · 4s refresh
            </span>
          )}
          <Button
            type="button"
            variant="ghost"
            className="gap-2"
            onClick={onRefresh}
            disabled={loading || !project}
            aria-label="Refresh workflow activity"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
        </div>
      )}
    >
      {loading ? (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(250px,0.65fr)]" aria-label="Loading workflow activity">
          <div className="h-56 animate-pulse rounded-2xl bg-slate-800/50" />
          <div className="h-56 animate-pulse rounded-2xl bg-slate-800/50" />
        </div>
      ) : error ? (
        <div className="rounded-xl border border-rose-500/25 bg-rose-500/5 p-5 text-sm text-rose-500" role="alert">
          <p>{error}</p>
          <Button type="button" variant="secondary" className="mt-4" onClick={onRefresh}>Try again</Button>
        </div>
      ) : !project ? (
        <div className="inspector-empty">
          <p>{projectUnavailable ? 'Project activity is unavailable.' : 'Create a project to view its persisted agent workflows.'}</p>
        </div>
      ) : !workflow ? (
        <div className="inspector-empty">
          <div>
            <p className="text-sm font-medium text-slate-300">No workflow activity yet</p>
            <p className="mt-1 text-xs">Agent states appear here after a workflow is started.</p>
            {project && (
              <Button type="button" className="mt-4 gap-2" onClick={onOpenWorkflows}>
                <GitBranch size={15} />
                Start a workflow
              </Button>
            )}
          </div>
        </div>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(250px,0.65fr)]">
          <div className="min-w-0">
            <div className="orchestration-heading mb-4 rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="brand-mark h-9 w-9 rounded-xl"><GitBranch size={16} /></span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-100">
                    Workflow #{workflow.id} · {(workflow.workflow_type || 'quality workflow').replaceAll('_', ' ')}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-400">{tasks.length} persisted agent tasks · select a task to inspect</p>
                </div>
              </div>
              <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs capitalize ${workflowStatusTone(workflow.status)}`}>
                {(workflow.status || 'unknown').replaceAll('_', ' ')}
              </span>
            </div>

            {tasks.length === 0 ? (
              <p className="rounded-xl border border-dashed border-slate-700 px-4 py-8 text-center text-sm text-slate-400">
                This workflow has no task records to visualize.
              </p>
            ) : (
              <div className="orchestration-board overflow-x-auto rounded-xl border border-slate-800/80 bg-slate-950/20">
                <div className="orchestration-canvas">
                  <svg
                    className="orchestration-links"
                    viewBox={`0 0 900 ${rows * 138}`}
                    preserveAspectRatio="none"
                    style={{ height: `${rows * 138}px` }}
                    aria-hidden="true"
                  >
                    {tasks.flatMap((task, index) => (
                      (task.depends_on_task_ids || []).flatMap((dependencyId) => {
                        const sourceIndex = tasks.findIndex((candidate) => String(candidate.id) === String(dependencyId))
                        if (sourceIndex < 0) return []
                        const sourceX = 150 + (sourceIndex % 3) * 300
                        const sourceY = Math.floor(sourceIndex / 3) * 138 + 56
                        const targetX = 150 + (index % 3) * 300
                        const targetY = Math.floor(index / 3) * 138 + 56
                        const controlY = (sourceY + targetY) / 2
                        const isActive = task.status === 'running' && tasks[sourceIndex].status === 'completed'
                        return (
                          <path
                            key={`${dependencyId}-${task.id}`}
                            className="agent-dependency-path"
                            data-active={isActive}
                            d={`M ${sourceX} ${sourceY} C ${sourceX} ${controlY}, ${targetX} ${controlY}, ${targetX} ${targetY}`}
                          />
                        )
                      })
                    ))}
                  </svg>
                  <div className="orchestration-grid">
                    {tasks.map((task, index) => {
                      const status = task.status || 'unknown'
                      const taskLabel = (task.task_type || 'agent task').replaceAll('_', ' ')
                      const agentLabel = (task.agent_name || 'Agent').replaceAll('_', ' ')
                      return (
                        <motion.button
                          key={task.id}
                          type="button"
                          className="agent-node"
                          data-status={status}
                          aria-pressed={String(task.id) === String(selectedTaskId)}
                          onClick={() => onSelectTask(task.id)}
                          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          whileHover={reduceMotion ? undefined : { y: -2 }}
                          whileTap={reduceMotion ? undefined : { scale: 0.985 }}
                          transition={{ duration: reduceMotion ? 0 : 0.22, delay: reduceMotion ? 0 : Math.min(index * 0.035, 0.28) }}
                        >
                          <span className="agent-node-header">
                            <span className="flex min-w-0 items-center gap-2">
                              <span className="agent-status-dot" data-status={status} />
                              <span className="truncate text-xs font-semibold">{agentLabel}</span>
                            </span>
                            <span className="text-[10px] capitalize text-slate-400">{status.replaceAll('_', ' ')}</span>
                          </span>
                          <span>
                            <span className="block truncate text-xs capitalize text-slate-400">{taskLabel}</span>
                            <span className="agent-node-meta mt-3 text-[10px] text-slate-500">
                              <span>{task.attempt_count ?? 0} attempts</span>
                              <span>{taskDuration(task)}</span>
                            </span>
                          </span>
                        </motion.button>
                      )
                    })}
                  </div>
                </div>
              </div>
            )}
          </div>

          <aside className="inspector-panel" aria-live="polite">
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
                <dl className="space-y-3 text-xs">
                  <div>
                    <dt className="text-slate-500">Current state</dt>
                    <dd className="mt-1 capitalize text-slate-200">{(selectedTask.status || 'unknown').replaceAll('_', ' ')}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Task context</dt>
                    <dd className="mt-1 leading-relaxed text-slate-300">{selectedTask.input_summary || 'Task-specific inputs'}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Duration · attempts</dt>
                    <dd className="mt-1 text-slate-300">{taskDuration(selectedTask)} · {selectedTask.attempt_count ?? 0}</dd>
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
                  <summary className="cursor-pointer text-xs font-medium text-slate-300">
                    Execution history ({taskAttempts.length})
                  </summary>
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
              <motion.div
                key="empty-inspector"
                className="inspector-empty"
                initial={reduceMotion ? false : { opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <p className="max-w-[200px] text-xs leading-relaxed">Select a persisted agent task to inspect its state, dependencies and execution context.</p>
              </motion.div>
            )}
            </AnimatePresence>
          </aside>
        </div>
      )}
    </Card>
  )
}

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

const MetricRow = ({ label, value }) => (
  <div className="flex items-center justify-between rounded-2xl bg-slate-900/80 p-3">
    <span>{label}</span>
    <span className="text-slate-400">{value}</span>
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

const DashboardSkeleton = () => {
  return (
    <div className="workspace-page mission-page text-slate-100">
      <Navbar title="Mission Control" subtitle="Project intelligence" />
      <div className="page-content flex flex-col gap-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="rounded-3xl border border-slate-800/80 bg-slate-900/70 p-4">
              <SkeletonBlock className="h-3 w-20" />
              <SkeletonBlock className="mt-3 h-7 w-14" />
            </div>
          ))}
        </div>

        {/* Top row skeleton */}
        <div className="grid gap-6 xl:grid-cols-[1.5fr_0.8fr]">
          <SkeletonBlock className="h-56" />
          <SkeletonBlock className="h-56" />
        </div>

        {/* Charts row skeleton */}
        <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
          <SkeletonBlock className="h-72" />
          <SkeletonBlock className="h-72" />
        </div>

        {/* Bottom row skeleton */}
        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <SkeletonBlock className="h-56" />
          <SkeletonBlock className="h-56" />
        </div>
      </div>
    </div>
  )
}

export default DashboardPage
