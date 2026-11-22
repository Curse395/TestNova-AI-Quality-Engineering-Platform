import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import { getApiErrorMessage } from '../api/client'
import {
  approveProjectTestCase,
  deleteProjectTestCase,
  evaluateProjectTestCaseGenerationRun,
  fetchProjects,
  fetchProjectTestCase,
  fetchProjectTestCaseGenerationRuns,
  fetchProjectTestCases,
  rejectProjectTestCase,
  updateProjectTestCase,
} from '../api/projects'
import { selectAvailableProjectId } from './workflowPresentation'
import { reviewStatusLabel } from './testCasePresentation'

const fieldClassName = 'mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100'

function editableFields(testCase = {}) {
  return {
    title: testCase.title || '',
    description: testCase.description || '',
    priority: testCase.priority || '',
    severity: testCase.severity || '',
    test_type: testCase.test_type || '',
    category: testCase.category || '',
    preconditions: testCase.preconditions || '',
    steps: Array.isArray(testCase.steps)
      ? testCase.steps.map((step) => ({
        action: step?.action || '',
        expected_result: step?.expected_result || '',
      }))
      : [],
    expected_result: testCase.expected_result || '',
    requirement_keys: Array.isArray(testCase.requirements)
      ? testCase.requirements.map((requirement) => requirement.requirement_key).join('\n')
      : (Array.isArray(testCase.requirement_keys)
        ? testCase.requirement_keys.join('\n')
        : ''),
  }
}

function requirementIds(value) {
  if (Array.isArray(value)) return value.map(String).filter(Boolean)
  if (typeof value !== 'string') return []
  return value.split(/[\n,]+/).map((id) => id.trim()).filter(Boolean)
}

function scalarRunDetails(run) {
  if (!run || typeof run !== 'object') return []
  const fields = [
    ['Status', run.generation_status || run.status],
    ['Started', run.started_at || run.created_at],
    ['Completed', run.completed_at],
    ['Model', run.model || run.model_name],
    ['Generated cases', run.generated_count ?? run.test_case_count ?? run.cases_generated],
    ['Requested maximum', run.requested_max_cases],
    ['Duplicate cases rejected', run.duplicate_rejected_count],
    ['Invalid cases rejected', run.invalid_rejected_count],
    ['Insufficient evidence', run.insufficient_evidence_count],
    ['Final cases persisted', run.final_persisted_count],
    ['Retries', run.retry_count],
    ['Saved cases', run.case_count],
    ['Cases with requirements', run.traced_case_count],
    ['Requested requirement keys', Array.isArray(run.requirement_keys) ? run.requirement_keys.join(', ') : ''],
    ['Covered requirement keys', Array.isArray(run.requirement_keys_covered)
      ? run.requirement_keys_covered.join(', ')
      : ''],
    ['Scenario categories', run.category_counts && typeof run.category_counts === 'object'
      ? Object.entries(run.category_counts).map(([key, value]) => `${key}: ${value}`).join(', ')
      : ''],
  ].filter(([, value]) => value !== undefined && value !== null && value !== '')
  const stats = run.stats || run.statistics || run.metrics || run.generation_stats || run.result?.stats
  if (stats && typeof stats === 'object' && !Array.isArray(stats)) {
    fields.push(...Object.entries(stats)
      .filter(([, value]) => value === null || ['string', 'number', 'boolean'].includes(typeof value))
      .map(([key, value]) => [key.replaceAll('_', ' '), value]))
  }
  return fields
}

function CollapsibleSection({ title, subtitle, children }) {
  return (
    <details className="surface-card rounded-3xl p-5">
      <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
        <span>
          <span className="block text-sm font-semibold text-slate-100">{title}</span>
          <span className="mt-1 block text-sm text-slate-400">{subtitle}</span>
        </span>
        <span className="text-xs text-slate-400">Expand / collapse</span>
      </summary>
      <div className="mt-4">{children}</div>
    </details>
  )
}

