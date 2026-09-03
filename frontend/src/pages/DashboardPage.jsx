import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCircle2, Cpu, Sparkles, TrendingUp, AlertTriangle } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer, CartesianGrid, Tooltip, XAxis, YAxis, PieChart, Pie, Cell } from 'recharts'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import Modal from '../components/ui/Modal'
import { fetchDashboard, fetchDashboardInsights } from '../api/dashboard'

const PIE_COLORS = ['#38bdf8', '#818cf8', '#34d399', '#f59e0b']

const DashboardPage = () => {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const navigate = useNavigate()

  // Insights drawer state.
  const [insightsOpen, setInsightsOpen] = useState(false)
  const [insights, setInsights] = useState(null)
  const [insightsLoading, setInsightsLoading] = useState(false)
  const [insightsError, setInsightsError] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function loadDashboard() {
      try {
        const payload = await fetchDashboard()
        if (!cancelled) {
          setData(payload)
          setError(null)
        }
      } catch (err) {
        // No valid session (missing/expired token) → send the user to sign in.
        if (err?.response?.status === 401) {
          if (!cancelled) navigate('/login', { replace: true })
          return
        }
        if (!cancelled) {
          setError('We could not load your dashboard right now. Please try again.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadDashboard()
    return () => {
      cancelled = true
    }
  }, [navigate])

  const openInsights = async () => {
    setInsightsOpen(true)
    setInsights(null)
    setInsightsError(null)
    setInsightsLoading(true)
    try {
      const payload = await fetchDashboardInsights()
      setInsights(payload)
      setInsightsError(null)
    } catch (err) {
      if (err?.response?.status === 401) {
        navigate('/login', { replace: true })
        return
      }
      setInsightsError('We could not load your insights right now. Please try again.')
    } finally {
      setInsightsLoading(false)
    }
  }

  const closeInsights = () => {
    setInsightsOpen(false)
  }

  if (loading) {
    return <DashboardSkeleton />
  }

  if (error && !data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.16),_transparent_30%),#020617] p-4 text-slate-100">
        <div className="flex w-full max-w-md flex-col items-center gap-4 rounded-3xl border border-rose-500/30 bg-rose-500/10 p-8 text-center">
          <p className="text-sm text-rose-200">{error}</p>
          <Button variant="secondary" onClick={() => window.location.reload()}>
            Retry
          </Button>
        </div>
      </div>
    )
  }

  // Defensive fallback so the dashboard never reads from null data.
  const safeData = data || {
    active_projects: [],
    quality_center: { release_confidence: 0, recommendation: '', knowledge_health: 0, healthy_projects: 0, medium_risk_projects: 0, high_risk_projects: 0 },
    test_generation: { coverage_uplift: 0, flake_reduction: 0, time_saved_minutes: 0 },
    overview: { total_projects: 0, total_documents: 0, total_chunks: 0, total_embeddings: 0, overall_coverage: 0 },
    live_health: { healthy: 0, needs_review: 0, critical: 0 },
    knowledge_distribution: [],
    assistant: { suggestions: [] },
    performance_trend: [],
  }

  const overviewCards = [
    { label: 'Total Projects', value: safeData.overview.total_projects, tone: 'text-sky-400', icon: 'projects' },
    { label: 'Total Documents', value: safeData.overview.total_documents, tone: 'text-indigo-400', icon: 'documents' },
    { label: 'Total Chunks', value: safeData.overview.total_chunks, tone: 'text-violet-400', icon: 'chunks' },
    { label: 'Total Embeddings', value: safeData.overview.total_embeddings, tone: 'text-emerald-400', icon: 'embeddings' },
    { label: 'Overall Coverage', value: `${safeData.overview.overall_coverage}%`, tone: 'text-cyan-400', icon: 'coverage' },
  ]

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.16),_transparent_30%),#020617] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="Release Intelligence" subtitle="Overview" />

        {error && (
          <div className="flex items-center justify-between gap-4 rounded-3xl border border-rose-500/30 bg-rose-500/10 px-5 py-4 text-sm text-rose-200">
            <span>{error}</span>
            <Button variant="secondary" onClick={() => window.location.reload()}>
              Retry
            </Button>
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {overviewCards.map((card) => (
            <Card key={card.label} className="!p-4">
              <div className="flex items-center justify-between">
                <p className="text-xs text-slate-400">{card.label}</p>
                <OverviewIcon name={card.icon} />
              </div>
              <p className={`mt-3 text-2xl font-semibold ${card.tone}`}>{card.value}</p>
            </Card>
          ))}
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.5fr_0.8fr]">
          <Card title="Quality command center" subtitle="Your AI-assisted release signal is improving daily." className="overflow-hidden">
            <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
              <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-slate-400">Release confidence</p>
                    <p className="mt-2 text-4xl font-semibold text-white">{safeData.quality_center.release_confidence}%</p>
                  </div>
                  <div className="rounded-2xl bg-emerald-500/10 p-3 text-emerald-400">
                    <CheckCircle2 size={24} />
                  </div>
                </div>
                <p className="mt-4 text-sm text-slate-400">{safeData.quality_center.recommendation}</p>
                <div className="mt-5 flex gap-3">
                  <Button onClick={openInsights} disabled={insightsLoading}>
                    {insightsLoading ? 'Loading…' : 'View insights'}
                  </Button>
                  <Button variant="secondary">Share report</Button>
                </div>
              </div>
              <div className="rounded-3xl border border-slate-800 bg-gradient-to-br from-sky-500/10 to-slate-950/80 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-slate-400">Autopilot</p>
                    <p className="text-lg font-semibold text-white">Test generation</p>
                  </div>
                  <Sparkles className="text-sky-400" size={18} />
                </div>
                <div className="mt-5 space-y-3 text-sm text-slate-300">
                  <div className="flex items-center justify-between rounded-2xl bg-slate-900/80 p-3">
                    <span>Coverage uplift</span><span className="text-emerald-400">+{safeData.test_generation.coverage_uplift}%</span>
                  </div>
                  <div className="flex items-center justify-between rounded-2xl bg-slate-900/80 p-3">
                    <span>Flake reduction</span><span className="text-sky-400">-{safeData.test_generation.flake_reduction}%</span>
                  </div>
                  <div className="flex items-center justify-between rounded-2xl bg-slate-900/80 p-3">
                    <span>Time saved</span><span className="text-violet-400">{safeData.test_generation.time_saved_minutes}m</span>
                  </div>
                </div>
              </div>
            </div>
          </Card>

          <Card title="Live health" subtitle="Top priority signals">
            <div className="space-y-3">
              {[
                { label: 'Healthy', value: safeData.live_health.healthy, tone: 'text-emerald-400' },
                { label: 'Needs review', value: safeData.live_health.needs_review, tone: 'text-amber-400' },
                { label: 'Critical', value: safeData.live_health.critical, tone: 'text-rose-400' },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between rounded-2xl bg-slate-950/70 px-3 py-3">
                  <span className="text-sm text-slate-400">{item.label}</span>
                  <span className={`text-lg font-semibold ${item.tone}`}>{item.value}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
          <Card title="Performance trend" subtitle="Coverage and execution speed over time" className="h-full">
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={safeData.performance_trend}>
                  <CartesianGrid stroke="#1e293b" vertical={false} />
                  <XAxis dataKey="date" stroke="#64748b" tickFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} />
                  <YAxis stroke="#64748b" />
                  <Tooltip />
                  <Line type="monotone" dataKey="documents" stroke="#38bdf8" strokeWidth={3} dot={{ r: 4 }} />
                  <Line type="monotone" dataKey="chunks" stroke="#a78bfa" strokeWidth={3} dot={{ r: 4 }} />
                  <Line type="monotone" dataKey="embeddings" stroke="#34d399" strokeWidth={3} dot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title="Knowledge Distribution" subtitle="Embedded knowledge across the workspace">
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={safeData.knowledge_distribution}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={60}
                    outerRadius={95}
                    paddingAngle={3}
                  >
                    {safeData.knowledge_distribution.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <Card title="Active projects" subtitle="Release readiness across current workstreams" action={<Button variant="ghost">See all</Button>}>
            <div className="space-y-3">
              {safeData.active_projects.length === 0 ? (
                <p className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
                  No active projects yet.
                </p>
              ) : (
                safeData.active_projects.map((project) => (
                  <div key={project.id} className="flex items-center justify-between rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-3">
                    <div>
                      <p className="font-medium text-slate-100">{project.name}</p>
                      <p className="text-sm text-slate-400">{project.documents} documents · {project.chunks} chunks</p>
                    </div>
                    <div className="text-right">
                      <p className={`text-sm ${project.status === 'Healthy' ? 'text-emerald-400' : project.status === 'Needs Review' ? 'text-amber-400' : 'text-rose-400'}`}>{project.status}</p>
                      <p className="text-sm text-slate-400">{project.embedding_coverage}% coverage</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>

          <Card title="AI assistant snapshot" subtitle="Suggested actions" action={<Button variant="ghost">Open chat</Button>}>
            <div className="space-y-3">
              {safeData.assistant.suggestions.length === 0 ? (
                <p className="rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-6 text-center text-sm text-slate-400">
                  No suggestions right now.
                </p>
              ) : (
                safeData.assistant.suggestions.map((suggestion, index) => (
                  <div key={index} className="flex items-start gap-3 rounded-2xl border border-slate-800 bg-slate-950/70 p-3">
                    <div className="rounded-xl bg-sky-500/10 p-2 text-sky-400"><Cpu size={16} /></div>
                    <div>
                      <p className="text-sm font-semibold text-slate-100">{suggestion}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>

        <InsightsModal
          open={insightsOpen}
          onClose={closeInsights}
          loading={insightsLoading}
          error={insightsError}
          insights={insights}
          onRetry={openInsights}
        />
      </div>
    </div>
  )
}

const OverviewIcon = ({ name }) => {
  const icons = {
    projects: <CheckCircle2 size={16} className="text-sky-400" />,
    documents: <Cpu size={16} className="text-indigo-400" />,
    chunks: <Cpu size={16} className="text-violet-400" />,
    embeddings: <Sparkles size={16} className="text-emerald-400" />,
    coverage: <TrendingUp size={16} className="text-cyan-400" />,
  }
  return icons[name] || null
}

const InsightsModal = ({ open, onClose, loading, error, insights, onRetry }) => {
  return (
    <Modal open={open} onClose={onClose} title="Release Insights" subtitle="AI-powered analysis of your workspace readiness">
      {loading ? (
        <div className="space-y-4">
          <div className="h-24 animate-pulse rounded-2xl bg-slate-800/70" />
          <div className="h-32 animate-pulse rounded-2xl bg-slate-800/70" />
          <div className="h-24 animate-pulse rounded-2xl bg-slate-800/70" />
        </div>
      ) : error ? (
        <div className="flex flex-col items-center gap-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-5 py-6 text-center">
          <p className="text-sm text-rose-200">{error}</p>
          <Button variant="secondary" onClick={onRetry}>Retry</Button>
        </div>
      ) : insights ? (
        <div className="space-y-5">
          {/* Release Confidence */}
          <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
            <p className="text-xs text-slate-400">Release Confidence</p>
            <p className="mt-1 text-3xl font-semibold text-white">{insights.release_confidence}%</p>
          </div>

          {/* Summary */}
          <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Summary</p>
            <p className="mt-2 text-sm text-slate-200">{insights.summary}</p>
          </div>

          {/* Issues */}
          {insights.issues.length > 0 && (
            <div>
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Issues</p>
              <div className="space-y-3">
                {insights.issues.map((issue, idx) => (
                  <IssueRow key={idx} issue={issue} />
                ))}
              </div>
            </div>
          )}

          {/* Recommendations */}
          {insights.recommendations.length > 0 && (
            <div>
              <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Recommendations</p>
              <ul className="space-y-2">
                {insights.recommendations.map((rec, idx) => (
                  <li
                    key={idx}
                    className="flex items-start gap-3 rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-sm text-slate-200"
                  >
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-sky-400" />
                    {rec}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Estimated confidence after fix */}
          <div className="flex items-center justify-between rounded-2xl border border-emerald-500/20 bg-emerald-500/10 p-4">
            <div className="flex items-center gap-3">
              <TrendingUp className="text-emerald-400" size={20} />
              <span className="text-sm text-emerald-200">Estimated confidence after fix</span>
            </div>
            <span className="text-2xl font-semibold text-emerald-300">{insights.estimated_confidence_after_fix}%</span>
          </div>
        </div>
      ) : null}
    </Modal>
  )
}

const IssueRow = ({ issue }) => {
  const severityColor =
    issue.severity === 'High'
      ? 'text-rose-400 bg-rose-500/10'
      : issue.severity === 'Medium'
      ? 'text-amber-400 bg-amber-500/10'
      : 'text-sky-400 bg-sky-500/10'
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
      <AlertTriangle className="mt-0.5 shrink-0 text-amber-400" size={18} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-semibold text-slate-100">{issue.title}</p>
          <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${severityColor}`}>{issue.severity}</span>
        </div>
        <p className="mt-1 text-sm text-slate-400">{issue.description}</p>
      </div>
    </div>
  )
}

const SkeletonBlock = ({ className = '' }) => (
  <div className={`animate-pulse rounded-2xl bg-slate-800/60 ${className}`} />
)

const DashboardSkeleton = () => {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.16),_transparent_30%),#020617] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        {/* Navbar skeleton */}
        <div className="flex items-center justify-between rounded-3xl border border-slate-800/80 bg-slate-900/70 px-5 py-4">
          <div className="space-y-2">
            <SkeletonBlock className="h-3 w-24" />
            <SkeletonBlock className="h-5 w-40" />
          </div>
          <div className="flex gap-2">
            <SkeletonBlock className="h-9 w-28" />
            <SkeletonBlock className="h-9 w-9" />
          </div>
        </div>

        {/* Overview cards skeleton */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="rounded-3xl border border-slate-800/80 bg-slate-900/70 p-4">
              <SkeletonBlock className="h-3 w-20" />
              <SkeletonBlock className="mt-3 h-7 w-14" />
            </div>
          ))}
        </div>

        {/* Top row skeleton */}
        <div className="grid gap-6 xl:grid-cols-[1.5fr_0.8fr]">
          <SkeletonBlock className="h-56" />
          <SkeletonBlock className="h-56" />
        </div>

        {/* Charts row skeleton */}
        <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
          <SkeletonBlock className="h-72" />
          <SkeletonBlock className="h-72" />
        </div>

        {/* Bottom row skeleton */}
        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <SkeletonBlock className="h-56" />
          <SkeletonBlock className="h-56" />
        </div>
      </div>
    </div>
  )
}

export default DashboardPage
