import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const KnowledgeHistoryChart = ({ data }) => (
  <ResponsiveContainer width="100%" height="100%">
    <LineChart data={data}>
      <CartesianGrid stroke="var(--border)" vertical={false} />
      <XAxis
        dataKey="date"
        stroke="var(--muted)"
        tickFormatter={(value) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
      />
      <YAxis stroke="var(--muted)" allowDecimals={false} />
      <Tooltip contentStyle={{ background: 'var(--surface)', borderColor: 'var(--border)', borderRadius: 12, color: 'var(--foreground)' }} />
      <Legend />
      <Line type="monotone" dataKey="documents" stroke="var(--accent-strong)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
      <Line type="monotone" dataKey="chunks" stroke="#8aa592" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
      <Line type="monotone" dataKey="embeddings" stroke="#b2c4b8" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
    </LineChart>
  </ResponsiveContainer>
)

export default KnowledgeHistoryChart