function sourceLocation(metadata = {}) {
  const sourceMetadata = metadata && typeof metadata === 'object' ? metadata : {}
  const location = sourceMetadata.source_location && typeof sourceMetadata.source_location === 'object'
    ? sourceMetadata.source_location
    : sourceMetadata
  const parts = []
  if (Array.isArray(location.page_numbers) && location.page_numbers.length) {
    parts.push(`Page${location.page_numbers.length > 1 ? 's' : ''} ${location.page_numbers.join(', ')}`)
  }
  if (location.sheet_name) parts.push(`Sheet: ${location.sheet_name}`)
  if (location.section) parts.push(`Section: ${location.section}`)
  for (const [startKey, endKey, singular, plural] of [
    ['line_start', 'line_end', 'Line', 'Lines'],
    ['row_start', 'row_end', 'Row', 'Rows'],
  ]) {
    const start = location[startKey]
    const end = location[endKey]
    if (Number.isInteger(start) && Number.isInteger(end)) {
      parts.push(start === end ? `${singular} ${start}` : `${plural} ${start}–${end}`)
    } else if (Number.isInteger(start)) {
      parts.push(`${singular} ${start}`)
    } else if (Number.isInteger(end)) {
      parts.push(`${singular} ${end}`)
    }
  }
  if (Array.isArray(location.json_paths)) {
    parts.push(...location.json_paths.filter((path) => typeof path === 'string' && path.length))
  }
  return parts.join(' · ')
}

