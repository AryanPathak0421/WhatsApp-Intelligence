import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

export const COLORS = { COMPLETED: '#16a34a', IN_PROGRESS: '#3b82f6', TODO: '#94a3b8', BLOCKED: '#ef4444', CANCELLED: '#cbd5e1',
  LOW: '#94a3b8', MEDIUM: '#f59e0b', HIGH: '#ef4444', CRITICAL: '#8b5cf6', brand: '#5b6cf0' } as Record<string, string>;
const tip = { contentStyle: { background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12, color: 'var(--text)' }, cursor: { fill: 'var(--surface-2)' } };

export function Donut({ data, height = 220 }: { data: { name: string; value: number; color: string }[]; height?: number }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <div className="relative" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart><Pie data={data.filter((d) => d.value > 0)} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="88%" paddingAngle={2} stroke="none">
          {data.filter((d) => d.value > 0).map((d) => <Cell key={d.name} fill={d.color} />)}</Pie><Tooltip {...tip} /><Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} /></PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 -mt-4 flex flex-col items-center justify-center"><span className="text-2xl font-semibold tabular-nums">{total}</span><span className="muted text-[11px]">tasks</span></div>
    </div>
  );
}

/** One-line category label for horizontal bar charts: long names are cut with an ellipsis (full name on hover) instead of wrapping over the next row. */
const CategoryTick = ({ x, y, payload, max = 24 }: { x?: number; y?: number; payload?: { value: string }; max?: number }) => {
  const full = String(payload?.value ?? '');
  const text = full.length > max ? `${full.slice(0, max - 8).trimEnd()}…${full.slice(-6)}` : full;     // keep the tail: names often differ only at the end
  return <g transform={`translate(${x},${y})`}><title>{full}</title><text x={-6} y={0} dy={4} textAnchor="end" className="recharts-text">{text}</text></g>;
};

export function SimpleBars({ data, x, bars, height = 220, layout = 'horizontal' }:
  { data: Record<string, any>[]; x: string; bars: { key: string; color: string; name?: string; stack?: string }[]; height?: number; layout?: 'horizontal' | 'vertical' }) {
  const v = layout === 'vertical';
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout={layout} margin={{ left: v ? 10 : -16, right: 8, top: 8 }}>
          <CartesianGrid vertical={v} horizontal={!v} strokeDasharray="3 3" />
          {v ? <><XAxis type="number" tickLine={false} axisLine={false} allowDecimals={false} /><YAxis type="category" dataKey={x} width={150} interval={0} tick={<CategoryTick />} tickLine={false} axisLine={false} /></>
            : <><XAxis dataKey={x} tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} allowDecimals={false} /></>}
          <Tooltip {...tip} />{bars.length > 1 && <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />}
          {bars.map((b) => <Bar key={b.key} dataKey={b.key} name={b.name ?? b.key} fill={b.color} stackId={b.stack} radius={b.stack ? 0 : 4} maxBarSize={36} />)}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Trend({ data, x, lines, height = 220, unit }: { data: Record<string, any>[]; x: string; lines: { key: string; color: string; name?: string }[]; height?: number; unit?: string }) {
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ left: -12, right: 8, top: 8 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" /><XAxis dataKey={x} tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} unit={unit} />
          <Tooltip {...tip} />{lines.length > 1 && <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />}
          {lines.map((l) => <Line key={l.key} type="monotone" dataKey={l.key} name={l.name ?? l.key} stroke={l.color} strokeWidth={2.5} dot={false} connectNulls />)}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
