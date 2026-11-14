import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../components/ui/Button'
import FormField from '../components/ui/FormField'
import { apiClient, getApiErrorMessage } from '../api/client'

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
      <div className="w-full max-w-5xl overflow-hidden rounded-[32px] border border-slate-800/80 bg-slate-900/80 shadow-2xl shadow-slate-950/60 backdrop-blur">
        <div className="grid lg:grid-cols-[1.1fr_0.9fr]">
          <div className="bg-gradient-to-br from-sky-500/20 via-slate-900 to-slate-950 p-8 lg:p-12">
            <p className="text-sm uppercase tracking-[0.35em] text-sky-400">TestNova AI</p>
            <h1 className="mt-4 text-4xl font-semibold text-slate-100">Ship quality with AI-native confidence.</h1>
            <p className="mt-4 max-w-md text-lg text-slate-400">
              Centralize release health, automate test insight, and keep every release moving.
            </p>
            <div className="mt-8 rounded-3xl border border-slate-700/70 bg-slate-950/60 p-5 text-sm text-slate-300">
              <p className="font-semibold text-slate-100">What teams love</p>
              <ul className="mt-3 space-y-2 text-slate-400">
                <li>• Live quality landscape across every project</li>
                <li>• AI-assisted issue triage and summaries</li>
                <li>• One-click upload and artifact intelligence</li>
              </ul>
            </div>
          </div>

          <div className="p-8 lg:p-12">
            <div className="flex rounded-2xl border border-slate-800 bg-slate-950/70 p-1">
              <button
                className={`flex-1 rounded-xl px-4 py-2 text-sm font-semibold ${mode === 'login' ? 'bg-sky-500 text-white' : 'text-slate-400'}`}
                onClick={() => { setMode('login'); setError('') }}
              >
                Sign in
              </button>
              <button
                className={`flex-1 rounded-xl px-4 py-2 text-sm font-semibold ${mode === 'register' ? 'bg-sky-500 text-white' : 'text-slate-400'}`}
                onClick={() => { setMode('register'); setError('') }}
              >
                Create account
              </button>
            </div>

            <form className="mt-7 space-y-4" onSubmit={handleSubmit}>
              {mode === 'register' && (
                <>
                  <FormField label="Full name" name="name" placeholder="Jordan Lee" value={form.name} onChange={handleChange} required />
                  <FormField label="Workspace name" name="workspace_name" placeholder="Acme" value={form.workspace_name} onChange={handleChange} required />
                </>
              )}
              <FormField label="Email" type="email" name="email" placeholder="you@company.com" value={form.email} onChange={handleChange} required />
              <FormField label="Password" type="password" name="password" placeholder="••••••••" value={form.password} onChange={handleChange} required />
              {error && <p className="text-sm text-rose-400">{error}</p>}
              <Button className="w-full py-3" disabled={submitting}>
                {submitting ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
              </Button>
            </form>

            <p className="mt-6 text-center text-sm text-slate-500">
              {mode === 'login' ? 'Need a workspace?' : 'Already have an account?'}{' '}
              <button
                type="button"
                className="text-sky-400"
                onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}
              >
                {mode === 'login' ? 'Create an account' : 'Sign in'}
              </button>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AuthPage
