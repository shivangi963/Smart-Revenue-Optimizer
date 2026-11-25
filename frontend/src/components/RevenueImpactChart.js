import React from 'react';
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api';
import { useAsync } from '../utils/hooks';
import { clockTime, money, pct } from '../utils/format';

export default function RevenueImpactChart() {
  const { data, error } = useAsync(() => api.get('/api/analytics/revenue-summary?hours=24'), [], 60000);
  if (error) return null;
  if (!data) return <section className="section"><p className="muted">Loading revenue impact…</p></section>;
  if (data.hourly.length === 0) return null;

  let running = 0;
  const rows = data.hourly.map((h) => {
    const gain = h.revenue - h.baseline_revenue;
    running += gain;
    return { time: clockTime(h.time), 'Hourly gain': Math.round(gain), 'Cumulative gain': Math.round(running) };
  });
  return (
    <section className="section">
      <h2 className="section-title">💹 Revenue Impact — last 24 hours</h2>
      <p className="section-subtitle">
        Extra revenue earned by dynamic pricing: simulated sales at the prices actually charged, minus what the same demand
        would have earned at the fixed base price. Total: <strong>{money(data.total.gain)}</strong> ({pct(data.total.lift_pct, 2)}).
      </p>
      <div className="grid-2" style={{ gridTemplateColumns: '2fr 1fr' }}>
        <div className="chart-box">
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="time" fontSize={12} interval="preserveStartEnd" minTickGap={30} />
              <YAxis fontSize={12} tickFormatter={(v) => money(v, { compact: true })} width={70} />
              <Tooltip formatter={(v) => money(v)} />
              <Legend />
              <Bar dataKey="Hourly gain" fill="#a5b4fc" isAnimationActive={false} />
              <Line type="monotone" dataKey="Cumulative gain" stroke="#10b981" strokeWidth={3} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Product</th><th className="num">Lift</th></tr></thead>
            <tbody>
              {data.per_product.map((p) => (
                <tr key={p.product_id}>
                  <td>{p.product_name}</td>
                  <td className="num" style={{ color: p.lift_pct >= 0 ? 'var(--success-color)' : 'var(--danger-color)', fontWeight: 700 }}>{pct(p.lift_pct, 2)}</td>
                </tr>
              ))}
              <tr className="hl"><td>Total</td><td className="num">{pct(data.total.lift_pct, 2)}</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
