import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
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
  fetchProjectReleaseReadiness,
  fetchProjects,
  generateProjectQualitySummary,
} from '../api/projects'
import {
  formatAvailableMetric,
  formatExecutionStatus,
  RELEASE_STATES,
  sortReleaseConcerns,
} from './releaseReadinessPresentation'

const STATE_STYLES = {
  ready_for_review: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200',
  attention_required: 'border-amber-500/30 bg-amber-500/10 text-amber-200',
  blocked: 'border-rose-500/30 bg-rose-500/10 text-rose-200',
  insufficient_evidence: 'border-slate-500/40 bg-slate-800 text-slate-200',
}

const STATUS_COLORS = {
  passed: '#34d399',
  failed: '#fb7185',
  error: '#f97316',
  skipped: '#fbbf24',
  other: '#a78bfa',
  missing: '#94a3b8',
  blank: '#64748b',
}

const formatValue = formatAvailableMetric
const formatPercent = (value) => value == null ? 'Unavailable' : `${value}%`
const dateOnly = (value) => value ? value.slice(0, 10) : 'Unavailable'

export default function ReleaseReadinessPage() {
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [data, setData] = useState(null)
  const [summary, setSummary] = useState(null)
  const [summaryError, setSummaryError] = useState('')
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [loadingProjects, setLoadingProjects] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const summaryRequestId = useRef(0)
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
      })
      .finally(() => { if (active) setLoadingProjects(false) })
    return () => { active = false }
  }, [navigate])

  useEffect(() => {
    if (!projectId) {
      setData(null)
      setLoading(false)
      return undefined
    }

    let active = true
    summaryRequestId.current += 1
    setLoading(true)
    setData(null)
    setError('')
    setSummary(null)
    setSummaryError('')
    fetchProjectReleaseReadiness(Number(projectId))
      .then((result) => {
        if (!active) return
        setData(result)
        setError('')
      })
      .catch((requestError) => {
        if (!active) return
        if (requestError?.response?.status === 401) navigate('/login', { replace: true })
        else setError('Release evidence could not be loaded for this project.')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => {
      active = false
      summaryRequestId.current += 1
    }
  }, [projectId, navigate])

  async function handleGenerateSummary() {
    if (!projectId || summaryLoading) return
    const requestId = ++summaryRequestId.current
    setSummaryLoading(true)
    setSummaryError('')
    try {
      const result = await generateProjectQualitySummary(Number(projectId))
      if (summaryRequestId.current !== requestId) return
      setSummary(result)
      if (result.status !== 'available') {
        setSummaryError(result.error || 'An evidence-validated AI summary is unavailable.')
      }
    } catch (requestError) {
      if (summaryRequestId.current !== requestId) return
      if (requestError?.response?.status === 401) navigate('/login', { replace: true })
      else setSummaryError('The AI summary could not be generated from the available evidence.')
      setSummary(null)
    } finally {
      if (summaryRequestId.current === requestId) setSummaryLoading(false)
    }
  }

  const metrics = data?.metrics
  const cases = metrics?.test_cases
  const traceability = metrics?.requirement_traceability
  const executions = metrics?.executions
  const trends = executions?.trends?.buckets || []
  const risks = metrics?.risks
  const workflows = metrics?.workflows
  const assessment = data?.assessment

  return (
    <div className="workspace-page min-h-screen bg-[var(--background)] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar
          title="Release Readiness"
          subtitle="Evidence-based project review; not a production-readiness verdict"
        />
        {projects.length > 0 && (
          <label className="max-w-md text-sm text-slate-400">
            Project
            <select
              value={projectId}
              onChange={(event) => {
                summaryRequestId.current += 1
                setProjectId(event.target.value)
                setSummary(null)
                setSummaryError('')
                setError('')
                setSummaryLoading(false)
              }}
              className="mt-2 block w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-slate-100"
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>{project.name}</option>
              ))}
            </select>
          </label>
        )}
        {error && (
          <p role="alert" className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
            {error}
          </p>
        )}
        {loadingProjects || loading ? (
          <p role="status" className="text-sm text-slate-400">Loading release evidence…</p>
        ) : !projects.length ? (
          <p className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6 text-center text-sm text-slate-400">
            Create a project to review release evidence.
          </p>
        ) : !data ? (
          <p className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6 text-center text-sm text-slate-400">
            Release evidence is unavailable for this project.
          </p>
        ) : (
          <>
            <Card title="Release assessment" subtitle={assessment.explanation}>
              <div className="flex flex-wrap items-center justify-between gap-4">
                <span className={`rounded-full border px-4 py-2 text-sm font-semibold ${STATE_STYLES[assessment.state] || STATE_STYLES.insufficient_evidence}`}>
                  {RELEASE_STATES[assessment.state] || assessment.label}
                </span>
                <span className="text-xs text-slate-500">
                  Execution evidence: {dateOnly(executions?.time_range?.first_execution_at)} – {dateOnly(executions?.time_range?.latest_execution_at)}
                </span>
              </div>
              <ul className="mt-4 space-y-2 text-sm text-slate-300">
                {assessment.reasons.map((reason) => <li key={reason}>• {reason}</li>)}
              </ul>
              <p className="mt-4 text-xs text-slate-500">
                A human release review remains necessary. This assessment uses deterministic rules and does not approve production deployment.
              </p>
            </Card>

            <section aria-label="Test case health and requirement traceability" className="grid gap-6 xl:grid-cols-2">
              <Card title="Test-case health" subtitle="Persisted test cases by review status, category, and priority.">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Metric label="Total cases" value={cases?.total_cases} />
                  <Metric label="Approved" value={cases?.review_status_counts?.approved} />
                  <Metric label="Draft" value={cases?.review_status_counts?.draft} />
                  <Metric label="Rejected" value={cases?.review_status_counts?.rejected} />
                </div>
                <div className="mt-5 grid gap-5 md:grid-cols-2">
                  <Distribution title="Cases by category" counts={cases?.category_counts} />
                  <Distribution title="Cases by priority" counts={cases?.priority_counts} />
                </div>
                <p className="mt-4 text-xs text-slate-500">
                  Missing and unexpected category, priority, and review values remain separate in the distributions.
                </p>
                <PageLink to="/test-cases">Review test cases</PageLink>
              </Card>

              <Card title="Requirement traceability" subtitle="Traceability is not proof of complete or adequate testing.">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <Metric label="Explicit requirements" value={traceability?.explicit_requirement_count} />
                  <Metric label="Inferred (separate)" value={traceability?.inferred_requirement_count} />
                  <Metric label="Unlinked explicit" value={traceability?.unlinked_explicit_requirement_count} />
                </div>
                <div className="mt-5 space-y-4">
                  <Rate label="Linked to an approved case (primary)" value={traceability?.approved_case_link_rate} />
                  <Rate label="Linked to any case (secondary)" value={traceability?.any_case_link_rate} />
                </div>
                {traceability?.explicit_requirement_count === 0 && (
                  <p className="mt-3 text-sm text-amber-200">No explicit requirements are available; traceability rates are unavailable.</p>
                )}
                <PageLink to="/analytics">View quality analytics</PageLink>
              </Card>
            </section>

            <Card title="Execution health" subtitle="Counts represent persisted execution runs, including repeated runs of the same case.">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label="Execution runs" value={executions?.total_runs} />
                <Metric label="Pass rate (passed / passed + failed)" value={formatPercent(executions?.pass_rate)} />
                <Metric label="Average duration (valid only)" value={duration(executions?.duration?.average_ms)} />
                <Metric label="Median duration (valid only)" value={duration(executions?.duration?.median_ms)} />
              </div>
              <p className="mt-3 text-xs text-slate-400">
                Valid durations: {formatValue(executions?.duration?.observed_run_count)} · unavailable or invalid: {formatValue(executions?.duration?.unavailable_run_count)}
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Lifetime evidence range: {dateOnly(executions?.time_range?.first_execution_at)} – {dateOnly(executions?.time_range?.latest_execution_at)} · recent activity shows at most 10 runs.
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                {Object.entries(executions?.status_counts || {}).map(([status, count]) => (
                  <span key={status} className="rounded-full border border-slate-700 px-3 py-1 text-xs" style={{ color: STATUS_COLORS[status] || '#cbd5e1' }}>
                    {status}: {count}
                  </span>
                ))}
              </div>
              <div className="mt-6 grid gap-6 xl:grid-cols-2">
                <TrendChart title="Execution runs by day (last 30 days)" data={trends} dataKey="run_count" color="#38bdf8" unit="runs" />
                <TrendChart title="Pass rate by day (determinate runs only)" data={trends} dataKey="pass_rate" color="#34d399" unit="%" />
              </div>
              {executions?.recent_runs?.length ? (
                <div className="mt-5 overflow-x-auto">
                  <h3 className="mb-2 text-sm font-medium text-slate-200">Recent execution activity</h3>
                  <table className="w-full min-w-[32rem] text-left text-xs">
                    <thead className="text-slate-500"><tr><th className="p-2">Run</th><th className="p-2">Status</th><th className="p-2">UTC time</th></tr></thead>
                    <tbody>
                      {executions.recent_runs.map((run) => (
                        <tr key={run.id} className="border-t border-slate-800">
                          <td className="p-2">#{run.id}</td>
                          <td className="p-2">{formatExecutionStatus(run.status)}</td>
                          <td className="p-2">{run.created_at ? run.created_at.replace('T', ' ').replace('+00:00', ' UTC') : 'Unavailable'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="mt-5 text-sm text-slate-400">No persisted execution runs are available; this is not a 100% pass rate.</p>
              )}
            </Card>

            <section aria-label="Risk and workflow health" className="grid gap-6 xl:grid-cols-2">
              <Card title="Risk overview" subtitle="Assessed severity is not a numerical probability. AI-inferred findings are distinct from observed execution facts.">
                {risks?.risk_count ? (
                  <>
                    <div className="grid grid-cols-2 gap-3">
                      <Distribution title="Findings by assessed severity" counts={risks.severity_counts} />
                      <Distribution title="Findings by category" counts={risks.category_counts} />
                    </div>
                    <div className="mt-4 space-y-3">
                      {(risks.risks || []).slice(0, 10).map((risk) => (
                        <article key={risk.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                          <p className="text-sm font-medium text-slate-100">{risk.description}</p>
                          <p className="mt-1 text-xs text-slate-400">
                            {risk.kind === 'ai_inferred' ? 'AI-inferred' : 'Observed fact'} · {risk.severity} · {risk.category?.replaceAll('_', ' ')}
                          </p>
                          <p className="mt-2 text-xs text-slate-300">{risk.explanation}</p>
                          {risk.evidence_references?.length > 0 && (
                            <p className="mt-2 break-all text-xs text-sky-200">Evidence: {risk.evidence_references.map((item) => item.label || item.id).join(', ')}</p>
                          )}
                        </article>
                      ))}
                    </div>
                    {(risks.risk_findings_truncated || risks.risk_task_window_truncated) && (
                      <p className="mt-3 text-xs text-amber-200">Risk history is bounded; older persisted assessments may be omitted.</p>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-slate-400">{risks?.unavailable_reason || 'No persisted risk findings are available; absence of findings is not proof of no risk.'}</p>
                )}
              </Card>

              <Card title="Agent and workflow health" subtitle="Persisted workflow snapshots, not a live monitoring feed.">
                {workflows?.workflow_count ? (
                  <>
                    <p className="mb-3 text-xs text-slate-500">
                      Status, failed-task, retry, and attempt counts cover the latest {workflows.sample_limit} workflow snapshots only.
                    </p>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                      {Object.entries(workflows.workflow_status_counts || {}).map(([status, count]) => (
                        <Metric key={status} label={`Workflows: ${status.replaceAll('_', ' ')}`} value={count} />
                      ))}
                      <Metric label="Failed tasks (snapshot)" value={workflows.failed_task_count} />
                      <Metric label="Retried tasks (snapshot)" value={workflows.retried_task_count} />
                      <Metric label="Recorded attempts" value={workflows.attempt_count} />
                    </div>
                    <div className="mt-4 space-y-3">
                      {workflows.workflows.map((workflow) => (
                        <article key={workflow.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                          <p className="text-sm font-medium">Workflow #{workflow.id} · {workflow.workflow_type.replaceAll('_', ' ')}</p>
                          <p className="mt-1 text-xs text-slate-400">
                            Workflow status: {workflow.status} · tasks: {workflow.task_count} · failed tasks: {workflow.failed_task_count} · retried tasks: {workflow.retried_task_count} · duration: {duration(workflow.duration_ms)}
                          </p>
                        </article>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-slate-400">No persisted workflow history is available for this project.</p>
                )}
                <PageLink to="/workflows">Inspect workflows and agent tasks</PageLink>
              </Card>
            </section>

            <Card title="Outstanding release concerns" subtitle="Prioritized from persisted project evidence; each item includes a suggested next step.">
              {data.concerns?.length ? (
                <div className="space-y-3">
                  {sortReleaseConcerns(data.concerns).map((concern) => (
                    <article key={concern.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <h3 className="font-medium text-slate-100">{concern.title}</h3>
                        <span className={`rounded-full px-2.5 py-1 text-xs ${attentionStyle(concern.attention)}`}>{concern.attention}</span>
                      </div>
                      <p className="mt-2 text-sm text-slate-300">{concern.explanation}</p>
                      <p className="mt-2 text-xs text-slate-500">Source: {concern.source}</p>
                      {concern.evidence_ids?.length > 0 && (
                        <p className="mt-1 break-all text-xs text-sky-200">Evidence: {concern.evidence_ids.join(', ')}</p>
                      )}
                      <p className="mt-2 text-sm text-slate-400">Next: {concern.next_action}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-400">No configured concerns were detected in the available evidence. Human review is still required.</p>
              )}
            </Card>

            <Card
              title="AI-generated quality context"
              subtitle="Optional interpretation of Stage 2–3 evidence. It does not change or override the deterministic assessment above."
            >
              <button
                type="button"
                onClick={handleGenerateSummary}
                disabled={summaryLoading}
                className="rounded-xl border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50"
              >
                {summaryLoading ? 'Generating…' : summary ? 'Refresh AI quality context' : 'Generate AI quality context'}
              </button>
              {summary?.status === 'available' && (
                <p className="mt-3 text-xs text-slate-500">
                  This is a snapshot from its generation time and may be stale if project evidence has changed. Refresh it to request a summary for current evidence.
                </p>
              )}
              {summaryError && <p role="alert" className="mt-3 text-sm text-amber-200">{summaryError}</p>}
              {summary?.status === 'available' && summary.summary && (
                <div className="mt-4 space-y-4">
                  <SummaryGroup title="Overall summary" items={[summary.summary.overall_summary]} />
                  {[
                    ['Testing activity', summary.summary.testing_activity],
                    ['Requirement traceability', summary.summary.requirement_traceability],
                    ['Execution trends', summary.summary.execution_trends],
                    ['Significant failures', summary.summary.significant_failures],
                    ['Identified risks', summary.summary.identified_risks],
                    ['Limitations', summary.summary.limitations],
                  ].map(([title, items]) => <SummaryGroup key={title} title={title} items={items} />)}
                  <div className="text-xs text-slate-500">
                    AI-generated {summary.generated_at ? new Date(summary.generated_at).toLocaleString() : 'time unavailable'} · {summary.cached ? 'cached evidence' : 'generated'}.
                    <p className="mt-1 break-all">Evidence fingerprint: {summary.evidence_fingerprint}</p>
                  </div>
                  <ul className="list-disc space-y-1 pl-5 text-xs text-slate-500">
                    {summary.limitations?.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
              )}
            </Card>
            <ul className="list-disc space-y-1 pl-5 text-xs text-slate-500">
              {data.limitations?.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}

function Metric({ label, value }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-100">{formatValue(value)}</p>
    </div>
  )
}

function Distribution({ title, counts }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-medium text-slate-300">{title}</h3>
      {counts && Object.keys(counts).length ? (
        <div className="space-y-1.5">
          {Object.entries(counts).map(([label, count]) => (
            <div key={label} className="flex justify-between gap-3 text-xs">
              <span className="text-slate-400">{label}</span>
              <span className="text-slate-200">{formatValue(count)}</span>
            </div>
          ))}
        </div>
      ) : <p className="text-xs text-slate-500">Unavailable</p>}
    </div>
  )
}

function Rate({ label, value }) {
  return (
    <div>
      <div className="mb-1 flex justify-between gap-2 text-sm">
        <span className="text-slate-300">{label}</span>
        <span className="font-medium text-slate-100">{formatPercent(value)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-800">
        {value != null && <div className="h-full bg-sky-400" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />}
      </div>
    </div>
  )
}

function TrendChart({ title, data, dataKey, color, unit }) {
  const points = data.map((item) => ({
    ...item,
    label: dateOnly(item.start),
    value: item[dataKey],
  }))
  return (
    <div>
      <h3 className="mb-2 text-sm font-medium text-slate-200">{title}</h3>
      {!points.some((item) => item.value != null) ? (
        <p className="flex h-48 items-center justify-center text-sm text-slate-500">No determinate trend data is available.</p>
      ) : (
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            {dataKey === 'run_count' ? (
              <BarChart data={points}>
                <CartesianGrid stroke="#1e293b" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                <YAxis allowDecimals={false} tick={{ fill: '#94a3b8', fontSize: 10 }} />
                <Tooltip formatter={(value) => [`${value} ${unit}`, title]} />
                <Bar dataKey="value" fill={color} radius={[4, 4, 0, 0]} />
              </BarChart>
            ) : (
              <LineChart data={points}>
                <CartesianGrid stroke="#1e293b" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 10 }} unit="%" />
                <Tooltip formatter={(value) => [value == null ? 'Unavailable' : `${value}${unit}`, title]} />
                <Line type="monotone" dataKey="value" stroke={color} connectNulls={false} dot={false} />
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

function SummaryGroup({ title, items }) {
  if (!items?.length) return null
  return (
    <section>
      <h3 className="text-sm font-medium text-slate-200">{title}</h3>
      <ul className="mt-2 space-y-2">
        {items.map((item, index) => (
          <li key={`${title}-${index}`} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-sm text-slate-300">
            <p>{item.statement}</p>
            <p className="mt-1 break-all text-xs text-sky-300">
              Evidence: {item.evidence_ids.join(', ')}{item.interpretation ? ' · interpretation' : ' · observation'}
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}

function PageLink({ to, children }) {
  return <Link to={to} className="mt-4 inline-block text-sm text-sky-300 hover:text-sky-200">{children} →</Link>
}

function duration(value) {
  return value == null ? 'Unavailable' : `${value} ms`
}

function attentionStyle(attention) {
  if (attention === 'blocker') return 'bg-rose-500/10 text-rose-200'
  if (attention === 'high') return 'bg-amber-500/10 text-amber-200'
  if (attention === 'medium') return 'bg-yellow-500/10 text-yellow-100'
  return 'bg-slate-800 text-slate-300'
}
