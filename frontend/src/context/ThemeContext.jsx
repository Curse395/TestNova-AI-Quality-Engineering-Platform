import { useCallback, useMemo, useState } from 'react'
import ThemeContext from './themeContext'

function initialTheme() {
  const savedTheme = localStorage.getItem('testnova-theme')
  if (savedTheme === 'light' || savedTheme === 'dark') return savedTheme
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(initialTheme)

  const toggleTheme = useCallback(() => {
    const nextTheme = theme === 'dark' ? 'light' : 'dark'
    localStorage.setItem('testnova-theme', nextTheme)
    document.documentElement.dataset.theme = nextTheme
    setTheme(nextTheme)
  }, [theme])

  const value = useMemo(() => ({ theme, toggleTheme }), [theme, toggleTheme])

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
