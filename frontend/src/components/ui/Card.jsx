const Card = ({ title, subtitle, children, className = '', action, style }) => (
  <section className={`surface-card rounded-3xl p-5 ${className}`} style={style}>
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
