import { Bell, Search, Sparkles } from 'lucide-react'
import Button from '../ui/Button'

const Navbar = ({ title, subtitle }) => {
  return (
    <header className="flex items-center justify-between rounded-3xl border border-slate-800/80 bg-slate-900/70 px-5 py-4 shadow-[0_20px_45px_-25px_rgba(0,0,0,0.75)] backdrop-blur">
      <div>
        <p className="text-sm text-slate-400">{subtitle}</p>
        <h1 className="text-xl font-semibold text-white">{title}</h1>
      </div>

      <div className="flex items-center gap-3">
        <label className="hidden items-center gap-2 rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-sm text-slate-400 md:flex">
          <Search size={16} />
          <input placeholder="Search workspace" className="bg-transparent outline-none" />
        </label>
        <button className="rounded-2xl border border-slate-800 bg-slate-950/70 p-2 text-slate-300">
          <Bell size={16} />
        </button>
        <Button className="gap-2">
          <Sparkles size={16} />
          New run
        </Button>
      </div>
    </header>
  )
}

export default Navbar
