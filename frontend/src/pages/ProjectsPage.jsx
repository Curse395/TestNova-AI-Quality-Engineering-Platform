import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { projects } from '../data/mockData'

const ProjectsPage = () => {
  return (
    <div className="min-h-screen bg-[#020617] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="Projects" subtitle="Portfolio" />
        <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <Card title="Portfolio" subtitle="Track delivery quality and rollout readiness." action={<Button variant="secondary">New project</Button>}>
            <div className="space-y-3">
              {projects.map((project) => (
                <div key={project.name} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-semibold text-white">{project.name}</p>
                      <p className="text-sm text-slate-400">Owner {project.owner}</p>
                    </div>
                    <span className="rounded-full bg-emerald-500/10 px-3 py-1 text-sm text-emerald-400">{project.status}</span>
                  </div>
                  <div className="mt-3 h-2 rounded-full bg-slate-800">
                    <div className="h-2 rounded-full bg-sky-400" style={{ width: project.progress }} />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Delivery notes" subtitle="Focus areas for the next sprint">
            <div className="space-y-3 text-sm text-slate-300">
              <div className="rounded-2xl bg-slate-950/70 p-3">Strengthen smoke coverage for mobile checkout.</div>
              <div className="rounded-2xl bg-slate-950/70 p-3">Monitor API latency before the next release candidate.</div>
              <div className="rounded-2xl bg-slate-950/70 p-3">Automate regression review for billing flows.</div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

export default ProjectsPage
