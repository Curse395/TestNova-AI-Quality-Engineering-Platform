import { NavLink, useNavigate } from 'react-router-dom'
import { Activity, Bot, BarChart3, ClipboardCheck, FolderKanban, LayoutGrid, LogOut, ShieldCheck, Upload } from 'lucide-react'
import Button from '../ui/Button'
import { navItems } from '../../data/navigation'

const icons = {
  LayoutGrid,
  FolderKanban,
  Upload,
  BarChart3,
  ClipboardCheck,
  Bot,
  Activity,
  ShieldCheck,
}

const Sidebar = () => {
  const navigate = useNavigate()

  const handleLogout = () => {
    localStorage.removeItem('access_token')
    navigate('/login', { replace: true })
  }

  return (
    <aside className="hidden w-72 flex-col border-r border-slate-800/80 bg-slate-950/80 px-6 py-8 lg:flex">
      <div className="mb-10">
        <p className="text-sm uppercase tracking-[0.35em] text-sky-400">TestNova AI</p>
        <h2 className="mt-2 text-2xl font-semibold text-white">Quality Engineering</h2>
      </div>

      <nav className="space-y-2">
        {navItems.map((item) => {
          const Icon = icons[item.icon]
          return (
            <NavLink
              key={item.href}
              to={item.href}
              end={item.href === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-2xl px-3 py-3 text-sm font-medium transition ${
                  isActive
                    ? 'bg-slate-800 text-white shadow-lg shadow-slate-900/40'
                    : 'text-slate-400 hover:bg-slate-900 hover:text-slate-100'
                }`
              }
            >
              <Icon size={18} />
              {item.label}
            </NavLink>
          )
        })}
      </nav>

      <div className="mt-auto rounded-3xl border border-sky-500/20 bg-sky-500/10 p-4">
        <p className="text-sm font-semibold text-sky-200">Workspace insights</p>
        <p className="mt-1 text-sm text-slate-400">Review document processing and embedding health.</p>
      </div>
      <Button variant="ghost" className="mt-4 justify-start gap-3" onClick={handleLogout}>
        <LogOut size={18} />
        Sign out
      </Button>
    </aside>
  )
}

export default Sidebar
