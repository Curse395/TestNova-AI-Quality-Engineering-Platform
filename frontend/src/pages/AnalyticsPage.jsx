import { BarChart, Bar, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import { performanceData } from '../data/mockData'

const AnalyticsPage = () => {
  return (
    <div className="min-h-screen bg-[#020617] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="Quality Analytics" subtitle="Insights" />
        <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <Card title="Execution performance" subtitle="Coverage vs. execution speed">
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={performanceData}>
                  <CartesianGrid stroke="#1e293b" vertical={false} />
                  <XAxis dataKey="name" stroke="#64748b" />
                  <YAxis stroke="#64748b" />
                  <Tooltip />
                  <Bar dataKey="coverage" fill="#38bdf8" radius={[8, 8, 0, 0]} />
                  <Bar dataKey="speed" fill="#818cf8" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title="Key metrics" subtitle="Signal summary for this quarter">
            <div className="space-y-3 text-sm text-slate-300">
              <div className="rounded-2xl bg-slate-950/70 p-3"><span className="text-slate-400">Flake rate</span><p className="mt-1 text-xl font-semibold text-white">2.4%</p></div>
              <div className="rounded-2xl bg-slate-950/70 p-3"><span className="text-slate-400">Test pass rate</span><p className="mt-1 text-xl font-semibold text-white">97.8%</p></div>
              <div className="rounded-2xl bg-slate-950/70 p-3"><span className="text-slate-400">Avg. triage time</span><p className="mt-1 text-xl font-semibold text-white">11 min</p></div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

export default AnalyticsPage
