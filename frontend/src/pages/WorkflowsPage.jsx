import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Play, RotateCw } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import { getApiErrorMessage } from '../api/client'
import { fetchProjects } from '../api/projects'
import {
  fetchWorkflow,
  fetchWorkflows,
  resumeWorkflow,
  startWorkflow,
} from '../api/workflows'
import {
  getTaskStatus,
  isCurrentWorkflowProject,
  isTaskTerminal,
  isWorkflowActive,
  safeTaskDiagnostic,
  safeWorkflowOutput,
  safeWorkflowText,
  statusPresentation,
  testCaseEvidenceSources,
  workflowGeneratedCases,
  workflowTestCasesPageUrl,
} from './workflowPresentation'
import { workflowStartValidationError } from './workflowValidation'

const workflowTypes = [
  { value: 'full_qa_workflow', label: 'Full QA workflow' },
  { value: 'test_generation', label: 'Test generation' },
  { value: 'bug_analysis', label: 'Bug analysis' },
  { value: 'change_risk_analysis', label: 'Change risk analysis' },
  { value: 'quality_insights', label: 'Quality insights' },
]

function StatusBadge({ status }) {
  const presentation = statusPresentation(status)
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs capitalize ${presentation.className}`}>
      {presentation.label}
    </span>
  )
}

function formatTimestamp(value) {
  if (!value) return '—'
  const timestamp = new Date(value)
  return Number.isNaN(timestamp.getTime()) ? '—' : timestamp.toLocaleString()
}

function formatDuration(startedAt, completedAt) {
  if (!startedAt) return '—'
  const start = Date.parse(startedAt)
  const end = completedAt ? Date.parse(completedAt) : Date.now()
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return '—'
  const seconds = Math.floor((end - start) / 1000)
  return seconds < 60
    ? `${seconds}s`
    : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function evidenceLocation(metadata = {}) {
  const source = metadata && typeof metadata === 'object' ? metadata : {}
  const location = source.source_location && typeof source.source_location === 'object'
    ? source.source_location
    : source
  const parts = []
  if (Number.isInteger(location.page_number)) parts.push(`Page ${location.page_number}`)
  if (Array.isArray(location.page_numbers) && location.page_numbers.length) {
    parts.push(`Pages ${location.page_numbers.join(', ')}`)
  }
  if (typeof location.section === 'string' && location.section) parts.push(`Section ${location.section}`)
  if (typeof location.sheet_name === 'string' && location.sheet_name) parts.push(`Sheet ${location.sheet_name}`)
  for (const [startKey, endKey, label] of [
    ['line_start', 'line_end', 'Line'],
    ['row_start', 'row_end', 'Row'],
  ]) {
    const start = location[startKey]
    const end = location[endKey]
    if (Number.isInteger(start) && Number.isInteger(end)) {
      parts.push(start === end ? `${label} ${start}` : `${label}s ${start}–${end}`)
    } else if (Number.isInteger(start ?? end)) {
      parts.push(`${label} ${start ?? end}`)
    }
  }
  return parts.map((part) => safeWorkflowText(part)).filter(Boolean).join(' · ')
}

function TaskHistory({ workflow }) {
  const tasks = workflow.tasks || []
  const taskNames = new Map(tasks.map((task) => [task.id, task.task_type.replaceAll('_', ' ')]))
  const terminalCount = tasks.filter((task) => isTaskTerminal(task.status)).length
  const runningAgents = tasks.filter((task) => task.status === 'running')

  return (
    <section aria-label="Task execution history" className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-semibold text-slate-200">Execution progress</h4>
          <span className="text-sm text-slate-400">
            {terminalCount} of {tasks.length} tasks reached a terminal state
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Progress counts completed, partial, skipped, failed, and blocked task records.
          Generation attempts: {workflow.generation_attempt_count ?? 0}.
        </p>
        {runningAgents.length > 0 && (
          <p className="mt-3 text-sm text-sky-200">
            Running concurrently: {runningAgents.map((task) => task.agent_name.replaceAll('_', ' ')).join(', ')}
          </p>
        )}
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        {tasks.map((task) => {
          const output = task.output_data || {}
          const structured = output.structured_data || {}
          const evidence = Array.isArray(output.evidence_references) ? output.evidence_references : []
          const taskDiagnostic = safeTaskDiagnostic(task.error_details)
          return (
            <article key={task.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h5 className="font-medium text-slate-100">{task.agent_name.replaceAll('_', ' ')}</h5>
                  <p className="mt-1 text-xs capitalize text-slate-500">
                    {task.task_type.replaceAll('_', ' ')} · {task.input_summary || 'Task-specific inputs'}
                  </p>
                </div>
                <StatusBadge status={getTaskStatus(task)} />
              </div>
              <dl className="mt-3 grid gap-x-4 gap-y-2 text-xs text-slate-400 sm:grid-cols-2">
                <div><dt className="inline text-slate-500">Started: </dt><dd className="inline">{formatTimestamp(task.started_at)}</dd></div>
                <div><dt className="inline text-slate-500">Finished: </dt><dd className="inline">{formatTimestamp(task.completed_at)}</dd></div>
                <div><dt className="inline text-slate-500">Duration: </dt><dd className="inline">{formatDuration(task.started_at, task.completed_at)}</dd></div>
                <div><dt className="inline text-slate-500">Task attempts: </dt><dd className="inline">{task.attempt_count ?? 0}</dd></div>
                <div className="sm:col-span-2">
                  <dt className="inline text-slate-500">Dependencies: </dt>
                  <dd className="inline">
                    {(task.depends_on_task_ids || []).length
                      ? task.depends_on_task_ids.map((id) => taskNames.get(id) || `task ${id}`).join(', ')
                      : 'None'}
                  </dd>
                </div>
              </dl>
              {(task.attempts || []).length > 0 && (
                <details className="mt-3 border-t border-slate-800 pt-3">
                  <summary className="cursor-pointer text-xs font-medium text-slate-300">
                    Attempt history ({task.attempts.length})
                  </summary>
                  <ol className="mt-2 space-y-2">
                    {task.attempts.map((attempt) => {
                      const diagnostic = safeTaskDiagnostic(attempt.error_details)
                      return (
                      <li key={`${task.id}-${attempt.task_attempt_number ?? attempt.attempt_number}`} className="space-y-2 rounded-lg bg-slate-900/60 p-2 text-xs text-slate-400">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span>
                            Task attempt {attempt.task_attempt_number ?? attempt.attempt_number}
                            {attempt.generation_attempt_number != null
                              ? ` · Generation attempt ${attempt.generation_attempt_number}`
                              : ''}
                            {' · '}{formatTimestamp(attempt.started_at)}
                            {attempt.completed_at
                              ? ` – ${formatTimestamp(attempt.completed_at)}`
                              : ''}
                          </span>
                          <StatusBadge status={attempt.status} />
                        </div>
                        {diagnostic && (
                          <p role="status" className="text-rose-200">
                            {diagnostic.code
                              ? `${diagnostic.code}: `
                              : ''}
                            {diagnostic.message}
                          </p>
                        )}
                        {attempt.output_data && (
                          <details>
                            <summary className="cursor-pointer text-slate-300">Attempt output</summary>
                            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-2">
                              {JSON.stringify(safeWorkflowOutput(attempt.output_data), null, 2)}
                            </pre>
                          </details>
                        )}
                      </li>
                    )})}
                  </ol>
                </details>
              )}
              {taskDiagnostic && (
                <p role="status" className="mt-3 rounded-lg bg-rose-500/10 p-2 text-xs text-rose-200">
                  {taskDiagnostic.code ? `${taskDiagnostic.code}: ` : ''}{taskDiagnostic.message}
                </p>
              )}
              {Object.keys(structured).length > 0 && (
                <details className="mt-3 border-t border-slate-800 pt-3">
                  <summary className="cursor-pointer text-xs font-medium text-slate-300">Output summary</summary>
                  <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-xs text-slate-400">
                    {JSON.stringify(safeWorkflowOutput(structured), null, 2)}
                  </pre>
                </details>
              )}
              {evidence.length > 0 && (
                <div className="mt-3 border-t border-slate-800 pt-3">
                  <p className="text-xs font-medium text-slate-300">Evidence references</p>
                  <ul className="mt-1 space-y-1 text-xs text-slate-500">
                    {evidence.map((source, index) => (
                      <li key={`${source.document_id}-${source.chunk_id}-${index}`}>
                        {source.document_name || (source.document_id ? `Document ${source.document_id}` : 'Source document')}
                        {' · '}chunk {source.chunk_id ?? '—'}
                        {source.source_type ? ` · ${source.source_type.replaceAll('_', ' ')}` : ''}
                      </li>
                    ))}
                  </ul>
                  {evidence.some((source) => source.excerpt) && (
                    <details className="mt-2">
                      <summary className="cursor-pointer text-xs text-slate-400">View cited excerpts</summary>
                      <ul className="mt-2 space-y-2 text-xs text-slate-500">
                        {evidence.filter((source) => source.excerpt).map((source, index) => (
                          <li key={`${source.chunk_id}-${index}`} className="rounded bg-slate-900 p-2">
                            {safeWorkflowText(source.excerpt)}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              )}
            </article>
          )
        })}
      </div>
    </section>
  )
}

function OutputSummary({ workflow }) {
  const results = workflow.final_output?.results || {}
  const generation = results.test_generation
  const testCases = workflowGeneratedCases(workflow)
  const requirements = results.requirements_analysis?.structured_data?.requirements || []
  const bugData = results.bug_analysis?.structured_data || {}
  const riskData = results.change_risk_analysis?.structured_data || {}
  const qualityData = results.quality_insights?.structured_data || {}
  const testAnalysis = results.test_analysis?.structured_data?.analysis
  const reviewFindings = generation?.review?.findings || []
  const missingScenarios = generation?.review?.missing_scenarios || []
  const regenerationFeedback = generation?.review?.actionable_feedback || []
  const requirementEvidence = results.requirements_analysis?.structured_data?.evidence || []
  const reviews = generation?.review?.reviews || []
  const agentMessages = Object.entries(results).flatMap(([taskType, result]) => {
    const data = result?.structured_data || {}
    return [
      ...(Array.isArray(data.warnings) ? data.warnings.map((message) => ({
        taskType,
        message: safeWorkflowText(message, 'A warning was reported.'),
        kind: 'warning',
      })) : []),
      ...(Array.isArray(result?.errors) ? result.errors.map((item) => {
        const diagnostic = safeTaskDiagnostic(
          typeof item === 'string' ? { message: item } : item,
        )
        return {
          taskType,
          message: diagnostic
            ? [diagnostic.code, diagnostic.message].filter(Boolean).join(': ')
            : 'A task error was reported.',
          kind: 'error',
        }
      }) : []),
    ]
  })

  return (
    <div className="space-y-4">
      {workflow.error_summary && (
        <p role="alert" className="flex gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
          <AlertCircle size={18} className="shrink-0" />
          {safeWorkflowText(workflow.error_summary, 'The workflow did not complete successfully.')}
        </p>
      )}
      {requirements.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200">Extracted requirements</h4>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">
            {requirements.map((item, index) => (
              <li key={`${item.id || 'requirement'}-${index}`}>
                {item.id ? `${safeWorkflowText(item.id)}: ` : ''}
                {safeWorkflowText(item.description)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {requirementEvidence.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200">Requirement sources</h4>
          <ul className="mt-2 space-y-1 text-xs text-slate-400">
            {requirementEvidence.map((source) => (
              <li key={`${source.document_id}-${source.chunk_id}`}>
                {safeWorkflowText(source.document_name, 'Source document')}
                {' · '}document {source.document_id} · chunk {source.chunk_id}
              </li>
            ))}
          </ul>
        </div>
      )}
      {bugData.reason && <p className="text-sm text-slate-400">{safeWorkflowText(bugData.reason)}</p>}
      {bugData.bugs?.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200">Bug findings</h4>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">
            {bugData.bugs.map((bug, index) => (
              <li key={bug.id || index}>
                {bug.description
                  ? safeWorkflowText(bug.description)
                  : JSON.stringify(safeWorkflowOutput(bug))}
              </li>
            ))}
          </ul>
        </div>
      )}
      {riskData.risk_level && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200">Change risk</h4>
          <p className="mt-1 text-sm text-slate-300">
            {riskData.risk_level} risk · score {riskData.risk_score ?? 'unavailable'}
          </p>
          {riskData.reasoning && <p className="mt-1 text-sm text-slate-400">{safeWorkflowText(riskData.reasoning)}</p>}
        </div>
      )}
      {qualityData.insights && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200">Quality insights</h4>
          <pre className="mt-2 overflow-auto rounded-xl bg-slate-950 p-3 text-xs text-slate-400">
            {typeof qualityData.insights === 'string'
              ? safeWorkflowText(qualityData.insights)
              : JSON.stringify(safeWorkflowOutput(qualityData.insights), null, 2)}
          </pre>
        </div>
      )}
      {testAnalysis && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200">Test execution analysis</h4>
          <pre className="mt-2 overflow-auto rounded-xl bg-slate-950 p-3 text-xs text-slate-400">
            {typeof testAnalysis === 'string'
              ? safeWorkflowText(testAnalysis)
              : JSON.stringify(safeWorkflowOutput(testAnalysis), null, 2)}
          </pre>
        </div>
      )}
      {generation?.validation && (
        <div>
          <p className="text-sm text-slate-300">
            Deterministic validation: {generation.validation.valid ? 'passed' : 'needs attention'}
          </p>
          {generation.validation.findings?.length > 0 && (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-200">
              {generation.validation.findings.map((finding, index) => (
                <li key={`${finding.check || 'validation'}-${index}`}>
                  {finding.severity ? `${safeWorkflowText(finding.severity)}: ` : ''}
                  {finding.message
                    ? safeWorkflowText(finding.message)
                    : JSON.stringify(safeWorkflowOutput(finding))}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {generation?.review?.workflow_approval && (
        <p className="text-sm text-slate-300">
          {generation.review.workflow_approval === 'needs_revision'
            ? 'Reviewer outcome: needs revision. Address the findings before requesting human approval.'
            : `Reviewer decision: ${generation.review.workflow_approval.replaceAll('_', ' ')}. Human approval is still required.`}
        </p>
      )}
      {reviewFindings.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200">Reviewer feedback</h4>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">
            {reviewFindings.map((finding, index) => (
              <li key={`${finding.check || 'review'}-${index}`}>
              {finding.severity ? `${safeWorkflowText(finding.severity)}: ` : ''}
              {finding.message
                ? safeWorkflowText(finding.message)
                : JSON.stringify(safeWorkflowOutput(finding))}
              </li>
            ))}
          </ul>
        </div>
      )}
      {missingScenarios.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200">Missing scenarios</h4>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">
            {missingScenarios.map((scenario, index) => (
              <li key={`${scenario.check || 'scenario'}-${index}`}>
                {scenario.message
                  ? safeWorkflowText(scenario.message)
                  : JSON.stringify(safeWorkflowOutput(scenario))}
              </li>
            ))}
          </ul>
        </div>
      )}
      {regenerationFeedback.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200">Regeneration feedback</h4>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">
            {regenerationFeedback.map((message, index) => (
              <li key={`${index}-${message}`}>{safeWorkflowText(message)}</li>
            ))}
          </ul>
        </div>
      )}
      {reviews.some((review) => review.structured_data?.checks) && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200">Review observations</h4>
          <ul className="mt-2 space-y-1 text-sm text-slate-400">
            {reviews.map((review) => {
              const evaluation = review.structured_data?.checks?.semantic_evaluation
              if (!evaluation) return null
              return (
                <li key={review.structured_data.test_case_id}>
                  Case {review.structured_data.test_case_id}: semantic status {evaluation.status || 'unavailable'};
                  reference {review.structured_data.evidence_quality?.reference_status || 'unknown'};
                  requirement coverage {evaluation.requirement_coverage || 'unclear'}.
                  {evaluation.reason ? ` ${safeWorkflowText(evaluation.reason)}` : ''}
                </li>
              )
            })}
          </ul>
        </div>
      )}
      {agentMessages.length > 0 && (
        <div className="space-y-2">
          {agentMessages.map((item, index) => (
            <p
              key={`${item.taskType}-${index}`}
              className={`rounded-lg px-3 py-2 text-sm ${item.kind === 'error' ? 'bg-rose-500/10 text-rose-200' : 'bg-amber-500/10 text-amber-200'}`}
            >
              {item.taskType.replaceAll('_', ' ')}: {item.message}
            </p>
          ))}
        </div>
      )}
      {testCases.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h4 className="text-sm font-semibold text-slate-200">Generated test cases</h4>
            <Link
              to={workflowTestCasesPageUrl(workflow.project_id)}
              className="text-sm font-medium text-sky-300 underline decoration-sky-500/50 underline-offset-4 hover:text-sky-200"
            >
              Review in Test Cases
            </Link>
          </div>
          {testCases.map((testCase) => (
            <article key={testCase.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex flex-wrap justify-between gap-2">
                <h5 className="font-medium text-slate-100">{safeWorkflowText(testCase.title, 'Untitled test case')}</h5>
                <span className="text-xs capitalize text-slate-400">
                  {[
                    testCase.test_type,
                    testCase.category,
                    testCase.priority,
                    testCase.severity ? `severity ${testCase.severity}` : null,
                    testCase.review_status ? `review ${testCase.review_status}` : null,
                  ].filter(Boolean).join(' · ')}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-300">{safeWorkflowText(testCase.description)}</p>
              {testCase.preconditions && (
                <p className="mt-3 text-sm text-slate-400">
                  <span className="font-medium text-slate-300">Preconditions: </span>
                  {safeWorkflowText(testCase.preconditions)}
                </p>
              )}
              {Array.isArray(testCase.steps) && testCase.steps.length > 0 && (
                <div className="mt-3">
                  <h6 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Steps</h6>
                  <ol className="mt-2 list-decimal space-y-2 pl-5 text-sm text-slate-300">
                    {testCase.steps.map((step, index) => (
                      <li key={`${testCase.id}-step-${index}`}>
                        <p>{safeWorkflowText(step.action)}</p>
                        {step.expected_result && (
                          <p className="mt-1 text-slate-400">
                            Expected: {safeWorkflowText(step.expected_result)}
                          </p>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {testCase.expected_result && (
                <p className="mt-3 text-sm text-slate-300">
                  <span className="font-medium">Expected result: </span>{safeWorkflowText(testCase.expected_result)}
                </p>
              )}
              {(testCase.requirements?.length > 0 || testCase.requirement_keys?.length > 0) && (
                <div className="mt-3">
                  <h6 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Linked requirements</h6>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-300">
                    {(testCase.requirements || []).map((requirement) => (
                      <li key={`${testCase.id}-${requirement.id ?? requirement.requirement_key}`}>
                        {requirement.requirement_key
                          ? `${safeWorkflowText(requirement.requirement_key)}: `
                          : ''}
                        {safeWorkflowText(requirement.description, 'Requirement linked')}
                      </li>
                    ))}
                    {(!testCase.requirements || testCase.requirements.length === 0)
                      && testCase.requirement_keys.map((key) => (
                        <li key={`${testCase.id}-${key}`}>{safeWorkflowText(key)}</li>
                      ))}
                  </ul>
                </div>
              )}
              {testCaseEvidenceSources(testCase).length > 0 && (
                <div className="mt-3 space-y-2 border-t border-slate-800 pt-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Cited source evidence</p>
                  {testCaseEvidenceSources(testCase).map((source, index) => (
                    <div key={`${testCase.id}-${source.chunk_id ?? 'unknown'}-${index}`} className="text-xs text-slate-400">
                      <p>
                        {safeWorkflowText(
                          source.document_name || (source.document_id ? `Document ${source.document_id}` : 'Source details unavailable'),
                        )}
                        {' · '}chunk {source.chunk_id ?? '—'}
                        {source.source_type ? ` · ${source.source_type.replaceAll('_', ' ')}` : ''}
                        {evidenceLocation(source.source_metadata)
                          ? ` · ${evidenceLocation(source.source_metadata)}`
                          : ''}
                      </p>
                      {source.sourceUnavailable && (
                        <p className="mt-1 text-amber-300">
                          Only the cited chunk ID is available; source name and excerpt were not included.
                        </p>
                      )}
                      {source.excerpt && (
                        <details className="mt-1">
                          <summary className="cursor-pointer text-slate-400">View cited excerpt</summary>
                          <p className="mt-1 whitespace-pre-wrap rounded bg-slate-900 p-2 text-slate-500">
                            {safeWorkflowText(source.excerpt)}
                          </p>
                        </details>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  )
}

const WorkflowsPage = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedProjectId = searchParams.get('project_id')
  const initialProjectIdRef = useRef(
    requestedProjectId || localStorage.getItem('testnova-active-project-id') || '',
  )
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [workflows, setWorkflows] = useState([])
  const [workflowsProjectId, setWorkflowsProjectId] = useState('')
  const [workflowDetails, setWorkflowDetails] = useState({})
  const [expandedWorkflows, setExpandedWorkflows] = useState({})
  const workflowDetailsRef = useRef({})
  const expandedWorkflowsRef = useRef({})
  const refreshingRef = useRef(new Map())
  const selectedProjectRef = useRef(projectId)
  selectedProjectRef.current = projectId
  const submittingRef = useRef(false)
  const [workflowType, setWorkflowType] = useState('full_qa_workflow')
  const [requirementsPrompt, setRequirementsPrompt] = useState('')
  const [maxCases, setMaxCases] = useState(5)
  const [categories, setCategories] = useState(['positive', 'negative', 'boundary', 'edge'])
  const [changeSummary, setChangeSummary] = useState('')
  const [changeSummaryError, setChangeSummaryError] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadingWorkflows, setLoadingWorkflows] = useState(false)
  const [loadingDetails, setLoadingDetails] = useState({})
  const [projectsError, setProjectsError] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [resumingId, setResumingId] = useState(null)
  const [error, setError] = useState('')

  const hasActiveWorkflow = useMemo(
    () => workflows.some((item) => isWorkflowActive(item.status)),
    [workflows],
  )

  const loadDetails = useCallback(async (requestedProjectId, workflowId, showLoading = false) => {
    if (!requestedProjectId) return
    const detailsKey = `${requestedProjectId}:${workflowId}`
    if (showLoading) {
      setLoadingDetails((current) => ({ ...current, [detailsKey]: true }))
    }
    try {
      const workflow = await fetchWorkflow(Number(requestedProjectId), workflowId)
      if (!isCurrentWorkflowProject(requestedProjectId, selectedProjectRef.current)) return
      workflowDetailsRef.current = {
        ...workflowDetailsRef.current,
        [detailsKey]: workflow,
      }
      setWorkflowDetails(workflowDetailsRef.current)
      if (expandedWorkflowsRef.current[detailsKey] === undefined) {
        expandedWorkflowsRef.current = {
          ...expandedWorkflowsRef.current,
          [detailsKey]: true,
        }
        setExpandedWorkflows(expandedWorkflowsRef.current)
      }
    } finally {
      if (showLoading && isCurrentWorkflowProject(requestedProjectId, selectedProjectRef.current)) {
        setLoadingDetails((current) => ({ ...current, [detailsKey]: false }))
      }
    }
  }, [])

  const refresh = useCallback(async () => {
    const requestedProjectId = projectId
    if (!requestedProjectId) return
    const existingRequest = refreshingRef.current.get(requestedProjectId)
    if (existingRequest) return existingRequest

    const request = (async () => {
      const items = await fetchWorkflows(Number(requestedProjectId))
      if (!isCurrentWorkflowProject(requestedProjectId, selectedProjectRef.current)) return
      setWorkflows(items)
      setWorkflowsProjectId(requestedProjectId)
      await Promise.all(items
        .filter((item) => {
          const detailsKey = `${requestedProjectId}:${item.id}`
          const isActive = isWorkflowActive(item.status)
          const isExpanded = expandedWorkflowsRef.current[detailsKey] === true
          const details = workflowDetailsRef.current[detailsKey]
          return isActive || (isExpanded && details?.status !== item.status)
        })
        .map((item) => loadDetails(requestedProjectId, item.id)))
    })()
    refreshingRef.current.set(requestedProjectId, request)
    try {
      await request
    } finally {
      if (refreshingRef.current.get(requestedProjectId) === request) {
        refreshingRef.current.delete(requestedProjectId)
      }
    }
  }, [projectId, loadDetails])

  const loadProjects = useCallback(async () => {
    setLoading(true)
    setProjectsError('')
    try {
      const items = await fetchProjects()
      setProjects(items)
      setProjectId((current) => {
        const requestedProject = items.find((item) => String(item.id) === initialProjectIdRef.current)
        const storedProject = items.find(
          (item) => String(item.id) === localStorage.getItem('testnova-active-project-id'),
        )
        return current || String(requestedProject?.id ?? storedProject?.id ?? items[0]?.id ?? '')
      })
      setProjectsError('')
      setError('')
    } catch (requestError) {
      const message = getApiErrorMessage(requestError, 'Projects could not be loaded.')
      setProjectsError(message)
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!projectId) return
    localStorage.setItem('testnova-active-project-id', projectId)
    if (searchParams.get('project_id') === projectId) return
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('project_id', projectId)
    setSearchParams(nextParams, { replace: true })
  }, [projectId, searchParams, setSearchParams])

  useEffect(() => {
    loadProjects()
  }, [loadProjects])

  useEffect(() => {
    if (!projectId) {
      setWorkflows([])
      setWorkflowDetails({})
      setExpandedWorkflows({})
      setLoadingDetails({})
      workflowDetailsRef.current = {}
      expandedWorkflowsRef.current = {}
      setWorkflowsProjectId('')
      setLoadingWorkflows(false)
      setHistoryError('')
      return undefined
    }
    let active = true
    setWorkflows([])
    setWorkflowDetails({})
    setExpandedWorkflows({})
    setLoadingDetails({})
    workflowDetailsRef.current = {}
    expandedWorkflowsRef.current = {}
    setLoadingWorkflows(true)
    setHistoryError('')
    setError('')
    const load = async () => {
      try {
        await refresh()
        if (active && isCurrentWorkflowProject(projectId, selectedProjectRef.current)) {
          setHistoryError('')
          setError('')
        }
      } catch (requestError) {
        if (active && isCurrentWorkflowProject(projectId, selectedProjectRef.current)) {
          const message = getApiErrorMessage(requestError, 'Workflow history could not be loaded.')
          setHistoryError(message)
          setError(message)
        }
      } finally {
        if (active) setLoadingWorkflows(false)
      }
    }
    load()
    return () => { active = false }
  }, [projectId, refresh])

  useEffect(() => {
    if (!projectId || !hasActiveWorkflow) return undefined
    const timer = window.setInterval(() => {
      refresh().catch((requestError) => {
        if (isCurrentWorkflowProject(projectId, selectedProjectRef.current)) {
          const message = getApiErrorMessage(requestError, 'Workflow history could not be refreshed.')
          setHistoryError(message)
          setError(message)
        }
      })
    }, 4000)
    return () => window.clearInterval(timer)
  }, [projectId, hasActiveWorkflow, refresh])

  const handleStart = async (event) => {
    event.preventDefault()
    const validationError = workflowStartValidationError(workflowType, changeSummary)
    setChangeSummaryError(validationError)
    if (validationError) return
    if (!projectId || submittingRef.current || hasActiveWorkflow) return
    const requestedProjectId = projectId
    submittingRef.current = true
    setSubmitting(true)
    setError('')
    try {
      const payload = {
        workflow_type: workflowType,
        max_cases: maxCases,
        categories,
      }
      if (requirementsPrompt.trim()) payload.requirements_prompt = requirementsPrompt.trim()
      if (workflowType === 'change_risk_analysis' || changeSummary.trim()) {
        if (changeSummary.trim()) payload.change_summary = changeSummary.trim()
      }
      const created = await startWorkflow(Number(requestedProjectId), payload)
      if (!isCurrentWorkflowProject(requestedProjectId, selectedProjectRef.current)) return
      const detailsKey = `${requestedProjectId}:${created.id}`
      workflowDetailsRef.current = { ...workflowDetailsRef.current, [detailsKey]: created }
      expandedWorkflowsRef.current = { ...expandedWorkflowsRef.current, [detailsKey]: true }
      setWorkflowDetails(workflowDetailsRef.current)
      setExpandedWorkflows(expandedWorkflowsRef.current)
      setWorkflows((current) => [created, ...current.filter((item) => item.id !== created.id)])
      await refresh()
    } catch (requestError) {
      if (isCurrentWorkflowProject(requestedProjectId, selectedProjectRef.current)) {
        setError(getApiErrorMessage(requestError, 'Workflow could not be started.'))
      }
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  const handleResume = async (workflowId) => {
    if (resumingId !== null) return
    const requestedProjectId = projectId
    setResumingId(workflowId)
    setError('')
    try {
      await resumeWorkflow(Number(requestedProjectId), workflowId)
      await refresh()
      // A resumed workflow can finish in the same terminal status it had before
      // resumption. The history refresh only reloads details when status changes,
      // so explicitly fetch this run to show its latest attempts and outputs.
      await loadDetails(requestedProjectId, workflowId, true)
    } catch (requestError) {
      if (isCurrentWorkflowProject(requestedProjectId, selectedProjectRef.current)) {
        setError(getApiErrorMessage(requestError, 'Workflow could not be resumed.'))
      }
    } finally {
      setResumingId(null)
    }
  }

  const handleRetry = () => {
    setError('')
    if (!projectId) {
      loadProjects()
      return
    }
    setHistoryError('')
    refresh().catch((requestError) => {
      if (isCurrentWorkflowProject(projectId, selectedProjectRef.current)) {
        const message = getApiErrorMessage(requestError, 'Workflow data could not be loaded.')
        setHistoryError(message)
        setError(message)
      }
    })
  }

  return (
    <div className="workspace-page min-h-screen bg-[var(--background)] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="QA Workflows" subtitle="Run evidence-grounded analysis and review agent progress" />
        {error && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
            <span>{error}</span>
            <button
              type="button"
              onClick={handleRetry}
              className="rounded-lg border border-rose-300/30 px-3 py-1.5 text-xs font-medium hover:bg-rose-500/10"
            >
              Retry
            </button>
          </div>
        )}
        <Card title="Start a workflow" subtitle="Execution runs in the backend; active progress is refreshed automatically">
          {loading ? <p className="text-sm text-slate-400">Loading projects…</p> : projects.length === 0 ? (
            projectsError
              ? <p role="alert" className="text-sm text-rose-200">Projects could not be loaded. Use Retry to try again.</p>
              : <p className="text-sm text-slate-400">Create a project before starting a workflow.</p>
          ) : (
            <form onSubmit={handleStart} className="grid gap-4 md:grid-cols-2">
              <label className="text-sm text-slate-300">
                Project
                <select
                  aria-label="Project"
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
                >
                  {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                </select>
              </label>
              <label className="text-sm text-slate-300">
                Workflow type
                <select
                  value={workflowType}
                  onChange={(event) => {
                    const nextWorkflowType = event.target.value
                    setWorkflowType(nextWorkflowType)
                    setChangeSummaryError(
                      workflowStartValidationError(nextWorkflowType, changeSummary),
                    )
                  }}
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
                >
                  {workflowTypes.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label className="text-sm text-slate-300 md:col-span-2">
                Requirements prompt (optional)
                <textarea
                  value={requirementsPrompt}
                  onChange={(event) => setRequirementsPrompt(event.target.value)}
                  maxLength={10000}
                  rows={3}
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
                  placeholder={'Use project documents by default, or include identified requirements like "REQ-AUTH-01: Registered users can sign in."'}
                />
                <span className="mt-1 block text-xs text-slate-500">
                  Add one requirement per line as KEY: description to create explicit test-to-requirement links.
                </span>
              </label>
              {(workflowType === 'test_generation' || workflowType === 'full_qa_workflow') && (
                <>
                  <label className="text-sm text-slate-300">
                    Maximum test cases
                    <input
                      type="number"
                      min="1"
                      max="20"
                      value={maxCases}
                      onChange={(event) => setMaxCases(Number(event.target.value))}
                      className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
                    />
                  </label>
                  <fieldset className="text-sm text-slate-300">
                    <legend>Scenario categories</legend>
                    <div className="mt-2 flex flex-wrap gap-3">
                      {['positive', 'negative', 'boundary', 'edge'].map((category) => (
                        <label key={category} className="inline-flex items-center gap-2 capitalize">
                          <input
                            type="checkbox"
                            checked={categories.includes(category)}
                            disabled={categories.length === 1 && categories.includes(category)}
                            onChange={(event) => setCategories((current) => (
                              event.target.checked
                                ? [...current, category]
                                : current.filter((item) => item !== category)
                            ))}
                            className="accent-sky-400"
                          />
                          {category}
                        </label>
                      ))}
                    </div>
                    <p className="mt-2 text-xs text-slate-500">Select at least one scenario category.</p>
                  </fieldset>
                </>
              )}
              {(workflowType === 'change_risk_analysis' || workflowType === 'full_qa_workflow') && (
                <label className="text-sm text-slate-300 md:col-span-2">
                  Change summary (required for change-risk analysis)
                  <textarea
                    id="change-summary"
                    value={changeSummary}
                    onChange={(event) => {
                      const value = event.target.value
                      setChangeSummary(value)
                      setChangeSummaryError(
                        workflowStartValidationError(workflowType, value),
                      )
                    }}
                    maxLength={5000}
                    minLength={10}
                    aria-invalid={Boolean(changeSummaryError)}
                    aria-describedby={changeSummaryError ? 'change-summary-error' : undefined}
                    rows={2}
                    className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
                    placeholder="Describe the software change to analyze."
                  />
                  {changeSummaryError && (
                    <span id="change-summary-error" role="alert" className="mt-1 block text-xs text-rose-300">
                      {changeSummaryError}
                    </span>
                  )}
                </label>
              )}
              <div className="md:col-span-2">
                <button
                  type="submit"
                  disabled={submitting || !projectId || hasActiveWorkflow}
                  className="inline-flex items-center gap-2 rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Play size={16} />
                  {submitting ? 'Starting…' : 'Start workflow'}
                </button>
                {hasActiveWorkflow && <span className="ml-3 text-xs text-slate-500">A workflow is already active for this project.</span>}
              </div>
            </form>
          )}
        </Card>

        <Card title="Workflow history" subtitle="Task states reflect persisted agent results">
          {loadingWorkflows || (projectId && workflowsProjectId !== projectId) ? (
            <p role="status" className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
              Loading workflow history…
            </p>
          ) : historyError ? (
            <p role="alert" className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-3 py-6 text-center text-sm text-rose-200">
              Workflow history could not be loaded: {historyError}
            </p>
          ) : workflows.length === 0 ? (
            <p className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
              No workflows have been started for this project.
            </p>
          ) : (
            <div className="space-y-4">
              {workflows.map((workflow) => {
                const detail = workflowDetails[`${projectId}:${workflow.id}`]
                const detailsKey = `${projectId}:${workflow.id}`
                return (
                <details
                  key={workflow.id}
                  className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4"
                  open={expandedWorkflows[detailsKey] ?? (workflow.status === 'running')}
                  onToggle={(event) => {
                    const isOpen = event.currentTarget.open
                    expandedWorkflowsRef.current = {
                      ...expandedWorkflowsRef.current,
                      [detailsKey]: isOpen,
                    }
                    setExpandedWorkflows((current) => ({
                      ...current,
                      [detailsKey]: isOpen,
                    }))
                    if (isOpen && !detail) {
                      const requestedProjectId = projectId
                      loadDetails(requestedProjectId, workflow.id, true).catch((requestError) => {
                        if (isCurrentWorkflowProject(requestedProjectId, selectedProjectRef.current)) {
                          setError(getApiErrorMessage(requestError, 'Workflow details could not be loaded.'))
                        }
                      })
                    }
                  }}
                >
                  <summary className="cursor-pointer list-none">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <h3 className="font-semibold capitalize text-slate-100">{(workflow.workflow_type || 'workflow').replaceAll('_', ' ')}</h3>
                        <p className="mt-1 text-xs text-slate-500">
                          Run #{workflow.id} · Created {formatTimestamp(workflow.created_at)}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          Started {formatTimestamp(workflow.started_at)}
                          {' · '}Completed {formatTimestamp(workflow.completed_at)}
                          {' · '}Updated {formatTimestamp(workflow.updated_at)}
                        </p>
                      </div>
                      <StatusBadge status={workflow.status} />
                    </div>
                  </summary>
                  <div className="mt-4 space-y-4 border-t border-slate-800 pt-4">
                    <div className="flex flex-wrap gap-2">
                      {(detail?.tasks || workflow.tasks || []).map((task) => (
                        <span key={task.id} className="inline-flex items-center gap-2 rounded-xl border border-slate-800 px-3 py-2 text-xs text-slate-300">
                          {(task.agent_name || task.task_type || 'Task').replaceAll('_', ' ')}
                          <StatusBadge status={getTaskStatus(task)} />
                        </span>
                      ))}
                    </div>
                    {(detail?.tasks || workflow.tasks || []).length > 0 && (
                      <TaskHistory workflow={detail || workflow} />
                    )}
                    {workflow.can_resume ? (
                      <button
                        type="button"
                        disabled={resumingId !== null}
                        onClick={() => handleResume(workflow.id)}
                        className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <RotateCw size={15} /> {resumingId === workflow.id ? 'Resuming…' : 'Resume workflow'}
                      </button>
                    ) : workflow.resume_reason ? (
                      <p className="text-xs text-slate-500">{workflow.resume_reason}</p>
                    ) : null}
                    {detail
                      ? <OutputSummary workflow={detail} />
                      : loadingDetails[detailsKey]
                        ? <p role="status" className="text-sm text-slate-400">Loading workflow details…</p>
                        : <p className="text-sm text-slate-500">Open this workflow to load its persisted results.</p>}
                  </div>
                </details>
                )
              })}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

export default WorkflowsPage
