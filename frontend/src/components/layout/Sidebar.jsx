import { NavLink } from 'react-router-dom'
import { Activity, ArrowUpRight, Bot, BarChart3, ClipboardCheck, FolderKanban, LayoutGrid, ShieldCheck, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'
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
  return (
    <aside className="app-sidebar" aria-label="Primary navigation">
      <div className="sidebar-brand">
        <div className="brand-mark" aria-hidden="true">
          <Activity size={20} strokeWidth={2.2} />
        </div>
        <div>
          <p className="text-sm font-semibold tracking-tight text-slate-100">TestNova <span className="text-sky-500">AI</span></p>
          <p className="mt-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-400">Agentic quality system</p>
        </div>
      </div>

      <nav className="sidebar-nav">
        <p className="sidebar-section-label">Workspace</p>
        {navItems.map((item) => {
          const Icon = icons[item.icon]
          return (
            <NavLink
              key={item.href}
              to={item.href}
              end={item.href === '/'}
              className="sidebar-link"
              title={item.label}
              aria-label={item.label}
            >
              <Icon size={17} aria-hidden="true" />
              <span className="sidebar-label">{item.label}</span>
            </NavLink>
          )
        })}
      </nav>

      <div className="sidebar-footer">
        <p className="text-xs font-medium text-slate-400">Connected quality loop</p>
        <p className="mt-1.5 text-xs leading-relaxed text-slate-500">Evidence, agents and release signals stay in context.</p>
        <Link to="/assistant" className="sidebar-assistant-link">
          <span className="sidebar-assistant-icon"><Bot size={15} aria-hidden="true" /></span>
          <span>Ask the AI assistant</span>
          <ArrowUpRight size={14} aria-hidden="true" />
        </Link>
      </div>
    </aside>
  )
}

export default Sidebar
