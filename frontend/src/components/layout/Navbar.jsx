import { useEffect, useRef, useState } from 'react'
import { ChevronRight, LogOut, Moon, Sun, UserRound } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { useTheme } from '../../context/useTheme'
import { clearDashboardCache } from '../../api/dashboard'

const Navbar = ({ title, subtitle }) => {
  const { theme, toggleTheme } = useTheme()
  const [profileOpen, setProfileOpen] = useState(false)
  const profileRef = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!profileOpen) return undefined

    const closeOnOutsideClick = (event) => {
      if (!profileRef.current?.contains(event.target)) setProfileOpen(false)
    }
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setProfileOpen(false)
    }

    document.addEventListener('pointerdown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [profileOpen])

  const handleSignOut = () => {
    localStorage.removeItem('access_token')
    clearDashboardCache()
    navigate('/login', { replace: true })
  }

  return (
    <header className="app-header">
      <div className="app-header-copy">
        <nav className="app-header-subtitle" aria-label="Breadcrumb">
          <Link to="/" className="breadcrumb-link">TestNova AI</Link>
          <ChevronRight size={12} aria-hidden="true" />
          <span>{subtitle || title}</span>
        </nav>
        <h1 className="app-header-title">{title}</h1>
      </div>

      <div className="app-header-actions">
        <button
          type="button"
          className="icon-action"
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
        >
          {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
        </button>
        <div className="profile-menu" ref={profileRef}>
          <button
            type="button"
            className="profile-action"
            aria-label="Open profile menu"
            aria-haspopup="menu"
            aria-expanded={profileOpen}
            aria-controls="profile-menu"
            onClick={() => setProfileOpen((open) => !open)}
          >
            <UserRound size={17} aria-hidden="true" />
          </button>
          {profileOpen && (
            <div className="profile-dropdown" id="profile-menu" role="menu" aria-label="Profile menu">
              <p className="profile-menu-title">Account</p>
              <p className="profile-menu-description">Signed in to TestNova AI</p>
              <button type="button" className="profile-signout" role="menuitem" onClick={handleSignOut}>
                <LogOut size={15} aria-hidden="true" />
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

export default Navbar
