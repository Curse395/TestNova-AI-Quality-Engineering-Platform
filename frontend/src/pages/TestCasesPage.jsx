import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import { getApiErrorMessage } from '../api/client'
import { fetchProjects, fetchProjectTestCases } from '../api/projects'

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
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [testCases, setTestCases] = useState([])
  const [loadingProjects, setLoadingProjects] = useState(true)
  const [loadingCases, setLoadingCases] = useState(false)
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
        else setError(getApiErrorMessage(requestError, 'Projects could not be loaded.'))
      })
      .finally(() => {
        if (active) setLoadingProjects(false)
      })
    return () => { active = false }
  }, [navigate])

  useEffect(() => {
    if (!projectId) {
      setTestCases([])
      return
    }

    let active = true
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
    return () => { active = false }
  }, [projectId, navigate])

  return (
    <div className="min-h-screen bg-[#020617] p-4 text-slate-100 lg:p-6">
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

        <Card title="Saved test cases" subtitle="Source links reference the exact document chunks used during generation">
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
                      <h2 className="font-semibold text-white">{testCase.title}</h2>
                      {(testCase.category || testCase.priority || testCase.review_status) && (
                        <p className="mt-1 text-xs capitalize text-slate-400">
                          {[testCase.category, testCase.priority && `${testCase.priority} priority`, testCase.review_status]
                            .filter(Boolean)
                            .join(' · ')}
                        </p>
                      )}
                    </div>
                    <span className="text-xs text-slate-500">Case #{testCase.id}</span>
                  </div>
                  {testCase.description && (
                    <p className="mt-3 whitespace-pre-wrap text-sm text-slate-300">{testCase.description}</p>
                  )}
                  {testCase.preconditions && (
                    <div className="mt-4">
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Preconditions</h3>
                      <p className="mt-2 whitespace-pre-wrap text-sm text-slate-300">{testCase.preconditions}</p>
                    </div>
                  )}
                  {Array.isArray(testCase.steps) && testCase.steps.length > 0 && (
                    <div className="mt-4">
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Test steps</h3>
                      <ol className="mt-2 list-decimal space-y-3 pl-5">
                        {testCase.steps.map((step, index) => (
                          <li key={`${testCase.id}-step-${index}`} className="pl-1 text-sm text-slate-300">
                            {step.action && <p className="whitespace-pre-wrap">{step.action}</p>}
                            {step.expected_result && (
                              <p className="mt-1 whitespace-pre-wrap text-slate-400">
                                Expected: {step.expected_result}
                              </p>
                            )}
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}
                  {testCase.expected_result && (
                    <div className="mt-4">
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Expected result</h3>
                      <p className="mt-2 whitespace-pre-wrap text-sm text-slate-300">{testCase.expected_result}</p>
                    </div>
                  )}

                  {testCase.evidence?.length ? (
                    <div className="mt-4 border-t border-slate-800 pt-4">
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Source evidence</h3>
                      <div className="mt-2 space-y-3">
                        {testCase.evidence.map((source) => {
                          const location = sourceLocation(source.source_metadata)
                          return (
                            <div key={`${source.document_id}-${source.chunk_id}`} className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
                              <p className="break-all text-sm font-medium text-sky-200">
                                {source.document_name}
                              </p>
                              <p className="mt-1 text-xs text-slate-500">
                                Document #{source.document_id} · Chunk #{source.chunk_id}
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
                    </div>
                  ) : (
                    <p className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-sm text-amber-200">
                      No verified source evidence is available for this test case.
                    </p>
                  )}
                </article>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

export default TestCasesPage
