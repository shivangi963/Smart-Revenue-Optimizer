import React, { useState } from 'react';
import {
  CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api';
import { useAsync } from '../utils/hooks';
import { categoryIcon, clockTime, dateTime, money, pct } from '../utils/format';

export default function PriceHistoryChart({ products, initialProductId }) {
  const [productId, setProductId] = useState(initialProductId || products[0]?.id);
  const [hours, setHours] = useState(24);

  const { data, error, loading } = useAsync(async () => {
    const [hist, fc, recs] = await Promise.all([
      api.get(`/history/${productId}?hours=${hours}`),
      api.get(`/api/analytics/price-forecast/${productId}?hours=24`),
      api.get(`/recommendations/${productId}?limit=8`),
    ]);
    return { hist, fc, recs };
  }, [productId, hours], 60000);

  if (!productId) return <section className="section"><p className="muted">Add a product first.</p></section>;

  let rows = [];
  let nowMs = null;
  if (data) {
    const h = data.hist.history.map((p) => ({ t: new Date(p.timestamp).getTime(), history: p.price }));
    const f = data.fc.forecast.map((p) => ({ t: new Date(p.time).getTime(), forecast: p.price }));
    rows = [...h, ...f].sort((a, b) => a.t - b.t);
    nowMs = h.length ? h[h.length - 1].t : null;
  }
  const stats = data?.hist.stats;
  const summary = data?.fc.summary;

  return (
    <section className="section">
      <h2 className="section-title">📈 Price History &amp; 24-hour Forecast</h2>
      <p className="section-subtitle">
        Solid line: prices the engine actually applied. Dashed line: what it expects to charge over the next 24 hours given the weather forecast,
        the holiday calendar and the normal daily traffic curve.
      </p>
      <div className="row" style={{ marginBottom: '1rem' }}>
        <div className="field" style={{ maxWidth: 280 }}>
          <label>Product</label>
          <select value={productId} onChange={(e) => setProductId(Number(e.target.value))}>
            {products.map((p) => <option key={p.id} value={p.id}>{categoryIcon(p.category)} {p.name}</option>)}
          </select>
        </div>
        <div style={{ marginTop: '1.3rem' }} className="row">
          {[6, 24, 48].map((h) => (
            <button key={h} className={`btn small ${hours === h ? '' : 'secondary'}`} onClick={() => setHours(h)}>{h}h</button>
          ))}
        </div>
      </div>

      {error && <div className="msg err">{error.message}</div>}
      {loading && !data && <p className="muted">Loading…</p>}
      {data && (
        <>
          <div className="kpi-grid" style={{ marginBottom: '1.25rem' }}>
            {stats && <>
              <div className="kpi-card"><div className="kpi-label">Lowest</div><div className="kpi-value">{money(stats.min)}</div></div>
              <div className="kpi-card"><div className="kpi-label">Highest</div><div className="kpi-value">{money(stats.max)}</div></div>
              <div className="kpi-card"><div className="kpi-label">Average</div><div className="kpi-value">{money(stats.avg)}</div><div className="kpi-sub">base {money(stats.base_price)}</div></div>
              <div className="kpi-card"><div className="kpi-label">Change over period</div><div className="kpi-value">{pct(stats.change_pct)}</div></div>
            </>}
            {summary && <div className="kpi-card good"><div className="kpi-label">Next 24h</div><div className="kpi-value" style={{ fontSize: '1.2rem' }}>Peak {summary.best_hour}</div><div className="kpi-sub">cheapest {summary.cheapest_hour}</div></div>}
          </div>

          <div className="chart-box">
            <ResponsiveContainer width="100%" height={340}>
              <ComposedChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="t" type="number" scale="time" domain={['dataMin', 'dataMax']} fontSize={12}
                       tickFormatter={(t) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} />
                <YAxis fontSize={12} domain={['auto', 'auto']} tickFormatter={(v) => money(v, { compact: true })} width={70} />
                <Tooltip labelFormatter={(t) => dateTime(new Date(t).toISOString())} formatter={(v, n) => [money(v), n]} />
                <Legend />
                <ReferenceLine y={data.hist.stats?.base_price} stroke="#9ca3af" strokeDasharray="4 4" label={{ value: 'base', fontSize: 11, fill: '#6b7280' }} />
                {nowMs && <ReferenceLine x={nowMs} stroke="#f59e0b" label={{ value: 'now', fontSize: 11, fill: '#b45309' }} />}
                <Line type="stepAfter" dataKey="history" name="Applied price" stroke="#667eea" strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} />
                <Line type="monotone" dataKey="forecast" name="24h forecast" stroke="#764ba2" strokeWidth={2.5} strokeDasharray="6 4" dot={{ r: 2 }} connectNulls isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          <h3 style={{ margin: '1.5rem 0 .5rem' }}>Recent pricing decisions</h3>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Time</th><th className="num">Price</th><th>Why</th></tr></thead>
              <tbody>
                {data.recs.recommendations.map((r) => (
                  <tr key={r.id}>
                    <td>{clockTime(r.timestamp)}</td>
                    <td className="num">{money(r.final_price)}</td>
                    <td>{r.rationale || <span className="muted">(backfilled history)</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
