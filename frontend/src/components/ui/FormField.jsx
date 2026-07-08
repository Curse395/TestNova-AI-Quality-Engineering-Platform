const FormField = ({ label, type = 'text', placeholder, value, onChange, name }) => (
  <label className="block text-sm text-slate-300">
    <span className="mb-2 block text-slate-400">{label}</span>
    <input
      type={type}
      name={name}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      className="w-full rounded-2xl border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-sky-400"
    />
  </label>
)

export default FormField