const TestCasesPage = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedProjectId = searchParams.get('project_id')
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [testCases, setTestCases] = useState([])
  const [generationRuns, setGenerationRuns] = useState([])
  const [runEvaluations, setRunEvaluations] = useState({})
  const [evaluatingRunId, setEvaluatingRunId] = useState(null)
  const [loadingProjects, setLoadingProjects] = useState(true)
  const [loadingCases, setLoadingCases] = useState(false)
  const [error, setError] = useState('')
  const [selectedCase, setSelectedCase] = useState(null)
  const [draft, setDraft] = useState(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [updatingReviewStatus, setUpdatingReviewStatus] = useState(false)
  const [detailError, setDetailError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    let active = true
    fetchProjects()
      .then((items) => {
        if (!active) return
        setProjects(items)
        setProjectId(selectAvailableProjectId(items, requestedProjectId))
      })
      .catch((requestError) => {
        if (!active) return
        if (requestError?.response?.status === 401) navigate('/login', { replace: true })
        else setError(getApiErrorMessage(requestError, 'Projects could not be loaded.'))
      })
      .finally(() => {
        if (active) setLoadingProjects(false)
      })
    return () => { active = false }
  }, [navigate, requestedProjectId])

  useEffect(() => {
    if (!projectId || searchParams.get('project_id') === projectId) return
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('project_id', projectId)
    setSearchParams(nextParams, { replace: true })
  }, [projectId, searchParams, setSearchParams])

  useEffect(() => {
    if (!projectId) {
      setTestCases([])
      setGenerationRuns([])
      setRunEvaluations({})
      return
    }

    let active = true
    setSelectedCase(null)
    setDraft(null)
    setLoadingCases(true)
    setError('')
    fetchProjectTestCases(Number(projectId))
      .then((items) => { if (active) setTestCases(items) })
      .catch((requestError) => {
        if (!active) return
        if (requestError?.response?.status === 401) navigate('/login', { replace: true })
        else setError(getApiErrorMessage(requestError, 'Test cases could not be loaded.'))
      })
      .finally(() => { if (active) setLoadingCases(false) })
    fetchProjectTestCaseGenerationRuns(Number(projectId))
      .then((runs) => { if (active) setGenerationRuns(runs) })
      .catch((requestError) => {
        if (!active) return
        setError((current) => current || getApiErrorMessage(
          requestError,
          'Generation history could not be loaded.',
        ))
      })
    return () => { active = false }
  }, [projectId, navigate])

  const openDetails = (testCase) => {
    setSelectedCase(testCase)
    setDraft(editableFields(testCase))
    setLoadingDetail(true)
    setEditing(false)
    setDetailError('')
    fetchProjectTestCase(Number(projectId), testCase.id)
      .then((details) => {
        setSelectedCase(details)
        setDraft(editableFields(details))
      })
      .catch((requestError) => {
        if (requestError?.response?.status === 401) navigate('/login', { replace: true })
        else setDetailError(getApiErrorMessage(requestError, 'Test case details could not be loaded.'))
      })
      .finally(() => setLoadingDetail(false))
  }

  const saveChanges = async (event) => {
    event.preventDefault()
    setSaving(true)
    setDetailError('')
    const changes = {
      ...draft,
      requirement_keys: requirementIds(draft.requirement_keys),
    }
    try {
      const updated = await updateProjectTestCase(Number(projectId), selectedCase.id, changes)
      const merged = { ...selectedCase, ...changes, ...updated }
      setSelectedCase(merged)
      setDraft(editableFields(merged))
      setTestCases((current) => current.map((item) => (
        String(item.id) === String(merged.id) ? { ...item, ...merged } : item
      )))
      setEditing(false)
    } catch (requestError) {
      if (requestError?.response?.status === 401) navigate('/login', { replace: true })
      else setDetailError(getApiErrorMessage(requestError, 'Test case changes could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  const deleteSelectedCase = async () => {
    if (!selectedCase || !window.confirm(`Delete “${selectedCase.title}”? This cannot be undone.`)) return
    setDeleting(true)
    setDetailError('')
    try {
      await deleteProjectTestCase(Number(projectId), selectedCase.id)
      setTestCases((current) => current.filter((item) => String(item.id) !== String(selectedCase.id)))
      setSelectedCase(null)
      setDraft(null)
    } catch (requestError) {
      if (requestError?.response?.status === 401) navigate('/login', { replace: true })
      else setDetailError(getApiErrorMessage(requestError, 'Test case could not be deleted.'))
    } finally {
      setDeleting(false)
    }
  }

  const updateReviewStatus = async (status) => {
    if (!selectedCase || updatingReviewStatus) return
    setUpdatingReviewStatus(true)
    setDetailError('')
    try {
      const result = status === 'approved'
        ? await approveProjectTestCase(Number(projectId), selectedCase.id)
        : await rejectProjectTestCase(Number(projectId), selectedCase.id)
      const updated = { ...selectedCase, review_status: result.review_status }
      setSelectedCase(updated)
      setTestCases((current) => current.map((item) => (
        String(item.id) === String(updated.id)
          ? { ...item, review_status: updated.review_status }
          : item
      )))
    } catch (requestError) {
      if (requestError?.response?.status === 401) navigate('/login', { replace: true })
      else setDetailError(getApiErrorMessage(requestError, 'Test case status could not be updated.'))
    } finally {
      setUpdatingReviewStatus(false)
    }
  }

  const selectedGenerationRun = selectedCase
    ? selectedCase.generation_run
      || generationRuns.find((run) => (
        String(run.id ?? run.generation_run_id) === String(selectedCase.generation_run_id)
      ))
    : null

  const evaluateRun = async (runId) => {
    setEvaluatingRunId(runId)
    setError('')
    try {
      const evaluation = await evaluateProjectTestCaseGenerationRun(
        Number(projectId),
        runId,
      )
      setRunEvaluations((current) => ({ ...current, [runId]: evaluation }))
    } catch (requestError) {
      if (requestError?.response?.status === 401) navigate('/login', { replace: true })
      else setError(getApiErrorMessage(requestError, 'Generation quality evaluation failed.'))
    } finally {
      setEvaluatingRunId(null)
    }
  }

  return (
    <div className="workspace-page min-h-screen bg-[var(--background)] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="Test Cases" subtitle="Review generated cases and source evidence" />
        {error && <p role="alert" className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">{error}</p>}
        <Card title="Project" subtitle="Select a project to inspect its saved test cases">
          {loadingProjects ? (
            <p className="text-sm text-slate-400">Loading projects…</p>
          ) : projects.length === 0 ? (
            <p className="text-sm text-slate-400">Create a project to view test cases.</p>
          ) : (
            <select
              aria-label="Project"
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              className="w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-slate-100 sm:max-w-md"
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>{project.name}</option>
              ))}
            </select>
          )}
        </Card>

        <CollapsibleSection title="Generation history" subtitle="Review generation limits, retries, saved counts, and quality metrics">
          {generationRuns.length === 0 ? (
            <p className="text-sm text-slate-400">No generation runs are available for this project.</p>
          ) : (
            <div className="space-y-3">
              {generationRuns.map((run) => {
                const metrics = runEvaluations[run.id]?.quality_metrics
                return (
                  <article key={run.id} className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <h2 className="font-medium text-slate-100">Run #{run.id}</h2>
                        <p className="mt-1 text-xs text-slate-400">
                          {run.generation_status || run.status || 'unknown'} · {run.created_at ? new Date(run.created_at).toLocaleString() : 'date unavailable'}
                        </p>
                      </div>
                      <button
                        type="button"
                        disabled={evaluatingRunId !== null || !run.case_count}
                        onClick={() => evaluateRun(run.id)}
                        className="rounded-lg border border-sky-500/30 px-3 py-1.5 text-xs font-medium text-sky-200 hover:bg-sky-500/10 disabled:opacity-50"
                      >
                        {evaluatingRunId === run.id ? 'Evaluating…' : 'Evaluate quality'}
                      </button>
                    </div>
                    <dl className="mt-3 grid gap-2 sm:grid-cols-3">
                      {scalarRunDetails(run).map(([label, value]) => (
                        <div key={label} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
                          <dt className="text-xs capitalize text-slate-500">{label}</dt>
                          <dd className="mt-1 break-words text-sm text-slate-300">{String(value)}</dd>
                        </div>
                      ))}
                    </dl>
                    {metrics && (
                      <div className="mt-3 grid gap-3 text-xs text-slate-300 sm:grid-cols-3">
                        <p className="rounded-lg border border-slate-800 p-3">
                          Requirement coverage: {metrics.requirement_coverage.status}
                          {' · '}traceability {Math.round(metrics.requirement_coverage.case_traceability_ratio * 100)}%
                        </p>
                        <p className="rounded-lg border border-slate-800 p-3">
                          Scenario diversity: {Math.round(metrics.scenario_diversity.distinct_scenario_ratio * 100)}%
                          {' · '}categories {Math.round(metrics.scenario_diversity.requested_category_coverage * 100)}%
                        </p>
                        <p className="rounded-lg border border-slate-800 p-3">
                          Evidence accuracy: {metrics.evidence_accuracy.status}
                          {metrics.evidence_accuracy.score !== null && metrics.evidence_accuracy.score !== undefined
                            ? ` · ${Math.round(metrics.evidence_accuracy.score * 100)}%`
                            : ''}
                        </p>
                      </div>
                    )}
                  </article>
                )
              })}
            </div>
          )}
        </CollapsibleSection>

        <CollapsibleSection title="Saved test cases" subtitle="Open View details to inspect requirements and source evidence">
          {loadingCases ? (
            <p className="text-sm text-slate-400">Loading test cases…</p>
          ) : testCases.length === 0 ? (
            <p className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
              No saved test cases are available for this project.
            </p>
          ) : (
            <div className="space-y-4">
              {testCases.map((testCase) => (
                <article key={testCase.id} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="font-semibold text-slate-100">{testCase.title}</h2>
                      <p className="mt-1 text-xs text-slate-400">
                        Priority: {testCase.priority || 'Unavailable'}
                        {' · '}Severity: {testCase.severity || 'Unavailable'}
                        {' · '}Status: {reviewStatusLabel(testCase.review_status)}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-slate-500">Case #{testCase.id}</span>
                      <button
                        type="button"
                        onClick={() => openDetails(testCase)}
                        className="rounded-lg border border-sky-500/30 px-3 py-1.5 text-xs font-medium text-sky-200 hover:bg-sky-500/10 focus:outline-none focus:ring-2 focus:ring-sky-400"
                      >
                        View details
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </CollapsibleSection>

        {selectedCase && (
          <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/80 p-3 backdrop-blur-sm sm:p-6">
            <section
              role="dialog"
              aria-modal="true"
              aria-labelledby="test-case-detail-title"
              className="my-auto w-full max-w-3xl rounded-3xl border border-slate-700 bg-slate-900 p-5 shadow-2xl sm:p-7"
            >
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-800 pb-4">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-sky-300">Test case #{selectedCase.id}</p>
                  <h2 id="test-case-detail-title" className="mt-1 text-xl font-semibold text-slate-100">
                    {selectedCase.title}
                  </h2>
                  <p role="status" className="mt-1 text-xs text-slate-400">
                    Review status: {reviewStatusLabel(selectedCase.review_status)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {!editing && (
                    <>
                      <button
                        type="button"
                        disabled={loadingDetail || deleting || saving || updatingReviewStatus}
                        onClick={() => updateReviewStatus('approved')}
                        className="rounded-xl border border-emerald-500/30 px-3 py-2 text-sm text-emerald-200 hover:bg-emerald-500/10 disabled:opacity-50"
                      >
                        {updatingReviewStatus ? 'Updating…' : 'Approve'}
                      </button>
                      <button
                        type="button"
                        disabled={loadingDetail || deleting || saving || updatingReviewStatus}
                        onClick={() => updateReviewStatus('rejected')}
                        className="rounded-xl border border-rose-500/30 px-3 py-2 text-sm text-rose-200 hover:bg-rose-500/10 disabled:opacity-50"
                      >
                        Reject
                      </button>
                      <button
                        type="button"
                        disabled={loadingDetail || deleting || updatingReviewStatus}
                        onClick={() => setEditing(true)}
                        className="rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                      >
                        Edit
                      </button>
                    </>
                  )}
                  <button
                    type="button"
                    onClick={() => { setSelectedCase(null); setDraft(null); setEditing(false) }}
                    aria-label="Close test case details"
                    className="rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800"
                  >
                    Close
                  </button>
                </div>
              </div>

              {loadingDetail && <p className="mt-4 text-sm text-slate-400">Loading latest test case details…</p>}
              {detailError && (
                <p role="alert" className="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
                  {detailError}
                </p>
              )}

              {editing ? (
                <form onSubmit={saveChanges} className="mt-5 space-y-4">
                  <label className="block text-sm text-slate-300">
                    Title
                    <input
                      required
                      value={draft.title}
                      onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                      className={fieldClassName}
                    />
                  </label>
                  <label className="block text-sm text-slate-300">
                    Description
                    <textarea
                      rows={3}
                      value={draft.description}
                      onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                      className={fieldClassName}
                    />
                  </label>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {[
                      ['priority', 'Priority'],
                      ['severity', 'Severity'],
                      ['test_type', 'Type'],
                      ['category', 'Category'],
                    ].map(([field, label]) => (
                      <label key={field} className="block text-sm text-slate-300">
                        {label}
                      {field === 'test_type' ? (
                        <input
                          value={draft[field]}
                          onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
                          className={fieldClassName}
                        />
                      ) : (
                        <select
                          value={draft[field]}
                          onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
                          className={fieldClassName}
                        >
                          {(field === 'category'
                            ? ['positive', 'negative', 'boundary', 'edge']
                            : ['low', 'medium', 'high', 'critical']
                          ).map((value) => (
                            <option key={value} value={value}>{value}</option>
                          ))}
                        </select>
                      )}
                    </label>
                    ))}
                  </div>
                  <label className="block text-sm text-slate-300">
                    Preconditions
                    <textarea
                      rows={3}
                      value={draft.preconditions}
                      onChange={(event) => setDraft({ ...draft, preconditions: event.target.value })}
                      className={fieldClassName}
                    />
                  </label>
                  <fieldset className="space-y-3">
                    <legend className="text-sm font-medium text-slate-300">Test steps</legend>
                    {draft.steps.map((step, index) => (
                      <div key={`edit-step-${index}`} className="rounded-xl border border-slate-800 p-3">
                        <div className="mb-2 flex items-center justify-between">
                          <span className="text-xs text-slate-400">Step {index + 1}</span>
                          <button
                            type="button"
                            onClick={() => setDraft({
                              ...draft,
                              steps: draft.steps.filter((_, stepIndex) => stepIndex !== index),
                            })}
                            className="text-xs text-rose-300 hover:text-rose-200"
                          >
                            Remove step
                          </button>
                        </div>
                        <label className="block text-sm text-slate-300">
                          Action
                          <textarea
                            rows={2}
                            value={step.action}
                            onChange={(event) => setDraft({
                              ...draft,
                              steps: draft.steps.map((item, stepIndex) => (
                                stepIndex === index ? { ...item, action: event.target.value } : item
                              )),
                            })}
                            className={fieldClassName}
                          />
                        </label>
                        <label className="mt-3 block text-sm text-slate-300">
                          Expected result
                          <textarea
                            rows={2}
                            value={step.expected_result}
                            onChange={(event) => setDraft({
                              ...draft,
                              steps: draft.steps.map((item, stepIndex) => (
                                stepIndex === index ? { ...item, expected_result: event.target.value } : item
                              )),
                            })}
                            className={fieldClassName}
                          />
                        </label>
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() => setDraft({
                        ...draft,
                        steps: [...draft.steps, { action: '', expected_result: '' }],
                      })}
                      className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800"
                    >
                      Add step
                    </button>
                  </fieldset>
                  <label className="block text-sm text-slate-300">
                    Overall expected result
                    <textarea
                      rows={3}
                      value={draft.expected_result}
                      onChange={(event) => setDraft({ ...draft, expected_result: event.target.value })}
                      className={fieldClassName}
                    />
                  </label>
                  <label className="block text-sm text-slate-300">
                    Requirement keys <span className="text-xs text-slate-500">(one per line or comma-separated)</span>
                    <textarea
                      rows={3}
                      value={draft.requirement_keys}
                      onChange={(event) => setDraft({ ...draft, requirement_keys: event.target.value })}
                      className={fieldClassName}
                    />
                  </label>
                  <div className="flex flex-wrap justify-between gap-3 border-t border-slate-800 pt-4">
                    <button
                      type="button"
                      onClick={deleteSelectedCase}
                      disabled={saving || deleting || loadingDetail}
                      className="rounded-xl border border-rose-500/30 px-4 py-2 text-sm text-rose-200 hover:bg-rose-500/10 disabled:opacity-50"
                    >
                      {deleting ? 'Deleting…' : 'Delete test case'}
                    </button>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => { setDraft(editableFields(selectedCase)); setEditing(false); setDetailError('') }}
                        disabled={saving || deleting}
                        className="rounded-xl border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        disabled={saving || deleting || loadingDetail}
                        className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-sky-400 disabled:opacity-50"
                      >
                        {saving ? 'Saving…' : 'Save changes'}
                      </button>
                    </div>
                  </div>
                </form>
              ) : (
                <div className="mt-5 space-y-5">
                  <div className="grid gap-3 sm:grid-cols-2">
                    {[
                      ['Priority', selectedCase.priority],
                      ['Severity', selectedCase.severity],
                      ['Type', selectedCase.test_type],
                      ['Category', selectedCase.category],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</h3>
                        <p className="mt-1 text-sm capitalize text-slate-200">{value || 'Not specified'}</p>
                      </div>
                    ))}
                  </div>
                  {selectedCase.description && (
                    <section>
                      <h3 className="text-sm font-semibold text-slate-200">Description</h3>
                      <p className="mt-1 whitespace-pre-wrap text-sm text-slate-300">{selectedCase.description}</p>
                    </section>
                  )}
                  <section>
                    <h3 className="text-sm font-semibold text-slate-200">Preconditions</h3>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-slate-300">
                      {selectedCase.preconditions || 'None specified.'}
                    </p>
                  </section>
                  <section>
                    <h3 className="text-sm font-semibold text-slate-200">Test steps</h3>
                    {Array.isArray(selectedCase.steps) && selectedCase.steps.length > 0 ? (
                      <ol className="mt-2 list-decimal space-y-3 pl-5">
                        {selectedCase.steps.map((step, index) => (
                          <li key={`detail-step-${index}`} className="pl-1 text-sm text-slate-300">
                            <p className="whitespace-pre-wrap">{step.action || 'No action specified.'}</p>
                            {step.expected_result && (
                              <p className="mt-1 whitespace-pre-wrap text-slate-400">Expected: {step.expected_result}</p>
                            )}
                          </li>
                        ))}
                      </ol>
                    ) : <p className="mt-1 text-sm text-slate-400">No steps specified.</p>}
                  </section>
                  {selectedCase.expected_result && (
                    <section>
                      <h3 className="text-sm font-semibold text-slate-200">Overall expected result</h3>
                      <p className="mt-1 whitespace-pre-wrap text-sm text-slate-300">{selectedCase.expected_result}</p>
                    </section>
                  )}
                  <section>
                    <h3 className="text-sm font-semibold text-slate-200">Requirement references</h3>
                    {Array.isArray(selectedCase.requirements) && selectedCase.requirements.length ? (
                      <ul className="mt-2 flex flex-wrap gap-2">
                        {selectedCase.requirements.map((requirement) => {
                          return (
                          <li key={requirement.id} className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1 text-xs text-slate-300">
                            {requirement.requirement_key}
                          </li>
                          )
                        })}
                      </ul>
                    ) : <p className="mt-1 text-sm text-slate-400">No requirement references linked.</p>}
                  </section>
                  <section>
                    <h3 className="text-sm font-semibold text-slate-200">Generation run</h3>
                    {selectedCase.generation_run_id != null && (
                      <p className="mt-1 text-xs text-slate-500">Run #{selectedCase.generation_run_id}</p>
                    )}
                    {selectedGenerationRun ? (
                      scalarRunDetails(selectedGenerationRun).length > 0 ? (
                        <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                          {scalarRunDetails(selectedGenerationRun).map(([label, value]) => (
                            <div key={label} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3">
                              <dt className="text-xs capitalize text-slate-500">{label}</dt>
                              <dd className="mt-1 break-words text-sm text-slate-300">{String(value)}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : <p className="mt-1 text-sm text-slate-400">Run details are available, but contain no summary stats.</p>
                    ) : <p className="mt-1 text-sm text-slate-400">No generation run details available.</p>}
                  </section>
                  <section>
                    <h3 className="text-sm font-semibold text-slate-200">Source evidence</h3>
                    {Array.isArray(selectedCase.evidence) && selectedCase.evidence.length > 0 ? (
                      <div className="mt-2 space-y-3">
                        {selectedCase.evidence.map((source, index) => {
                          const location = sourceLocation(source.source_metadata)
                          return (
                            <div key={`${source.document_id}-${source.chunk_id}-${index}`} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                              <p className="break-all text-sm font-medium text-sky-200">{source.document_name || `Document #${source.document_id}`}</p>
                              <p className="mt-1 text-xs text-slate-500">
                                {source.document_id != null && `Document #${source.document_id}`}
                                {source.chunk_id != null && ` · Chunk #${source.chunk_id}`}
                                {source.source_type ? ` · ${source.source_type.replaceAll('_', ' ')}` : ''}
                                {location ? ` · ${location}` : ''}
                              </p>
                              <blockquote className="mt-2 whitespace-pre-wrap border-l-2 border-sky-500/40 pl-3 text-sm text-slate-300">
                                {source.excerpt || 'Source excerpt is unavailable.'}
                              </blockquote>
                            </div>
                          )
                        })}
                      </div>
                    ) : <p className="mt-1 text-sm text-slate-400">No verified source evidence is available.</p>}
                  </section>
                  <div className="flex justify-end border-t border-slate-800 pt-4">
                    <button
                      type="button"
                      onClick={deleteSelectedCase}
                      disabled={deleting || loadingDetail}
                      className="rounded-xl border border-rose-500/30 px-4 py-2 text-sm text-rose-200 hover:bg-rose-500/10 disabled:opacity-50"
                    >
                      {deleting ? 'Deleting…' : 'Delete test case'}
                    </button>
                  </div>
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  )
}

export default TestCasesPage
