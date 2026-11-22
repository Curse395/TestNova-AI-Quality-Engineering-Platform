import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import {
  fetchProjectAnalytics,
  fetchProjects,
  generateProjectQualitySummary,
} from '../api/projects'
import {
  reviewStatusDistributionData,
  testCaseDistributionData,
} from './testCasePresentation'
import { potentialImpactHighlights } from './riskImpactPresentation'

const AnalyticsPage = () => {
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [analytics, setAnalytics] = useState(null)
  const [qualitySummary, setQualitySummary] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [summaryError, setSummaryError] = useState('')
  const summaryRequestId = useRef(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    let active = true
    fetchProjects()
      .then((items) => {
        if (!active) return
        setProjects(items)
        if (items.length) setProjectId(String(items[0].id))
      })
      .catch((requestError) => {
        if (!active) return
        if (requestError?.response?.status === 401) navigate('/login', { replace: true })
        else setError('Projects could not be loaded.')
        setLoading(false)
      })
    return () => { active = false }
  }, [navigate])

  useEffect(() => {
    if (!projectId) {
      setAnalytics(null)
      setLoading(false)
      return
    }

    let active = true
    setLoading(true)
    fetchProjectAnalytics(Number(projectId))
      .then((data) => {
        if (active) {
          setAnalytics(data)
          setError('')
        }
      })
      .catch((requestError) => {
        if (!active) return
        if (requestError?.response?.status === 401) navigate('/login', { replace: true })
        else setError('Analytics could not be loaded for this project.')
        setAnalytics(null)
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [projectId, navigate])

  const overview = analytics?.overview
  const testCases = analytics?.testCases
  const coverage = analytics?.coverage
  const risks = analytics?.risks
  const workflowMonitoring = analytics?.workflowMonitoring
  const rows = analytics
    ? (Array.isArray(analytics.documents) ? analytics.documents : null)
    : null
  const caseCategoryData = testCaseDistributionData(testCases?.category_counts, 'category')
  const casePriorityData = testCaseDistributionData(testCases?.priority_counts, 'priority')
  const caseReviewData = reviewStatusDistributionData(testCases?.review_status_counts)
  const riskSeverityData = distributionData(risks?.severity_counts)
    .filter(({ name, value }) => name !== 'unclassified' || Number(value) !== 0)
  const impactHighlights = potentialImpactHighlights(risks?.risks)

  async function handleGenerateSummary() {
    if (!projectId || summaryLoading) return
    const requestId = ++summaryRequestId.current
    const requestedProjectId = Number(projectId)
    setSummaryLoading(true)
    setSummaryError('')
    try {
      const result = await generateProjectQualitySummary(requestedProjectId)
      if (summaryRequestId.current !== requestId) return
      setQualitySummary(result)
      if (result.status !== 'available') {
        setSummaryError(result.error || 'A validated quality summary is unavailable.')
      }
    } catch (requestError) {
      if (summaryRequestId.current !== requestId) return
      if (requestError?.response?.status === 401) {
        navigate('/login', { replace: true })
      } else {
        setSummaryError('Quality summary could not be generated from the available evidence.')
      }
      setQualitySummary(null)
    } finally {
      if (summaryRequestId.current === requestId) setSummaryLoading(false)
    }
  }

  return (
    <div className="workspace-page min-h-screen bg-[var(--background)] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="Quality Analytics" subtitle="Project knowledge and test quality metrics" />
        {projects.length > 0 && (
          <label className="max-w-md text-sm text-slate-400">
            Project
            <select
              value={projectId}
              onChange={(event) => {
                summaryRequestId.current += 1
                setProjectId(event.target.value)
                setQualitySummary(null)
                setSummaryError('')
                setSummaryLoading(false)
              }}
              className="mt-2 block w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-slate-100"
            >
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
          </label>
        )}
        {error && <p role="alert" className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">{error}</p>}
        {loading ? (
          <p className="text-sm text-slate-400">Loading analytics…</p>
        ) : !projects.length ? (
          <p className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6 text-center text-sm text-slate-400">Create a project to see analytics.</p>
        ) : !overview ? (
          <p className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6 text-center text-sm text-slate-400">
            Analytics are unavailable for this project.
          </p>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Metric title="Documents" value={overview.documents} />
              <Metric title="Documents with chunks" value={overview.documents_with_chunks} />
              <Metric title="Chunks" value={overview.chunks} />
              <Metric title="Embeddings" value={overview.embeddings} />
              <Metric title="Document chunk coverage" value={overview.document_chunk_coverage} percentage />
              <Metric title="Embedding coverage" value={overview.embedding_coverage} percentage />
            </div>
            <Card title="Document processing" subtitle="Chunk and embedding counts by document">
              {rows === null ? (
                <p className="text-sm text-slate-400">Document statistics are unavailable.</p>
              ) : rows.length === 0 ? (
                <p className="text-sm text-slate-400">No documents have been uploaded to this project.</p>
              ) : (
                <div className="space-y-4">
                  {rows.map((document) => {
                    const coverage = document.chunks
                      ? Math.min(100, Math.round((document.embeddings / document.chunks) * 100))
                      : null
                    return (
                      <div key={document.document_id} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="break-all font-medium text-slate-100">{document.filename}</p>
                          <p className="text-sm text-slate-400">
                            {document.chunks ?? 'Unavailable'} chunks · {document.embeddings ?? 'Unavailable'} embeddings
                          </p>
                        </div>
                        <div className="mt-3 h-2 rounded-full bg-slate-800">
                          {coverage != null && (
                            <div className="h-2 rounded-full bg-sky-400" style={{ width: `${coverage}%` }} />
                          )}
                        </div>
                        <p className="mt-2 text-right text-xs text-slate-500">
                          {coverage == null ? 'Unavailable' : `${coverage}%`} embedding coverage
                        </p>
                      </div>
                    )
                  })}
                </div>
              )}
            </Card>

            {testCases && (
              <>
                <Card title="Test-case statistics" subtitle={`${testCases.total_cases} persisted test cases; distributions include draft, approved, and rejected cases.`}>
                  <div className="grid gap-4 lg:grid-cols-3">
                    {testCases.total_cases === 0 ? (
                      <p className="text-sm text-slate-400">No test cases are recorded for this project.</p>
                    ) : (
                      <>
                        <DistributionChart title="Cases by category" data={caseCategoryData} valueLabel="Test cases" normalizeCategoryAxis />
                        <DistributionChart title="Cases by priority" data={casePriorityData} valueLabel="Test cases" normalizeCategoryAxis />
                        <DistributionChart
                          title="Cases by review status"
                          data={caseReviewData}
                          valueLabel="Test cases"
                          showPercentages
                          normalizeCategoryAxis
                        />
                      </>
                    )}
                  </div>
                </Card>
              </>
            )}

            {coverage && (
              <Card
                title="Requirement traceability"
                subtitle={coverage.traceability_note}
              >
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <Metric title="Explicit requirements" value={coverage.explicit_requirement_count} />
                  <Metric title="Inferred requirements (separate)" value={coverage.inferred_requirement_count} />
                  <Metric title="Explicit requirements without case links" value={coverage.unlinked_explicit_requirement_count} />
                  <Metric title="Explicit requirements linked to any case" value={`${coverage.explicit_requirements_with_any_case_link} / ${coverage.explicit_requirement_count}`} />
                  <Metric title="Explicit requirements linked to an approved case" value={`${coverage.explicit_requirements_with_approved_case_link} / ${coverage.explicit_requirement_count}`} />
                  <Metric title="Any-case link rate" value={coverage.any_case_link_rate} percentage />
                  <Metric title="Approved-case link rate" value={coverage.approved_case_link_rate} percentage />
                </div>
              </Card>
            )}

            {risks && (
              <Card
                title="Project risk evidence"
                subtitle="Persisted ChangeRiskAgent findings are AI-inferred; execution failures are observed facts. Severity is not a probability."
              >
                {risks.risk_count === 0 ? (
                  <p className="text-sm text-slate-400">{risks.unavailable_reason || 'No persisted risk evidence is available.'}</p>
                ) : (
                  <>
                    <div className="mb-5 grid gap-4 sm:grid-cols-2">
                      <Metric title="Risk findings and observed issues" value={risks.risk_count} />
                      <Metric title="High-priority AI-inferred risks" value={risks.high_priority_risks?.length ?? 0} />
                    </div>
                    <div className="grid gap-6 lg:grid-cols-2">
                      <DistributionChart title="Risk findings by severity (assessed)" data={riskSeverityData} valueLabel="Risk findings" />
                      <PotentialImpactHighlights highlights={impactHighlights} />
                    </div>
                    <div className="mt-6 space-y-3">
                      {(risks.risk_findings_truncated || risks.risk_task_window_truncated) && (
                        <p className="text-xs text-amber-200">
                          Showing {risks.returned_risk_count} prioritized findings from {risks.risk_task_count} recent change-risk tasks; aggregate counts may include more findings within that window.
                          {risks.risk_task_window_truncated ? ' Older risk tasks were not queried.' : ''}
                        </p>
                      )}
                      {risks.risks.map((risk) => (
                        <RiskFindingCard key={risk.id} risk={risk} />
                      ))}
                    </div>
                    <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-slate-500">
                      {risks.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
                    </ul>
                  </>
                )}
              </Card>
            )}

            {workflowMonitoring && (
              <WorkflowMonitoringSection workflowMonitoring={workflowMonitoring} />
            )}
            <Card
              title="AI-generated quality summary"
              subtitle="Generated on request from the listed project evidence. AI interpretation is not a release-readiness assessment."
            >
              <button
                type="button"
                onClick={handleGenerateSummary}
                disabled={summaryLoading}
                className="rounded-xl border border-sky-500/40 bg-sky-500/10 px-4 py-2 text-sm font-medium text-sky-100 disabled:cursor-wait disabled:opacity-60"
              >
                {summaryLoading ? 'Generating from project evidence…' : 'Generate quality summary'}
              </button>
              {summaryError && <p role="alert" className="mt-3 text-sm text-amber-200">{summaryError}</p>}
              {qualitySummary?.status === 'available' && qualitySummary.summary && (
                <div className="mt-5 space-y-4">
                  <SummaryStatements title="Overall summary" items={[qualitySummary.summary.overall_summary]} />
                  {[
                    ['Testing activity', qualitySummary.summary.testing_activity],
                    ['Test-case quality', qualitySummary.summary.test_case_quality],
                    ['Requirement traceability', qualitySummary.summary.requirement_traceability],
                    ['Significant failures', qualitySummary.summary.significant_failures],
                    ['Identified risks', qualitySummary.summary.identified_risks],
                    ['Missing evidence', qualitySummary.summary.missing_evidence],
                    ['Recommended next actions', qualitySummary.summary.recommended_actions],
                    ['Limitations', qualitySummary.summary.limitations],
                  ].map(([title, items]) => (
                    items.length > 0 && <SummaryStatements key={title} title={title} items={items} />
                  ))}
                  <p className="text-xs text-slate-500">
                    {qualitySummary.cached ? 'Reused for unchanged evidence' : 'Generated'} · evidence fingerprint {qualitySummary.evidence_fingerprint}
                  </p>
                  <ul className="list-disc space-y-1 pl-5 text-xs text-slate-500">
                    {qualitySummary.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
                  </ul>
                </div>
              )}
            </Card>
          </>
        )}
      </div>
    </div>
  )
}

const Metric = ({ title, value, percentage = false, suffix = '' }) => (
  <Card className="!p-4">
    <p className="text-xs text-slate-400">{title}</p>
    <p className="mt-3 text-2xl font-semibold text-sky-400">
      {value == null ? 'Unavailable' : `${value}${percentage ? '%' : suffix}`}
    </p>
  </Card>
)

const distributionData = (counts) => (
  counts && typeof counts === 'object'
    ? Object.entries(counts).map(([name, value]) => ({ name, value }))
    : []
)

function WorkflowMonitoringSection({ workflowMonitoring }) {
  const [expanded, setExpanded] = useState(false)
  const workflows = Array.isArray(workflowMonitoring.workflows)
    ? workflowMonitoring.workflows
    : []
  const workflowCount = workflowMonitoring.workflow_count ?? workflows.length

  return (
    <Card
      title="Agent workflow monitoring"
      subtitle={`${workflowCount} persisted workflow snapshots. This is not a real-time progress feed.`}
      action={(
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
          className="shrink-0 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:border-slate-500 hover:text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
        >
          {expanded ? 'Hide snapshots' : 'Show snapshots'}
        </button>
      )}
    >
      {expanded && (
        workflowCount === 0 || workflows.length === 0 ? (
          <p className="text-sm text-slate-400">No workflow history is recorded for this project.</p>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-slate-500">Showing the latest {workflowCount} persisted workflow snapshots.</p>
            {workflows.map((workflow) => (
              <WorkflowSnapshot key={workflow.id} workflow={workflow} />
            ))}
          </div>
        )
      )}
    </Card>
  )
}

function WorkflowSnapshot({ workflow }) {
  const [expanded, setExpanded] = useState(false)
  const tasks = Array.isArray(workflow.tasks) ? workflow.tasks : []

  return (
    <details
      className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 transition-colors open:border-slate-700"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none flex-wrap items-start justify-between gap-x-3 gap-y-2 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-slate-100">
            Workflow {workflow.id} · {String(workflow.workflow_type || 'workflow').replaceAll('_', ' ')}
          </span>
          <span className="mt-1 block text-xs text-slate-500">
            Started {formatTimestamp(workflow.started_at)} · completed {formatTimestamp(workflow.completed_at)}
            {' · '}duration {workflow.duration_ms == null ? 'Unavailable' : `${workflow.duration_ms} ms`}
            {' · '}{workflow.failed_task_count} failed · {workflow.retried_task_count} retried · {tasks.length} tasks
          </span>
        </span>
        <span className={`shrink-0 text-xs capitalize ${workflow.status === 'failed' || workflow.status === 'partially_completed' ? 'text-rose-200' : 'text-slate-300'}`}>
          {String(workflow.status || 'unknown').replaceAll('_', ' ')}
        </span>
      </summary>
      {expanded && (
        <div className="mt-3 space-y-3 border-t border-slate-800 pt-3">
          {workflow.error_summary && (
            <p className="text-sm text-rose-200">{workflow.error_summary}</p>
          )}
          {tasks.length === 0 ? (
            <p className="text-sm text-slate-400">No agent task details are recorded for this workflow.</p>
          ) : (
            <ol className="space-y-2">
              {tasks.map((task, index) => {
                const attempts = Array.isArray(task.attempts) ? task.attempts : []
                return (
                  <li key={task.id || `${workflow.id}-task-${index}`} className="rounded-lg bg-slate-900/70 p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-slate-200">
                        {task.execution_order == null ? `Plan ${task.plan_order} · not started` : `Started #${task.execution_order}`}
                        {' · '}{String(task.agent_name || 'agent').replaceAll('_', ' ')}
                      </span>
                      <span className={`capitalize ${task.status === 'failed' ? 'text-rose-200' : task.status === 'retrying' ? 'text-amber-200' : 'text-slate-400'}`}>
                        {task.status} · {task.attempt_count} attempt(s)
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      Started {formatTimestamp(task.started_at)} · completed {formatTimestamp(task.completed_at)}
                      {' · '}duration {task.duration_ms == null ? 'Unavailable' : `${task.duration_ms} ms`}
                    </p>
                    {task.error && (
                      <p className="mt-1 text-xs text-rose-200">
                        {[task.error.code, task.error.message].filter(Boolean).join(': ')}
                      </p>
                    )}
                    {attempts.length > 1 && (
                      <p className="mt-1 text-xs text-amber-200">
                        Attempt history: {attempts.map((attempt) => `#${attempt.attempt_number} ${attempt.status}`).join(' · ')}
                      </p>
                    )}
                  </li>
                )
              })}
            </ol>
          )}
        </div>
      )}
    </details>
  )
}

const DistributionChart = ({
  title,
  data,
  valueLabel,
  showPercentages = false,
  normalizeCategoryAxis = false,
}) => (
  <div>
    <h3 className="mb-2 text-sm font-medium text-slate-300">{title}</h3>
    <div className="h-56">
      {data.length === 0 ? (
        <p className="flex h-full items-center justify-center text-sm text-slate-400">Analytics unavailable.</p>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis
              dataKey="name"
              stroke="#64748b"
              {...(normalizeCategoryAxis ? {
                type: 'category',
                allowDuplicatedCategory: false,
                interval: 0,
                tickMargin: 8,
                tick: { fill: '#64748b', fontSize: 11 },
              } : {})}
            />
            <YAxis stroke="#64748b" allowDecimals={false} />
            <Tooltip
              formatter={(value, _name, item) => [
                showPercentages && Number.isFinite(item?.payload?.percentage)
                  ? `${value} (${item.payload.percentage}%)`
                  : value,
                valueLabel,
              ]}
            />
            <Bar dataKey="value" name={valueLabel} fill="#38bdf8" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
    {showPercentages && data.length > 0 && (
      <ul aria-label="Review status counts and percentages" className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400">
        {data.map((item) => (
          <li key={item.name}>{item.name}: {item.value} ({item.percentage}%)</li>
        ))}
      </ul>
    )}
  </div>
)

const PotentialImpactHighlights = ({ highlights }) => (
  <section aria-label="Potential Impact Highlights">
    <h3 className="mb-3 text-sm font-medium text-slate-300">Potential Impact Highlights</h3>
    {highlights.length === 0 ? (
      <p className="text-sm text-slate-400">No potential impact descriptions are available from persisted AI-inferred findings.</p>
    ) : (
      <div className="space-y-2">
        {highlights.map((highlight) => (
          <PotentialImpactHighlight key={highlight.name} highlight={highlight} />
        ))}
      </div>
    )}
  </section>
)

function PotentialImpactHighlight({ highlight }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <details
      className="rounded-xl border border-slate-800 bg-slate-950/40 p-3"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-slate-200">{highlight.name}</span>
        <span className="text-xs text-slate-400">
          {highlight.descriptionCount} {highlight.descriptionCount === 1 ? 'impact' : 'impacts'}
          {' · '}{highlight.findingCount} {highlight.findingCount === 1 ? 'finding' : 'findings'}
        </span>
      </summary>
      {expanded && (
        <ul className="mt-3 space-y-3 border-t border-slate-800 pt-3">
          {highlight.descriptions.map((item, index) => (
            <li key={`${highlight.name}-${index}`} className="text-sm">
              <p className="whitespace-pre-wrap text-slate-300">{item.description}</p>
              <div className="mt-2">
                <p className="text-xs font-medium text-slate-500">Supporting risk findings</p>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-slate-400">
                  {item.findingTitles.map((title) => <li key={title}>{title}</li>)}
                </ul>
              </div>
            </li>
          ))}
        </ul>
      )}
    </details>
  )
}

function RiskFindingCard({ risk }) {
  const [expanded, setExpanded] = useState(false)
  const severity = risk.severity || 'unclassified'
  const assessmentType = risk.kind === 'ai_inferred'
    ? 'AI-inferred change-impact risk'
    : risk.kind === 'observed_fact'
      ? 'Observed execution fact'
      : 'Assessment type unavailable'
  const evidenceReferences = Array.isArray(risk.evidence_references)
    ? risk.evidence_references
    : []

  return (
    <details
      className="rounded-xl border border-slate-800 bg-slate-950/60 p-4"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3">
        <span className="line-clamp-2 min-w-0 flex-1 font-medium text-slate-100">
          {risk.description || 'Untitled risk finding'}
        </span>
        <span className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full border px-2.5 py-1 text-xs ${
            severity === 'critical' || severity === 'high'
              ? 'border-rose-500/30 bg-rose-500/10 text-rose-200'
              : 'border-slate-700 bg-slate-900 text-slate-300'
          }`}>
            {severity === 'unclassified' ? 'Severity unclassified' : `${severity} severity`}
          </span>
          <span className="text-xs text-slate-400">{assessmentType}</span>
        </span>
      </summary>
      {expanded && (
        <div className="mt-4 space-y-4 border-t border-slate-800 pt-4">
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Description</h4>
            <p className="mt-1 whitespace-pre-wrap text-sm text-slate-200">
              {risk.description || 'No description recorded.'}
            </p>
          </section>
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Potential impact</h4>
            <p className="mt-1 whitespace-pre-wrap text-sm text-slate-300">
              {Array.isArray(risk.potential_impact) && risk.potential_impact.length
                ? risk.potential_impact.join(' ')
                : 'No potential impact recorded.'}
            </p>
          </section>
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Assessment details</h4>
            <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs text-slate-500">Assessment type</dt>
                <dd className="mt-1 text-slate-300">{assessmentType}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Category</dt>
                <dd className="mt-1 capitalize text-slate-300">
                  {(risk.category || 'not specified').replaceAll('_', ' ')}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs text-slate-500">Assessment</dt>
                <dd className="mt-1 whitespace-pre-wrap text-slate-300">
                  {risk.explanation || 'No assessment explanation recorded.'}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs text-slate-500">Severity basis</dt>
                <dd className="mt-1 text-slate-300">
                  {risk.severity_basis || 'No severity basis recorded.'}
                </dd>
              </div>
              {(risk.assessed_at || risk.source_workflow_id != null || risk.source_task_id != null) && (
                <div className="sm:col-span-2 text-xs text-slate-500">
                  {risk.assessed_at && <>Assessed {formatTimestamp(risk.assessed_at)}</>}
                  {risk.source_workflow_id != null && ` · Workflow ${risk.source_workflow_id}`}
                  {risk.source_task_id != null && ` · Task ${risk.source_task_id}`}
                </div>
              )}
            </dl>
          </section>
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Source evidence references</h4>
            {evidenceReferences.length ? (
              <ul className="mt-2 space-y-2">
                {evidenceReferences.map((reference) => (
                  <li
                    key={reference.id || `${reference.kind}-${reference.document_id}-${reference.chunk_id}`}
                    className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm"
                  >
                    <p className="break-all text-sky-200">
                      {reference.label || reference.id || 'Evidence reference'}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {reference.kind?.replaceAll('_', ' ') || 'source'}
                      {reference.document_id != null && ` · Document ${reference.document_id}`}
                      {reference.chunk_id != null && ` · Chunk ${reference.chunk_id}`}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-slate-400">No source evidence references recorded.</p>
            )}
            {risk.evidence_references_truncated && (
              <p className="mt-2 text-xs text-slate-500">
                Showing {evidenceReferences.length} of {risk.evidence_reference_count} references.
              </p>
            )}
            {risk.evidence_note && <p className="mt-2 text-xs text-amber-200">{risk.evidence_note}</p>}
          </section>
        </div>
      )}
    </details>
  )
}

const SummaryStatements = ({ title, items }) => (
  <section className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
    <h3 className="text-sm font-medium text-slate-200">{title}</h3>
    <ul className="mt-2 space-y-2">
      {items.map((item, index) => (
        <li key={`${title}-${index}`} className="text-sm text-slate-300">
          <span>{item.statement}</span>
          {item.interpretation && <span className="ml-2 text-xs text-amber-200">AI interpretation</span>}
          <p className="mt-1 text-xs text-slate-500">Evidence: {item.evidence_ids.join(', ')}</p>
        </li>
      ))}
    </ul>
  </section>
)

function formatTimestamp(value) {
  if (!value) return 'Unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unavailable'
    : date.toLocaleString(undefined, { timeZone: 'UTC' })
}

export default AnalyticsPage
