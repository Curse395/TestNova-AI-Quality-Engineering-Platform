import { useEffect, useRef, useState, useCallback } from 'react'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { sendMessage, fetchChatHistory } from '../api/chat'
import { fetchDashboard } from '../api/dashboard'
import { apiClient } from '../api/client'

/* ------------------------------------------------------------------ */
/*  Suggestion → prompt mapping                                        */
/* ------------------------------------------------------------------ */
const SUGGESTION_PROMPTS = {
  generate_embeddings: 'What documents still need embeddings?',
  review_projects: 'Which projects need attention before release?',
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
const SourceCitation = ({ sources }) => {
  if (!sources || sources.length === 0) return null
  return (
    <div className="mt-2 rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Sources</p>
      <div className="space-y-2">
        {sources.map((src, i) => (
          <div key={i} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-slate-300">📄 {src.document_name}</span>
            <span className="text-xs text-slate-500">Similarity: {Number(src.score).toFixed(2)}</span>
          </div>
        ))}
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
  const [historyLoading, setHistoryLoading] = useState(true)
  const [suggestions, setSuggestions] = useState([])
  const [toast, setToast] = useState(null)
  const [selectedProject, setSelectedProject] = useState(null)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, sending, scrollToBottom])

  /* Load projects, suggestions, and chat history on mount */
  useEffect(() => {
    let cancelled = false

    async function init() {
      try {
        const projRes = await apiClient.get('/projects/')
        const projList = projRes.data?.data || []
        if (cancelled) return

        const activeProject = projList.length > 0 ? projList[0] : null
        if (!activeProject) {
          setHistoryLoading(false)
          return
        }
        setSelectedProject(activeProject)

        const [dashData, history] = await Promise.all([
          fetchDashboard().catch(() => null),
          fetchChatHistory(activeProject.id).catch(() => []),
        ])

        if (cancelled) return

        if (dashData?.assistant?.suggestions) {
          setSuggestions(dashData.assistant.suggestions)
        }

        const sorted = [...history].sort(
          (a, b) => new Date(a.created_at) - new Date(b.created_at),
        )
        setMessages(
          sorted.flatMap((h) => [
            { role: 'user', text: h.question },
            { role: 'assistant', text: h.answer },
          ]),
        )
      } catch (err) {
        if (!cancelled) {
          setToast('Could not load assistant data. Please try again later.')
        }
      } finally {
        if (!cancelled) setHistoryLoading(false)
      }
    }

    init()
    return () => { cancelled = true }
  }, [])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || sending || !selectedProject) return

    setInput('')
    setSending(true)

    // Append the user message immediately.
    setMessages((prev) => [...prev, { role: 'user', text }])

    try {
      const res = await sendMessage(selectedProject.id, text)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: res.answer || 'No answer was returned.',
          sources: res.sources || [],
        },
      ])
    } catch (err) {
      setToast('Failed to get a response. Please try again.')
      setMessages((prev) => prev.slice(0, -1))
      setInput(text)
    } finally {
      setSending(false)
      inputRef.current?.focus()
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

  const handleNewThread = () => {
    setMessages([])
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
              <Button variant="secondary" onClick={handleNewThread} disabled={sending}>
                New thread
              </Button>
            }
            className="flex flex-col"
            style={{ minHeight: 0 }}
          >
            <div className="testnova-scroll flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1" style={{ minHeight: 0 }}>
              {historyLoading ? (
                <HistorySkeleton />
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
                disabled={sending || !selectedProject}
                className="flex-1 rounded-2xl border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none placeholder:text-slate-500 disabled:opacity-50"
                placeholder={selectedProject ? 'Ask the assistant…' : 'Loading projects…'}
              />
              <Button onClick={handleSend} disabled={sending || !input.trim() || !selectedProject}>
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