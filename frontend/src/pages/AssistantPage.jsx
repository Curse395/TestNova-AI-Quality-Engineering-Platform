import { useEffect, useRef, useState, useCallback } from 'react'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import {
  createChatSession,
  fetchChatSession,
  fetchChatSessions,
  sendMessage,
} from '../api/chat'
import { fetchDashboard } from '../api/dashboard'
import { fetchProjects } from '../api/projects'

/* ------------------------------------------------------------------ */
/*  Suggestion → prompt mapping                                        */
/* ------------------------------------------------------------------ */
const SUGGESTION_PROMPTS = {
  generate_embeddings: 'What documents still need embeddings?',
  review_projects: 'Which projects need attention before release?',
}

function toChatMessages(history) {
  if (!Array.isArray(history)) {
    throw new Error('Unexpected chat history response.')
  }

  return [...history]
    .sort((a, b) => {
      const timeDifference = Date.parse(a.created_at) - Date.parse(b.created_at)
      if (Number.isFinite(timeDifference) && timeDifference !== 0) {
        return timeDifference
      }
      return a.id - b.id
    })
    .flatMap((entry) => [
      { role: 'user', text: entry.question },
      { role: 'assistant', text: entry.answer },
    ])
}

/* ------------------------------------------------------------------ */
/*  Toast                                                              */
/* ------------------------------------------------------------------ */
const Toast = ({ message, onClose }) => {
  useEffect(() => {
    const t = setTimeout(onClose, 5000)
    return () => clearTimeout(t)
  }, [onClose])

  return (
    <div className="fixed bottom-6 right-6 z-50 max-w-sm rounded-2xl border border-rose-500/30 bg-rose-500/15 px-5 py-3 text-sm text-rose-200 shadow-xl backdrop-blur">
      {message}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Skeleton loaders                                                   */
/* ------------------------------------------------------------------ */
const HistorySkeleton = () => (
  <div className="space-y-3">
    {[1, 2, 3].map((i) => (
      <div key={i} className="space-y-2">
        <div className="ml-auto h-10 w-3/4 animate-pulse rounded-2xl bg-slate-800/70" />
        <div className="mr-auto h-14 w-4/5 animate-pulse rounded-2xl bg-slate-800/70" />
      </div>
    ))}
  </div>
)

const TypingIndicator = () => (
  <div className="flex items-center gap-2 rounded-2xl bg-sky-500/10 px-4 py-3 text-sm text-slate-400">
    <span className="inline-block h-2 w-2 animate-bounce rounded-full bg-sky-400 [animation-delay:-0.3s]" />
    <span className="inline-block h-2 w-2 animate-bounce rounded-full bg-sky-400 [animation-delay:-0.15s]" />
    <span className="inline-block h-2 w-2 animate-bounce rounded-full bg-sky-400" />
    <span className="ml-1">Thinking…</span>
  </div>
)

/* ------------------------------------------------------------------ */
/*  Source citation                                                    */
/* ------------------------------------------------------------------ */
function formatSourceLocation(metadata = {}) {
  const sourceMetadata = metadata && typeof metadata === 'object' ? metadata : {}
  const location = sourceMetadata.source_location && typeof sourceMetadata.source_location === 'object'
    ? sourceMetadata.source_location
    : sourceMetadata
  const parts = []

  if (Array.isArray(location.page_numbers) && location.page_numbers.length) {
    parts.push(`Page${location.page_numbers.length > 1 ? 's' : ''} ${location.page_numbers.join(', ')}`)
  }
  if (location.section) parts.push(`Section: ${location.section}`)
  if (location.sheet_name) parts.push(`Sheet: ${location.sheet_name}`)

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

const SourceCitation = ({ sources }) => {
  if (!sources || sources.length === 0) return null
  return (
    <div className="mt-2 rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Sources</p>
      <div className="space-y-2">
        {sources.map((src) => {
          const location = formatSourceLocation(src.source_metadata)
          const similarity = src.similarity
            ?? (typeof src.distance === 'number' ? 1 - src.distance : null)
            ?? (typeof src.score === 'number' ? 1 - src.score : null)

          return (
            <details key={src.chunk_id} className="rounded-xl border border-slate-800 bg-slate-900/50 p-3">
              <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 text-sm text-slate-300">
                <span>
                  📄 {src.document_name}
                  {src.source_type ? ` · ${src.source_type.replaceAll('_', ' ')}` : ''}
                  {location ? ` · ${location}` : ''}
                </span>
                <span className="text-xs text-slate-500">
                  Chunk #{src.chunk_id} · Similarity: {Number.isFinite(similarity) ? similarity.toFixed(2) : 'unavailable'}
                </span>
              </summary>
              <p className="mt-2 whitespace-pre-wrap border-l-2 border-sky-500/40 pl-3 text-sm text-slate-400">
                {src.excerpt || 'Source excerpt is unavailable.'}
              </p>
            </details>
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */
const AssistantPage = () => {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [projects, setProjects] = useState([])
  const [projectLoading, setProjectLoading] = useState(true)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [suggestions, setSuggestions] = useState([])
  const [toast, setToast] = useState(null)
  const [selectedProject, setSelectedProject] = useState(null)
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)
  const viewRequestIdRef = useRef(0)
  const sendRequestIdRef = useRef(0)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, sending, scrollToBottom])

  const loadProjectConversation = useCallback(async (project, requestId) => {
    try {
      const projectSessions = await fetchChatSessions(project.id)
      let availableSessions = projectSessions
      if (availableSessions.length === 0) {
        const session = await createChatSession(project.id)
        availableSessions = [session]
      }

      if (requestId !== viewRequestIdRef.current) return
      if (availableSessions.some((session) => session.project_id !== project.id)) {
        throw new Error('A conversation did not match the selected project.')
      }

      setSessions(availableSessions)
      const activeSession = availableSessions[0]
      setActiveSessionId(activeSession.id)

      const session = await fetchChatSession(project.id, activeSession.id)
      if (requestId !== viewRequestIdRef.current) return
      if (session.project_id !== project.id || session.id !== activeSession.id) {
        throw new Error('The conversation did not match the selected project.')
      }
      setMessages(toChatMessages(session.messages))
    } catch {
      if (requestId === viewRequestIdRef.current) {
        setSessions([])
        setActiveSessionId(null)
        setMessages([])
        setToast('Could not load this project’s conversations. Please try again.')
      }
    } finally {
      if (requestId === viewRequestIdRef.current) setHistoryLoading(false)
    }
  }, [])

  /* Load authorized projects, suggestions, and the first project's conversation. */
  useEffect(() => {
    let cancelled = false

    async function init() {
      try {
        const [projList, dashData] = await Promise.all([
          fetchProjects(),
          fetchDashboard().catch(() => null),
        ])
        if (cancelled) return

        setProjects(projList)
        setProjectLoading(false)
        if (dashData?.assistant?.suggestions) {
          setSuggestions(dashData.assistant.suggestions)
        }

        const activeProject = projList[0] || null
        if (!activeProject) {
          setSelectedProject(null)
          setSessions([])
          setActiveSessionId(null)
          setMessages([])
          setHistoryLoading(false)
          return
        }
        setSelectedProject(activeProject)
        const requestId = ++viewRequestIdRef.current
        await loadProjectConversation(activeProject, requestId)
      } catch {
        if (!cancelled) {
          setProjectLoading(false)
          setHistoryLoading(false)
          setMessages([])
          setToast('Could not load your projects. Please try again.')
        }
      } finally {
        if (!cancelled) setProjectLoading(false)
      }
    }

    init()
    return () => {
      cancelled = true
      viewRequestIdRef.current += 1
      sendRequestIdRef.current += 1
    }
  }, [loadProjectConversation])

  const handleSelectProject = async (event) => {
    const projectId = Number(event.target.value)
    const project = projects.find((item) => item.id === projectId)
    if (!project || project.id === selectedProject?.id) return

    const requestId = ++viewRequestIdRef.current
    sendRequestIdRef.current += 1
    setSending(false)
    setSelectedProject(project)
    setMessages([])
    setSessions([])
    setActiveSessionId(null)
    setHistoryLoading(true)
    setToast(null)
    await loadProjectConversation(project, requestId)
  }

  const handleSelectSession = async (event) => {
    const sessionId = Number(event.target.value)
    const session = sessions.find((item) => item.id === sessionId)
    if (!session || !selectedProject) return

    const requestId = ++viewRequestIdRef.current
    sendRequestIdRef.current += 1
    setSending(false)
    setActiveSessionId(session.id)
    setHistoryLoading(true)
    setMessages([])

    try {
      const data = await fetchChatSession(selectedProject.id, session.id)
      if (requestId === viewRequestIdRef.current) {
        if (data.project_id !== selectedProject.id || data.id !== session.id) {
          throw new Error('The conversation did not match the selected project.')
        }
        setMessages(toChatMessages(data.messages))
      }
    } catch {
      if (requestId === viewRequestIdRef.current) {
        setToast('Could not load this conversation. Please try again.')
      }
    } finally {
      if (requestId === viewRequestIdRef.current) setHistoryLoading(false)
    }
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || sending || historyLoading || !selectedProject || !activeSessionId) return

    const projectId = selectedProject.id
    const sessionId = activeSessionId
    const requestId = ++sendRequestIdRef.current
    const viewRequestId = viewRequestIdRef.current
    setInput('')
    setSending(true)

    // Append the user message immediately.
    setMessages((prev) => [...prev, { role: 'user', text }])

    try {
      const res = await sendMessage(projectId, sessionId, text)
      if (
        requestId === sendRequestIdRef.current &&
        viewRequestId === viewRequestIdRef.current
      ) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            text: res.answer || 'No answer was returned.',
            sources: res.sources || [],
          },
        ])
      }
    } catch {
      if (
        requestId === sendRequestIdRef.current &&
        viewRequestId === viewRequestIdRef.current
      ) {
        setToast('Failed to get a response. Please try again.')
        setMessages((prev) => prev.slice(0, -1))
        setInput(text)
      }
    } finally {
      if (requestId === sendRequestIdRef.current) {
        setSending(false)
        inputRef.current?.focus()
      }
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSuggestionClick = (suggestion) => {
    const action = typeof suggestion === 'object' ? suggestion.action : null
    const prompt = SUGGESTION_PROMPTS[action] || (typeof suggestion === 'object' ? suggestion.title : suggestion)
    setInput(prompt)
    inputRef.current?.focus()
  }

  const handleNewThread = async () => {
    if (!selectedProject || sending || historyLoading) return

    const projectId = selectedProject.id
    const requestId = ++viewRequestIdRef.current
    setHistoryLoading(true)
    try {
      const session = await createChatSession(projectId)
      if (requestId !== viewRequestIdRef.current) return
      if (session.project_id !== projectId) {
        throw new Error('The new conversation did not match the selected project.')
      }
      setSessions((prev) => [session, ...prev])
      setActiveSessionId(session.id)
      setMessages([])
    } catch {
      if (requestId === viewRequestIdRef.current) {
        setToast('Could not start a new conversation. Please try again.')
      }
    } finally {
      if (requestId === viewRequestIdRef.current) setHistoryLoading(false)
    }
  }

  const priorityColor = (p) =>
    p === 'High' ? 'text-rose-400 bg-rose-500/10' : p === 'Medium' ? 'text-amber-400 bg-amber-500/10' : 'text-sky-400 bg-sky-500/10'

  return (
    <div className="overflow-hidden bg-[#020617] p-4 text-slate-100 lg:p-6" style={{ height: '100vh' }}>
      <div className="mx-auto flex h-full max-w-7xl flex-col gap-6">
        <Navbar title="AI Assistant" subtitle="Copilot" />

        <div className="grid flex-1 gap-6 xl:grid-cols-[0.95fr_1.05fr]" style={{ minHeight: 0 }}>
          {/* ---------- Left: Suggestions ---------- */}
          <Card title="Live workspace" subtitle="Suggested next actions" className="flex flex-col" style={{ minHeight: 0 }}>
            {suggestions.length === 0 ? (
              <p className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
                No suggestions right now.
              </p>
            ) : (
              <div className="testnova-scroll min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 text-sm text-slate-300" style={{ minHeight: 0 }}>
                {suggestions.map((s, i) => {
                  const title = typeof s === 'string' ? s : s.title
                  const desc = typeof s === 'object' ? s.description : null
                  const prio = typeof s === 'object' ? s.priority : null
                  return (
                    <button
                      key={i}
                      onClick={() => handleSuggestionClick(s)}
                      className="w-full rounded-2xl border border-slate-800 bg-slate-950/70 p-3 text-left transition hover:border-sky-500/40 hover:bg-sky-500/5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-slate-100">{title}</span>
                        {prio && (
                          <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${priorityColor(prio)}`}>
                            {prio}
                          </span>
                        )}
                      </div>
                      {desc && <p className="mt-1 text-xs text-slate-400">{desc}</p>}
                    </button>
                  )
                })}
              </div>
            )}
          </Card>

          {/* ---------- Right: Conversation ---------- */}
          <Card
            title="Conversation"
            subtitle={`AI-powered support for quality teams${selectedProject ? ` · ${selectedProject.name}` : ''}`}
            action={
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-2 text-xs text-slate-400">
                  <span>Project</span>
                  <select
                    value={selectedProject?.id ?? ''}
                    onChange={handleSelectProject}
                    disabled={projectLoading || projects.length === 0}
                    aria-label="Select project"
                    className="max-w-40 rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-xs text-slate-200 disabled:opacity-50"
                  >
                    {projects.length === 0 ? (
                      <option value="">No projects</option>
                    ) : (
                      projects.map((project) => (
                        <option key={project.id} value={project.id}>
                          {project.name}
                        </option>
                      ))
                    )}
                  </select>
                </label>
                {sessions.length > 0 && (
                  <select
                    value={activeSessionId ?? ''}
                    onChange={handleSelectSession}
                    disabled={historyLoading || sending}
                    aria-label="Select conversation"
                    className="max-w-40 rounded-xl border border-slate-700 bg-slate-950/80 px-3 py-2 text-xs text-slate-200 disabled:opacity-50"
                  >
                    {sessions.map((session) => (
                      <option key={session.id} value={session.id}>
                        {session.title} · {session.id}
                      </option>
                    ))}
                  </select>
                )}
                <Button
                  variant="secondary"
                  onClick={handleNewThread}
                  disabled={sending || historyLoading || projectLoading || !selectedProject}
                >
                  New thread
                </Button>
              </div>
            }
            className="flex flex-col"
            style={{ minHeight: 0 }}
          >
            <div className="testnova-scroll flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1" style={{ minHeight: 0 }}>
              {historyLoading ? (
                <HistorySkeleton />
              ) : !selectedProject ? (
                <div className="flex flex-1 items-center justify-center">
                  <p className="text-sm text-slate-500">Create a project to start a conversation.</p>
                </div>
              ) : messages.length === 0 ? (
                <div className="flex flex-1 items-center justify-center">
                  <p className="text-sm text-slate-500">Ask a question to get started.</p>
                </div>
              ) : (
                messages.map((msg, i) => (
                  <div
                    key={i}
                    className={`rounded-2xl p-3 text-sm ${msg.role === 'assistant' ? 'bg-sky-500/10 text-slate-100' : 'ml-8 bg-slate-950/70 text-slate-300'}`}
                  >
                    <p className="mb-1 text-xs uppercase tracking-[0.25em] text-slate-500">
                      {msg.role === 'user' ? 'You' : 'Assistant'}
                    </p>
                    <p className="whitespace-pre-wrap">{msg.text}</p>
                    {msg.role === 'assistant' && <SourceCitation sources={msg.sources} />}
                  </div>
                ))
              )}

              {sending && <TypingIndicator />}

              <div ref={messagesEndRef} />
            </div>

            <div className="mt-4 flex gap-3">
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={sending || historyLoading || !selectedProject || !activeSessionId}
                className="flex-1 rounded-2xl border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none placeholder:text-slate-500 disabled:opacity-50"
                placeholder={selectedProject ? 'Ask the assistant…' : 'No project available'}
              />
              <Button onClick={handleSend} disabled={sending || historyLoading || !input.trim() || !selectedProject || !activeSessionId}>
                {sending ? 'Sending…' : 'Send'}
              </Button>
            </div>
          </Card>
        </div>
      </div>

      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
    </div>
  )
}

export default AssistantPage