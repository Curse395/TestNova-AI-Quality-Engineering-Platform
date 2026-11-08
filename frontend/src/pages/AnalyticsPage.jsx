import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import { fetchProjectAnalytics, fetchProjects } from '../api/projects'

const AnalyticsPage = () => {
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [analytics, setAnalytics] = useState(null)
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
  const rows = analytics?.documents || []

  return (
    <div className="min-h-screen bg-[#020617] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="Quality Analytics" subtitle="Project knowledge health" />
        {projects.length > 0 && (
          <label className="max-w-md text-sm text-slate-400">
            Project
            <select
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
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
        ) : overview ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Metric title="Documents" value={overview.documents} />
              <Metric title="Chunks" value={overview.chunks} />
              <Metric title="Embeddings" value={overview.embeddings} />
              <Metric title="Embedding coverage" value={`${overview.embedding_coverage}%`} />
            </div>
            <Card title="Document processing" subtitle="Chunk and embedding counts by document">
              {rows.length === 0 ? (
                <p className="text-sm text-slate-400">No documents have been uploaded to this project.</p>
              ) : (
                <div className="space-y-4">
                  {rows.map((document) => {
                    const coverage = document.chunks
                      ? Math.min(100, Math.round((document.embeddings / document.chunks) * 100))
                      : 0
                    return (
                      <div key={document.document_id} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="break-all font-medium text-white">{document.filename}</p>
                          <p className="text-sm text-slate-400">{document.chunks} chunks · {document.embeddings} embeddings</p>
                        </div>
                        <div className="mt-3 h-2 rounded-full bg-slate-800">
                          <div className="h-2 rounded-full bg-sky-400" style={{ width: `${coverage}%` }} />
                        </div>
                        <p className="mt-2 text-right text-xs text-slate-500">{coverage}% embedding coverage</p>
                      </div>
                    )
                  })}
                </div>
              )}
            </Card>
          </>
        ) : null}
      </div>
    </div>
  )
}

const Metric = ({ title, value }) => (
  <Card className="!p-4">
    <p className="text-xs text-slate-400">{title}</p>
    <p className="mt-3 text-2xl font-semibold text-sky-400">{value ?? 0}</p>
  </Card>
)

export default AnalyticsPage
