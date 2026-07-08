import { ArrowUpRight, CheckCircle2, Cpu, Sparkles, Zap } from 'lucide-react'
import { LineChart, Line, ResponsiveContainer, BarChart, Bar, CartesianGrid, Tooltip, XAxis, YAxis, PieChart, Pie, Cell } from 'recharts'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { performanceData, bugTrendData, projects } from '../data/mockData'

const DashboardPage = () => {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.16),_transparent_30%),#020617] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="Release Intelligence" subtitle="Overview" />

        <div className="grid gap-6 xl:grid-cols-[1.5fr_0.8fr]">
          <Card title="Quality command center" subtitle="Your AI-assisted release signal is improving daily." className="overflow-hidden">
            <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
              <div className="rounded-3xl border border-slate-800 bg-slate-950/70 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-slate-400">Release confidence</p>
                    <p className="mt-2 text-4xl font-semibold text-white">96%</p>
                  </div>
                  <div className="rounded-2xl bg-emerald-500/10 p-3 text-emerald-400">
                    <CheckCircle2 size={24} />
                  </div>
                </div>
                <p className="mt-4 text-sm text-slate-400">AI detected 3 high-risk clusters and recommended fixes before the next rollout.</p>
                <div className="mt-5 flex gap-3">
                  <Button>View insights</Button>
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
                    <span>Coverage uplift</span><span className="text-emerald-400">+11%</span>
                  </div>
                  <div className="flex items-center justify-between rounded-2xl bg-slate-900/80 p-3">
                    <span>Flake reduction</span><span className="text-sky-400">-22%</span>
                  </div>
                  <div className="flex items-center justify-between rounded-2xl bg-slate-900/80 p-3">
                    <span>Time saved</span><span className="text-violet-400">8.2h</span>
                  </div>
                </div>
              </div>
            </div>
          </Card>

          <Card title="Live health" subtitle="Top priority signals">
            <div className="space-y-3">
              {[
                { label: 'Critical regressions', value: '4', tone: 'text-rose-400' },
                { label: 'Pending reviews', value: '12', tone: 'text-amber-400' },
                { label: 'AI suggestions', value: '27', tone: 'text-sky-400' },
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
                <LineChart data={performanceData}>
                  <CartesianGrid stroke="#1e293b" vertical={false} />
                  <XAxis dataKey="name" stroke="#64748b" />
                  <YAxis stroke="#64748b" />
                  <Tooltip />
                  <Line type="monotone" dataKey="coverage" stroke="#38bdf8" strokeWidth={3} dot={{ r: 4 }} />
                  <Line type="monotone" dataKey="speed" stroke="#a78bfa" strokeWidth={3} dot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title="Risk by area" subtitle="Recent issue distribution">
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={bugTrendData} dataKey="value" nameKey="name" innerRadius={60} outerRadius={95} paddingAngle={3}>
                    <Cell fill="#38bdf8" />
                    <Cell fill="#818cf8" />
                    <Cell fill="#34d399" />
                    <Cell fill="#f59e0b" />
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
              {projects.map((project) => (
                <div key={project.name} className="flex items-center justify-between rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-3">
                  <div>
                    <p className="font-medium text-slate-100">{project.name}</p>
                    <p className="text-sm text-slate-400">Owner {project.owner}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-emerald-400">{project.status}</p>
                    <p className="text-sm text-slate-400">{project.progress}</p>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card title="AI assistant snapshot" subtitle="Suggested actions" action={<Button variant="ghost">Open chat</Button>}>
            <div className="space-y-3">
              {[
                { title: 'Prioritize flaky suites', detail: 'Reduce retry noise by 15%' },
                { title: 'Upload new builds', detail: '4 artifacts waiting for review' },
                { title: 'Draft release note', detail: 'Auto-generated from latest results' },
              ].map((item) => (
                <div key={item.title} className="flex items-start gap-3 rounded-2xl border border-slate-800 bg-slate-950/70 p-3">
                  <div className="rounded-xl bg-sky-500/10 p-2 text-sky-400"><Cpu size={16} /></div>
                  <div>
                    <p className="text-sm font-semibold text-slate-100">{item.title}</p>
                    <p className="text-sm text-slate-400">{item.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

export default DashboardPage
