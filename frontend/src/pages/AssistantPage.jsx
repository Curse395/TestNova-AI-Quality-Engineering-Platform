import Navbar from '../components/layout/Navbar'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { messages } from '../data/mockData'

const AssistantPage = () => {
  return (
    <div className="min-h-screen bg-[#020617] p-4 text-slate-100 lg:p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <Navbar title="AI Assistant" subtitle="Copilot" />
        <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
          <Card title="Live workspace" subtitle="Suggested next actions">
            <div className="space-y-3 text-sm text-slate-300">
              <div className="rounded-2xl bg-slate-950/70 p-3">Summarize the latest regression cluster from mobile checkout.</div>
              <div className="rounded-2xl bg-slate-950/70 p-3">Generate release notes based on the last 3 builds.</div>
              <div className="rounded-2xl bg-slate-950/70 p-3">Draft a triage plan for the billing flow issue.</div>
            </div>
          </Card>

          <Card title="Conversation" subtitle="AI-powered support for quality teams" action={<Button variant="secondary">New thread</Button>}>
            <div className="space-y-3">
              {messages.map((message) => (
                <div key={`${message.from}-${message.text}`} className={`rounded-2xl p-3 text-sm ${message.from === 'assistant' ? 'bg-sky-500/10 text-slate-100' : 'bg-slate-950/70 text-slate-300'}`}>
                  <p className="mb-1 text-xs uppercase tracking-[0.25em] text-slate-500">{message.from}</p>
                  <p>{message.text}</p>
                </div>
              ))}
            </div>
            <div className="mt-4 flex gap-3">
              <input className="flex-1 rounded-2xl border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none" placeholder="Ask the assistant..." />
              <Button>Send</Button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

export default AssistantPage
