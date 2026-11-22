import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Activity, ArrowRight, GitBranch, ShieldCheck, Sparkles } from 'lucide-react'
import Button from '../components/ui/Button'
import FormField from '../components/ui/FormField'
import { apiClient, getApiErrorMessage } from '../api/client'
import { clearDashboardCache } from '../api/dashboard'

const AuthPage = () => {
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ name: '', email: '', password: '', workspace_name: '' })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const handleChange = (e) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const endpoint = mode === 'login' ? '/auth/login' : '/auth/register'
      const payload =
        mode === 'login'
          ? { email: form.email, password: form.password }
          : { name: form.name, email: form.email, password: form.password, workspace_name: form.workspace_name }

      let res = await apiClient.post(endpoint, payload)
      if (mode === 'register') {
        res = await apiClient.post('/auth/login', {
          email: form.email,
          password: form.password,
        })
      }
      const token = res.data.access_token || res.data?.data?.access_token
      if (token) {
        clearDashboardCache()
        localStorage.setItem('access_token', token)
      } else {
        throw new Error('Authentication response did not contain an access token.')
      }
      navigate('/')
    } catch (err) {
      setError(getApiErrorMessage(err, 'Something went wrong. Please try again.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page flex min-h-screen items-center justify-center px-4 py-10 text-slate-100">
      <div className="auth-frame">
        <section className="auth-story" aria-labelledby="auth-story-heading">
          <div className="auth-story-topline">
            <div className="brand-mark" aria-hidden="true"><Activity size={19} /></div>
            <span>TestNova <span className="text-sky-500">AI</span></span>
            <span className="auth-story-divider" />
            <span className="auth-story-caption">Agentic quality system</span>
          </div>

          <div className="auth-story-copy">
            <p className="mission-kicker"><Sparkles size={13} /> Quality, in motion</p>
            <h1 id="auth-story-heading">Let your QA agents do the heavy lifting.</h1>
            <p>One connected system to turn product evidence into tested changes and release confidence.</p>
          </div>

          <div className="auth-agent-loop" aria-label="Agent workflow: understand, validate, and report">
            <div className="auth-loop-heading">
              <span>THE QUALITY LOOP</span>
              <span>Evidence to confidence</span>
            </div>
            <div className="auth-loop-steps">
              <div className="auth-loop-step">
                <span className="auth-loop-icon"><GitBranch size={16} /></span>
                <span><strong>Understand</strong><small>Product context</small></span>
              </div>
              <span className="auth-loop-connector" aria-hidden="true" />
              <div className="auth-loop-step">
                <span className="auth-loop-icon"><Activity size={16} /></span>
                <span><strong>Validate</strong><small>Agent workflows</small></span>
              </div>
              <span className="auth-loop-connector" aria-hidden="true" />
              <div className="auth-loop-step">
                <span className="auth-loop-icon"><ShieldCheck size={16} /></span>
                <span><strong>Decide</strong><small>Release readiness</small></span>
              </div>
            </div>
          </div>

          <p className="auth-story-footnote">Every decision stays connected to its evidence.</p>
        </section>

        <section className="auth-form-panel" aria-label={mode === 'login' ? 'Sign in' : 'Create account'}>
            <div className="auth-form-heading">
              <p className="auth-form-eyebrow">YOUR WORKSPACE</p>
              <h2>{mode === 'login' ? 'Welcome back' : 'Create your workspace'}</h2>
              <p>{mode === 'login' ? 'Pick up where your quality workflow left off.' : 'Bring your team and quality workflows together.'}</p>
            </div>

            <div className="auth-mode-switch" role="group" aria-label="Account action">
              <button
                type="button"
                aria-pressed={mode === 'login'}
                className={`auth-mode-button ${mode === 'login' ? 'is-active' : ''}`}
                onClick={() => { setMode('login'); setError('') }}
              >
                Sign in
              </button>
              <button
                type="button"
                aria-pressed={mode === 'register'}
                className={`auth-mode-button ${mode === 'register' ? 'is-active' : ''}`}
                onClick={() => { setMode('register'); setError('') }}
              >
                Create account
              </button>
            </div>

            <form className="auth-form" onSubmit={handleSubmit}>
              {mode === 'register' && (
                <>
                  <FormField label="Full name" name="name" placeholder="Jordan Lee" value={form.name} onChange={handleChange} required />
                  <FormField label="Workspace name" name="workspace_name" placeholder="Acme" value={form.workspace_name} onChange={handleChange} required />
                </>
              )}
              <FormField label="Email" type="email" name="email" placeholder="you@company.com" value={form.email} onChange={handleChange} required />
              <FormField label="Password" type="password" name="password" placeholder="••••••••" value={form.password} onChange={handleChange} required />
              {error && <p className="auth-error" role="alert">{error}</p>}
              <Button className="auth-submit w-full py-3" disabled={submitting}>
                <span>{submitting ? 'Please wait…' : mode === 'login' ? 'Sign in to TestNova' : 'Create workspace'}</span>
                {!submitting && <ArrowRight size={16} aria-hidden="true" />}
              </Button>
            </form>

            <p className="auth-form-footnote">Secure access to your quality workspace.</p>
        </section>
      </div>
    </div>
  )
}

export default AuthPage
