import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { getApiErrorMessage } from '../api/client'
import { fetchProjectDocuments, fetchProjects, uploadAndProcessDocument } from '../api/projects'

const UploadPage = () => {
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [sourceType, setSourceType] = useState('document')
  const [documents, setDocuments] = useState([])
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
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
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [navigate])

  useEffect(() => {
    if (!projectId) {
      setDocuments([])
      return
    }
    let active = true
    fetchProjectDocuments(Number(projectId))
      .then((items) => { if (active) setDocuments(items) })
      .catch((requestError) => {
        if (!active) return
        if (requestError?.response?.status === 401) navigate('/login', { replace: true })
        else setError('Documents could not be loaded.')
      })
    return () => { active = false }
  }, [projectId, navigate])

  const handleUpload = async (event) => {
    event.preventDefault()
    if (!file || !projectId) return

    const form = event.currentTarget
    setUploading(true)
    setError('')
    try {
      await uploadAndProcessDocument(Number(projectId), file, sourceType)
      setFile(null)
      form.reset()
      setDocuments(await fetchProjectDocuments(Number(projectId)))
    } catch (requestError) {
      if (requestError?.response?.status === 401) {
        navigate('/login', { replace: true })
      } else {
        setError(getApiErrorMessage(requestError, 'Upload or processing failed. Check the document status and try again.'))
        try {
          setDocuments(await fetchProjectDocuments(Number(projectId)))
        } catch {
          // Keep the original operation error visible.
        }
      }
    } finally {
      setUploading(false)
    }
  }

  const statusTone = (status) => status === 'completed'
    ? 'text-emerald-400'
    : status === 'failed'
      ? 'text-rose-400'
      : 'text-amber-400'

  return (
    <div className="min-h-screen bg-[#020617] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="Upload Center" subtitle="Project knowledge" />
        {error && <p role="alert" className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">{error}</p>}
        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <Card title="Upload a document" subtitle="Supported: PDF, DOCX, TXT, CSV, XLSX, and JSON.">
            {loading ? (
              <p className="text-sm text-slate-400">Loading projects…</p>
            ) : projects.length === 0 ? (
              <p className="text-sm text-slate-400">Create a project before uploading documents.</p>
            ) : (
              <form className="space-y-4" onSubmit={handleUpload}>
                <label className="block text-sm text-slate-300">
                  Project
                  <select
                    value={projectId}
                    onChange={(event) => setProjectId(event.target.value)}
                    className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-slate-100"
                  >
                    {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                  </select>
                </label>
                <label className="block text-sm text-slate-300">
                  Document category
                  <select
                    value={sourceType}
                    onChange={(event) => setSourceType(event.target.value)}
                    className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-slate-100"
                  >
                    <option value="document">General document</option>
                    <option value="requirements">Requirements / specification</option>
                    <option value="bug_report">Bug report / issue</option>
                    <option value="test_log">Test execution log</option>
                    <option value="technical_document">Technical documentation</option>
                  </select>
                </label>
                <label className="block rounded-3xl border border-dashed border-slate-700 bg-slate-950/70 p-8 text-center">
                  <span className="block text-lg font-semibold text-white">Choose a project document</span>
                  <span className="mt-2 block text-sm text-slate-400">File size limit is configured by the server.</span>
                  <input
                    className="mt-5 block w-full text-sm text-slate-300"
                    type="file"
                    accept=".pdf,.docx,.txt,.csv,.xlsx,.json"
                    onChange={(event) => setFile(event.target.files?.[0] || null)}
                  />
                </label>
                {file && <p className="text-sm text-slate-400">Selected: {file.name}</p>}
                <Button disabled={!file || uploading}>{uploading ? 'Uploading and processing…' : 'Upload and process'}</Button>
              </form>
            )}
          </Card>

          <Card title="Project documents" subtitle="Upload, extraction, and embedding status">
            {!projectId ? (
              <p className="text-sm text-slate-400">Select or create a project to view documents.</p>
            ) : documents.length === 0 ? (
              <p className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
                No documents uploaded to this project.
              </p>
            ) : (
              <div className="space-y-3">
                {documents.map((document) => (
                  <div key={document.id} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="break-all font-medium text-white">{document.filename}</p>
                        <p className="mt-1 text-xs text-slate-500">{document.source_type?.replaceAll('_', ' ')}</p>
                      </div>
                      <span className={`shrink-0 text-sm capitalize ${statusTone(document.processing_status)}`}>
                        {document.processing_status}
                      </span>
                    </div>
                    {document.processing_error && <p className="mt-2 text-sm text-rose-300">{document.processing_error}</p>}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

export default UploadPage
