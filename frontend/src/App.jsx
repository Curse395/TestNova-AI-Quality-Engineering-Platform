import { lazy, Suspense, useEffect } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import Sidebar from './components/layout/Sidebar'
import './App.css'

const AuthPage = lazy(() => import('./pages/AuthPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ProjectsPage = lazy(() => import('./pages/ProjectsPage'))
const UploadPage = lazy(() => import('./pages/UploadPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const AssistantPage = lazy(() => import('./pages/AssistantPage'))
const TestCasesPage = lazy(() => import('./pages/TestCasesPage'))
const WorkflowsPage = lazy(() => import('./pages/WorkflowsPage'))
const ReleaseReadinessPage = lazy(() => import('./pages/ReleaseReadinessPage'))

function RouteLoading() {
  return (
    <div className="route-loading" role="status" aria-label="Loading workspace">
      <span className="route-loading-mark" />
      <span>Opening workspace</span>
    </div>
  )
}

function AppShell({ children }) {
  const { pathname } = useLocation()
  const reduceMotion = useReducedMotion()

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-workspace" id="main-workspace">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={pathname}
            className="workspace-route"
            initial={reduceMotion ? false : { opacity: 0, y: 7 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? undefined : { opacity: 0, y: -4 }}
            transition={{ duration: reduceMotion ? 0 : 0.18, ease: [0.2, 0.65, 0.3, 1] }}
          >
            <Suspense fallback={<RouteLoading />}>{children}</Suspense>
          </motion.div>
        </AnimatePresence>
      </main>
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
        <Route path="/login" element={<Suspense fallback={<RouteLoading />}><AuthPage /></Suspense>} />
        <Route
          path="/*"
          element={
            <RequireAuth>
              <AppShell>
                <Routes>
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/projects" element={<ProjectsPage />} />
                  <Route path="/upload" element={<UploadPage />} />
                  <Route path="/test-cases" element={<TestCasesPage />} />
                  <Route path="/workflows" element={<WorkflowsPage />} />
                  <Route path="/analytics" element={<AnalyticsPage />} />
                  <Route path="/release-readiness" element={<ReleaseReadinessPage />} />
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
