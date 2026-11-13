import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
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

const STATUS_COLORS = {
  passed: '#34d399',
  failed: '#fb7185',
  error: '#f97316',
  skipped: '#fbbf24',
  other: '#a78bfa',
  missing: '#94a3b8',
  blank: '#64748b',
}

const AnalyticsPage = () => {
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [trendBucket, setTrendBucket] = useState('day')
  const [trendFromDate, setTrendFromDate] = useState('')
  const [trendThroughDate, setTrendThroughDate] = useState('')
  const [appliedTrendRange, setAppliedTrendRange] = useState(null)
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
    fetchProjectAnalytics(
      Number(projectId),
      trendBucket,
      appliedTrendRange || {},
    )
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
  }, [projectId, trendBucket, appliedTrendRange, navigate])

  const overview = analytics?.overview
  const testCases = analytics?.testCases
  const coverage = analytics?.coverage
  const executions = analytics?.executions
  const executionTrends = analytics?.executionTrends
  const risks = analytics?.risks
  const workflowMonitoring = analytics?.workflowMonitoring
  const rows = analytics
    ? (Array.isArray(analytics.documents) ? analytics.documents : null)
    : null
  const caseCategoryData = distributionData(testCases?.category_counts)
  const casePriorityData = distributionData(testCases?.priority_counts)
  const caseReviewData = distributionData(testCases?.review_status_counts)
  const executionStatusData = distributionData(executions?.status_counts)
  const trendBuckets = Array.isArray(executionTrends?.buckets)
    ? executionTrends.buckets
    : []
  const riskSeverityData = distributionData(risks?.severity_counts)
  const riskCategoryData = distributionData(risks?.category_counts)

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
    <div className="min-h-screen bg-[#020617] p-4 text-slate-100 lg:p-6">
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
                          <p className="break-all font-medium text-white">{document.filename}</p>
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
                        <DistributionChart title="Cases by category" data={caseCategoryData} valueLabel="Test cases" />
                        <DistributionChart title="Cases by priority" data={casePriorityData} valueLabel="Test cases" />
                        <DistributionChart title="Cases by review status" data={caseReviewData} valueLabel="Test cases" />
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

            {executions && (
              <Card
                title="Test execution summary"
                subtitle={`${executions.from ? `Filtered from ${formatBucketDate(executions.from)} to ${formatBucketDate(executions.to)} (UTC); ` : 'Lifetime totals; '}each persisted execution run is counted, including repeated runs of a test case.`}
              >
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Metric title="Execution runs" value={executions.total_runs} />
                  <Metric title="Average valid duration" value={executions.duration.average_ms} suffix=" ms" />
                  <Metric title="Median valid duration" value={executions.duration.median_ms} suffix=" ms" />
                  <Metric title="Valid duration observations" value={executions.duration.observed_run_count} />
                  <Metric title="Unavailable/invalid durations" value={executions.duration.unavailable_run_count} />
                </div>
                <div className="mt-6">
                  {executions.total_runs === 0 ? (
                    <p className="text-sm text-slate-400">No execution runs are recorded for this project in this period.</p>
                  ) : (
                    <DistributionChart title="Execution runs by status" data={executionStatusData} valueLabel="Execution runs" />
                  )}
                </div>
              </Card>
            )}

            {executionTrends && (
              <Card title="Execution trends" subtitle={`Execution runs grouped by ${trendBucket}; buckets use UTC execution timestamps.`}>
                <label className="mb-5 block max-w-xs text-sm text-slate-400">
                  Time bucket
                  <select
                    value={trendBucket}
                    onChange={(event) => setTrendBucket(event.target.value)}
                    className="mt-2 block w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-slate-100"
                  >
                    <option value="day">Daily</option>
                    <option value="week">Weekly (Monday start)</option>
                    <option value="month">Monthly</option>
                  </select>
                </label>
                <div className="mb-5 flex flex-wrap items-end gap-3">
                  <label className="text-sm text-slate-400">
                    Start date (UTC, inclusive; applies to execution summary and trends)
                    <input
                      type="date"
                      value={trendFromDate}
                      onChange={(event) => setTrendFromDate(event.target.value)}
                      className="mt-2 block rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-slate-100"
                    />
                  </label>
                  <label className="text-sm text-slate-400">
                    Through date (UTC, inclusive)
                    <input
                      type="date"
                      value={trendThroughDate}
                      onChange={(event) => setTrendThroughDate(event.target.value)}
                      className="mt-2 block rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-slate-100"
                    />
                  </label>
                  <button
                    type="button"
                    disabled={Boolean(trendFromDate) !== Boolean(trendThroughDate)}
                    onClick={() => setAppliedTrendRange(
                      trendFromDate && trendThroughDate
                        ? {
                            from: `${trendFromDate}T00:00:00Z`,
                            to: nextUtcDate(trendThroughDate),
                          }
                        : null,
                    )}
                    className="rounded-xl border border-slate-700 px-4 py-2 text-sm text-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Apply date range
                  </button>
                </div>
                <div className="grid gap-6 xl:grid-cols-2">
                  <TrendRunChart data={trendBuckets} />
                  <TrendPassRateChart data={trendBuckets} />
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
                      <DistributionChart title="Risk findings by category" data={riskCategoryData} valueLabel="Risk findings" />
                    </div>
                    <div className="mt-6 space-y-3">
                      {(risks.risk_findings_truncated || risks.risk_task_window_truncated) && (
                        <p className="text-xs text-amber-200">
                          Showing {risks.returned_risk_count} prioritized findings from {risks.risk_task_count} recent change-risk tasks; aggregate counts may include more findings within that window.
                          {risks.risk_task_window_truncated ? ' Older risk tasks were not queried.' : ''}
                        </p>
                      )}
                      {risks.risks.map((risk) => (
                        <article key={risk.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <h3 className="font-medium text-slate-100">{risk.description}</h3>
                            <span className={`rounded-full border px-2.5 py-1 text-xs ${
                              risk.severity === 'critical' || risk.severity === 'high'
                                ? 'border-rose-500/30 bg-rose-500/10 text-rose-200'
                                : 'border-slate-700 bg-slate-900 text-slate-300'
                            }`}>
                              {risk.severity === 'unclassified' ? 'Severity unclassified' : `${risk.severity} · assessed`}
                            </span>
                          </div>
                          <p className="mt-2 text-sm text-slate-400">
                            {risk.kind === 'ai_inferred' ? 'AI-inferred change-impact risk' : 'Observed execution fact'}
                            {' · '}{risk.category.replaceAll('_', ' ')}
                          </p>
                          <p className="mt-2 text-sm text-slate-300">{risk.explanation}</p>
                          {risk.potential_impact?.length > 0 && (
                            <p className="mt-2 text-sm text-slate-400">
                              Potential impact: {risk.potential_impact.join(' ')}
                            </p>
                          )}
                          <p className="mt-2 text-xs text-slate-500">{risk.severity_basis}</p>
                          {risk.evidence_references?.length > 0 && (
                            <p className="mt-2 text-xs text-sky-200">
                              Evidence: {risk.evidence_references.map((item) => item.label || item.id).join(', ')}
                              {risk.evidence_references_truncated ? ` · showing ${risk.evidence_references.length} of ${risk.evidence_reference_count}` : ''}
                            </p>
                          )}
                          {risk.evidence_note && (
                            <p className="mt-2 text-xs text-amber-200">{risk.evidence_note}</p>
                          )}
                        </article>
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
              <Card
                title="Agent workflow monitoring"
                subtitle="Persisted workflow/task snapshots; this is not a real-time progress feed."
              >
                {workflowMonitoring.workflow_count === 0 ? (
                  <p className="text-sm text-slate-400">No workflow history is recorded for this project.</p>
                ) : (
                  <div className="space-y-4">
                    <p className="text-xs text-slate-500">Showing the latest {workflowMonitoring.workflow_count} persisted workflow snapshots.</p>
                    {workflowMonitoring.workflows.map((workflow) => (
                      <section key={workflow.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <h3 className="font-medium text-white">
                            Workflow {workflow.id} · {workflow.workflow_type.replaceAll('_', ' ')}
                          </h3>
                          <span className="text-sm capitalize text-slate-300">{workflow.status.replaceAll('_', ' ')}</span>
                        </div>
                        <p className="mt-1 text-xs text-slate-500">
                          Started {formatTimestamp(workflow.started_at)} · completed {formatTimestamp(workflow.completed_at)}
                          {' · '}duration {workflow.duration_ms == null ? 'Unavailable' : `${workflow.duration_ms} ms`}
                          {' · '}{workflow.failed_task_count} failed tasks · {workflow.retried_task_count} retried tasks
                        </p>
                        {workflow.error_summary && <p className="mt-2 text-sm text-rose-200">{workflow.error_summary}</p>}
                        <ol className="mt-3 space-y-2">
                          {workflow.tasks.map((task) => (
                            <li key={task.id} className="rounded-lg bg-slate-900/70 p-3 text-sm">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <span className="text-slate-200">
                                  {task.execution_order == null ? `Plan ${task.plan_order} · not started` : `Started #${task.execution_order}`}
                                  {' · '}{task.agent_name.replaceAll('_', ' ')}
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
                              {task.attempts.length > 1 && (
                                <p className="mt-1 text-xs text-amber-200">
                                  Attempt history: {task.attempts.map((attempt) => `#${attempt.attempt_number} ${attempt.status}`).join(' · ')}
                                </p>
                              )}
                            </li>
                          ))}
                        </ol>
                      </section>
                    ))}
                  </div>
                )}
              </Card>
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
                    ['Execution trends', qualitySummary.summary.execution_trends],
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

const DistributionChart = ({ title, data, valueLabel }) => (
  <div>
    <h3 className="mb-2 text-sm font-medium text-slate-300">{title}</h3>
    <div className="h-56">
      {data.length === 0 ? (
        <p className="flex h-full items-center justify-center text-sm text-slate-400">Analytics unavailable.</p>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="name" stroke="#64748b" />
            <YAxis stroke="#64748b" allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="value" name={valueLabel} fill="#38bdf8" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  </div>
)

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

const TrendRunChart = ({ data }) => (
  <div>
    <h3 className="mb-2 text-sm font-medium text-slate-300">Execution runs by outcome</h3>
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid stroke="#1e293b" vertical={false} />
          <XAxis dataKey="start" stroke="#64748b" tickFormatter={formatBucketDate} />
          <YAxis stroke="#64748b" allowDecimals={false} />
          <Tooltip labelFormatter={formatBucketDate} />
          <Legend />
          {Object.entries(STATUS_COLORS).map(([status, color]) => (
            <Bar
              key={status}
              dataKey={`status_counts.${status}`}
              name={status}
              stackId="runs"
              fill={color}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  </div>
)

const TrendPassRateChart = ({ data }) => (
  <div>
    <h3 className="mb-2 text-sm font-medium text-slate-300">Pass rate among passed/failed runs</h3>
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid stroke="#1e293b" vertical={false} />
          <XAxis dataKey="start" stroke="#64748b" tickFormatter={formatBucketDate} />
          <YAxis stroke="#64748b" domain={[0, 100]} unit="%" />
          <Tooltip
            labelFormatter={formatBucketDate}
            formatter={(value) => value == null ? 'Unavailable' : `${value}%`}
          />
          <Line
            type="monotone"
            dataKey="pass_rate"
            name="Pass rate"
            stroke="#34d399"
            strokeWidth={3}
            connectNulls={false}
            dot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  </div>
)

function formatBucketDate(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unavailable'
    : date.toLocaleDateString(undefined, { timeZone: 'UTC', month: 'short', day: 'numeric', year: '2-digit' })
}

function formatTimestamp(value) {
  if (!value) return 'Unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unavailable'
    : date.toLocaleString(undefined, { timeZone: 'UTC' })
}

function nextUtcDate(value) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 1)
  return date.toISOString()
}

export default AnalyticsPage
