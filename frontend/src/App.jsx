import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
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

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<AuthPage />} />
        <Route
          path="/*"
          element={
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
          }
        />
      </Routes>
    </BrowserRouter>
  )
}

export default App
