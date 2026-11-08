import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import Sidebar from './components/layout/Sidebar'
import AuthPage from './pages/AuthPage'
import DashboardPage from './pages/DashboardPage'
import ProjectsPage from './pages/ProjectsPage'
import UploadPage from './pages/UploadPage'
import AnalyticsPage from './pages/AnalyticsPage'
import AssistantPage from './pages/AssistantPage'

function AppShell({ children }) {
  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <Sidebar />
      <main className="flex-1">{children}</main>
    </div>
  )
}

function RequireAuth({ children }) {
  const navigate = useNavigate()

  useEffect(() => {
    const handleUnauthorized = () => navigate('/login', { replace: true })
    window.addEventListener('testnova:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('testnova:unauthorized', handleUnauthorized)
  }, [navigate])

  if (!localStorage.getItem('access_token')) {
    return <Navigate to="/login" replace />
  }
  return children
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<AuthPage />} />
        <Route
          path="/*"
          element={
            <RequireAuth>
              <AppShell>
                <Routes>
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/projects" element={<ProjectsPage />} />
                  <Route path="/upload" element={<UploadPage />} />
                  <Route path="/analytics" element={<AnalyticsPage />} />
                  <Route path="/assistant" element={<AssistantPage />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </AppShell>
            </RequireAuth>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}

export default App
