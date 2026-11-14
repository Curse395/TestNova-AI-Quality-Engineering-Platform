const Card = ({ title, subtitle, children, className = '', action, style }) => (
  <section className={`surface-card rounded-3xl border border-slate-800/80 bg-slate-900/70 p-5 shadow-[0_20px_45px_-25px_rgba(0,0,0,0.75)] backdrop-blur ${className}`} style={style}>
    {(title || subtitle || action) && (
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          {title && <h3 className="text-sm font-semibold text-slate-100">{title}</h3>}
          {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
        </div>
        {action}
      </div>
    )}
    {children}
  </section>
)

export default Card
