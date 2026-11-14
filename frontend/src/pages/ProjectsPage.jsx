import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { getApiErrorMessage } from '../api/client'
import { createProject, deleteProject, fetchProjects } from '../api/projects'

const ProjectsPage = () => {
  const [projects, setProjects] = useState([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const loadProjects = useCallback(async () => {
    try {
      setProjects(await fetchProjects())
      setError('')
    } catch (requestError) {
      if (requestError?.response?.status === 401) {
        navigate('/login', { replace: true })
        return
      }
      setError('Projects could not be loaded. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [navigate])

  useEffect(() => {
    loadProjects()
  }, [loadProjects])

  const handleCreate = async (event) => {
    event.preventDefault()
    if (!name.trim()) return

    setSaving(true)
    setError('')
    try {
      const project = await createProject({
        name: name.trim(),
        description: description.trim() || null,
      })
      setProjects((current) => [project, ...current])
      setName('')
      setDescription('')
    } catch (requestError) {
      if (requestError?.response?.status === 401) {
        navigate('/login', { replace: true })
      } else {
        setError(getApiErrorMessage(requestError, 'Project could not be created.'))
      }
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (project) => {
    if (!window.confirm(`Delete "${project.name}" and its project data?`)) return
    try {
      await deleteProject(project.id)
      setProjects((current) => current.filter((item) => item.id !== project.id))
    } catch (requestError) {
      if (requestError?.response?.status === 401) {
        navigate('/login', { replace: true })
      } else {
        setError(getApiErrorMessage(requestError, 'Project could not be deleted.'))
      }
    }
  }

  return (
    <div className="workspace-page min-h-screen bg-[var(--background)] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="Projects" subtitle="Portfolio" />
        {error && <p role="alert" className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">{error}</p>}
        <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <Card title="Portfolio" subtitle="Projects in your workspace">
            {loading ? (
              <p className="text-sm text-slate-400">Loading projects…</p>
            ) : projects.length === 0 ? (
              <p className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
                No projects yet. Create one to get started.
              </p>
            ) : (
              <div className="space-y-3">
                {projects.map((project) => (
                  <div key={project.id} className="flex items-start justify-between gap-4 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                    <div>
                      <p className="font-semibold text-slate-100">{project.name}</p>
                      <p className="mt-1 text-sm text-slate-400">{project.description || 'No description'}</p>
                    </div>
                    <Button variant="ghost" onClick={() => handleDelete(project)}>Delete</Button>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card title="New project" subtitle="Projects are created in your owned workspace">
            <form className="space-y-4" onSubmit={handleCreate}>
              <label className="block text-sm text-slate-300">
                Project name
                <input
                  required
                  maxLength={200}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-slate-100"
                />
              </label>
              <label className="block text-sm text-slate-300">
                Description
                <textarea
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-slate-100"
                  rows={3}
                />
              </label>
              <Button disabled={saving}>{saving ? 'Creating…' : 'Create project'}</Button>
            </form>
          </Card>
        </div>
      </div>
    </div>
  )
}

export default ProjectsPage
