const Button = ({ children, variant = 'primary', className = '', ...props }) => {
  const base = 'inline-flex items-center justify-center rounded-2xl px-4 py-2 text-sm font-semibold transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-sky-400/60'
  const variants = {
    primary: 'bg-sky-500 text-white hover:bg-sky-400 shadow-lg shadow-sky-500/20',
    secondary: 'bg-slate-800/80 text-slate-100 hover:bg-slate-700 border border-slate-700',
    ghost: 'bg-transparent text-slate-300 hover:bg-slate-800/70',
  }

  return (
    <button className={`ui-button ${base} ${variants[variant]} ${className}`} data-variant={variant} {...props}>
      {children}
    </button>
  )
}

export default Button
