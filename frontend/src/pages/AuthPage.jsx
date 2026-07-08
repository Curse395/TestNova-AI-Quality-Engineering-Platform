import { useState } from 'react'
import { Link } from 'react-router-dom'
import Button from '../components/ui/Button'
import FormField from '../components/ui/FormField'

const AuthPage = () => {
  const [mode, setMode] = useState('login')

  return (
    <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_rgba(14,165,233,0.2),_transparent_40%),linear-gradient(135deg,_#020617,_#111827)] px-4 py-10 text-slate-100">
      <div className="w-full max-w-5xl overflow-hidden rounded-[32px] border border-slate-800/80 bg-slate-900/80 shadow-2xl shadow-slate-950/60 backdrop-blur">
        <div className="grid lg:grid-cols-[1.1fr_0.9fr]">
          <div className="bg-gradient-to-br from-sky-500/20 via-slate-900 to-slate-950 p-8 lg:p-12">
            <p className="text-sm uppercase tracking-[0.35em] text-sky-400">TestNova AI</p>
            <h1 className="mt-4 text-4xl font-semibold text-white">Ship quality with AI-native confidence.</h1>
            <p className="mt-4 max-w-md text-lg text-slate-400">
              Centralize release health, automate test insight, and keep every release moving.
            </p>
            <div className="mt-8 rounded-3xl border border-slate-700/70 bg-slate-950/60 p-5 text-sm text-slate-300">
              <p className="font-semibold text-white">What teams love</p>
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
                onClick={() => setMode('login')}
              >
                Sign in
              </button>
              <button
                className={`flex-1 rounded-xl px-4 py-2 text-sm font-semibold ${mode === 'register' ? 'bg-sky-500 text-white' : 'text-slate-400'}`}
                onClick={() => setMode('register')}
              >
                Create account
              </button>
            </div>

            <form className="mt-7 space-y-4">
              {mode === 'register' && <FormField label="Full name" placeholder="Jordan Lee" />}
              <FormField label="Email" type="email" placeholder="you@company.com" />
              <FormField label="Password" type="password" placeholder="••••••••" />
              <Button className="w-full py-3">{mode === 'login' ? 'Sign in' : 'Create account'}</Button>
            </form>

            <p className="mt-6 text-center text-sm text-slate-500">
              {mode === 'login' ? 'Need a workspace?' : 'Already have an account?'}{' '}
              <Link to="/" className="text-sky-400">
                {mode === 'login' ? 'Request access' : 'Sign in'}
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AuthPage
