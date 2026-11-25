import React, { useEffect, useState } from 'react';
import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, ReferenceArea, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../api';
import { useAsync } from '../utils/hooks';
import { categoryIcon, dateTime, getCurrency, modelLabel, money, num, pct } from '../utils/format';

const SWITCHABLE = ['linear', 'random_forest', 'gradient_boosting'];
const COLORS = ['#667eea', '#764ba2', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#9ca3af'];

function RevenueCurve({ products, initialProductId }) {
  const [productId, setProductId] = useState(initialProductId || products[0]?.id);
  const { data, error } = useAsync(() => api.get(`/api/analytics/revenue-curve/${productId}`), [productId], 60000);
  return (
    <div>
      <div className="row between">
        <h3>Revenue response curve</h3>
        <select className="inline" value={productId} onChange={(e) => setProductId(Number(e.target.value))}>
          {products.map((p) => <option key={p.id} value={p.id}>{categoryIcon(p.category)} {p.name}</option>)}
        </select>
      </div>
      {error && <div className="msg err">{error.message}</div>}
      {data && (
        <div className="chart-box" style={{ marginTop: '.75rem' }}>
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={data.curve} margin={{ top: 22, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="price" type="number" domain={['dataMin', 'dataMax']} fontSize={12} tickFormatter={(v) => money(v, { compact: true })} />
              <YAxis fontSize={12} tickFormatter={(v) => money(v, { compact: true })} width={70} />
              <Tooltip formatter={(v, n) => [money(v), n]} labelFormatter={(p) => `Price ${money(p)}`} />
              <Legend />
              <ReferenceArea x1={data.allowed_range.min} x2={data.allowed_range.max} fill="#10b981" fillOpacity={0.07} />
              <ReferenceLine x={data.base_price} stroke="#9ca3af" strokeDasharray="4 4" />
              <ReferenceLine x={data.recommended_price} stroke="#667eea" strokeWidth={2} />
              <ReferenceLine x={data.optimal_price} stroke="#ef4444" strokeDasharray="2 3" strokeWidth={2} />
              <Line type="monotone" dataKey="revenue" name="Expected revenue / hr" stroke="#c4b5fd" dot={{ r: 2 }} strokeWidth={1.5} isAnimationActive={false} />
              <Line type="monotone" dataKey="revenue_smooth" name="Smoothed curve" stroke="#764ba2" dot={false} strokeWidth={3} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
          <p className="chart-caption">
            Learned from the demand model for the <em>current</em> conditions. Markers:{' '}
            <strong style={{ color: '#667eea' }}>blue line</strong> = recommended price ({money(data.recommended_price)}),{' '}
            <strong style={{ color: '#ef4444' }}>red dotted</strong> = revenue peak ({money(data.optimal_price)}),{' '}
            <strong style={{ color: '#6b7280' }}>grey dashed</strong> = base price ({money(data.base_price)}). Green band = prices the guardrails allow.
          </p>
        </div>
      )}
    </div>
  );
}

export default function ModelAnalytics({ products, initialProductId, isAdmin = false }) {
  const info = useAsync(() => api.get('/api/model/info'), [], 5000);
  const metrics = useAsync(() => api.get('/api/model/metrics'), [info.data?.version, info.data?.active_model]);
  const imp = useAsync(() => api.get('/api/model/feature-importance?top=10'), [info.data?.version, info.data?.active_model]);
  const [msg, setMsg] = useState(null);
  const [samples, setSamples] = useState(25000);

  const state = info.data?.status?.state;
  const reloadMetrics = metrics.reload;
  useEffect(() => { if (state === 'ready') reloadMetrics(); }, [state, reloadMetrics]);

  const act = async (fn, okText) => {
    try { await fn(); setMsg({ ok: true, text: okText }); info.reload(); }
    catch (e) { setMsg({ ok: false, text: e.message }); }
  };

  if (!info.data) return <section className="section"><p className="muted">Loading model information…</p></section>;
  const i = info.data;
  const training = state === 'training';
  const m = metrics.data;
  const rows = m?.strategies || [];
  const liftData = rows.map((r) => ({ name: r.label, lift: r.revenue_lift_pct, key: r.key }));

  return (
    <>
      <section className="section">
        <h2 className="section-title">🤖 Machine-Learning Model</h2>
        {training && <div className="banner info">⏳ <strong>Training in progress:</strong> {i.status.message} — prices use the rule-based fallback until it finishes.</div>}
        {msg && <div className={`msg ${msg.ok ? 'ok' : 'err'}`}>{msg.text}</div>}

        <div className="kpi-grid">
          <div className="kpi-card"><div className="kpi-label">Version</div><div className="kpi-value" style={{ fontSize: '1.15rem' }}>{i.version}</div><div className="kpi-sub">{i.trained_at ? dateTime(i.trained_at) : '—'}</div></div>
          <div className="kpi-card"><div className="kpi-label">Training data</div><div className="kpi-value">{i.n_samples ? num(i.n_samples) : '—'}</div><div className="kpi-sub">synthetic market observations</div></div>
          <div className="kpi-card good"><div className="kpi-label">Best model</div><div className="kpi-value" style={{ fontSize: '1.15rem' }}>{i.best_model ? modelLabel(i.best_model) : '—'}</div><div className="kpi-sub">lowest hold-out RMSE</div></div>
          <div className="kpi-card"><div className="kpi-label">Pricing with</div><div className="kpi-value" style={{ fontSize: '1.15rem' }}>{modelLabel(i.active_model || 'rule_based')}</div><div className="kpi-sub">switch below to compare live</div></div>
        </div>

        <div className="row" style={{ marginBottom: '.5rem' }}>
          <strong>Active model:</strong>
          {SWITCHABLE.map((k) => (
            <button key={k} className={`btn small ${i.active_model === k ? 'active' : 'secondary'}`} disabled={!isAdmin || !i.ready || training}
                    onClick={() => act(() => api.post('/api/model/select', { model_type: k }), `Now pricing with ${modelLabel(k)}`)}>
              {modelLabel(k)}{i.best_model === k ? ' ★' : ''}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <select className="inline" value={samples} onChange={(e) => setSamples(Number(e.target.value))} disabled={!isAdmin || training}>
            {[5000, 10000, 25000, 50000].map((n) => <option key={n} value={n}>{num(n)} samples</option>)}
          </select>
          <button className="btn small" disabled={!isAdmin || training}
                  onClick={() => act(() => api.post('/api/model/retrain', { n_samples: samples }), 'Retraining started in the background')}>
            {training ? 'Training…' : '⟳ Retrain'}
          </button>
        </div>
        {!isAdmin && <p className="muted small" style={{ marginTop: '.5rem' }}>Viewers can inspect the models; only administrators can switch or retrain them.</p>}
      </section>

      {m?.ready && (
        <>
          <section className="section">
            <h2 className="section-title">📋 Model Comparison</h2>
            <p className="section-subtitle">
              Evaluated on {num(m.n_test)} unseen contexts. MAE/RMSE are in {getCurrency()}; revenue lift is measured against static base-price
              pricing using the market's true demand curve. The <em>Oracle</em> row is the theoretical ceiling.
            </p>
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Strategy</th><th className="num">MAE</th><th className="num">RMSE</th><th className="num">R²</th>
                  <th className="num">Revenue lift</th><th className="num">Profit lift</th><th className="num">Latency</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.key} className={r.is_active ? 'hl' : r.key === 'oracle' || r.key === 'static' ? 'dim' : ''}>
                      <td>{r.label} {r.is_active && <span className="badge info">active</span>} {m.best_model === r.key && <span className="badge ok">best</span>}</td>
                      <td className="num">{r.mae.toFixed(2)}</td><td className="num">{r.rmse.toFixed(2)}</td><td className="num">{r.r2.toFixed(3)}</td>
                      <td className="num">{pct(r.revenue_lift_pct, 2)}</td><td className="num">{pct(r.profit_lift_pct, 1)}</td>
                      <td className="num">{r.latency_ms ? `${r.latency_ms.toFixed(2)} ms` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="grid-2" style={{ marginTop: '1.5rem' }}>
              <div className="chart-box">
                <div className="chart-title">Revenue lift vs. static pricing</div>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={liftData} layout="vertical" margin={{ left: 30 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis type="number" fontSize={12} unit="%" />
                    <YAxis type="category" dataKey="name" fontSize={12} width={130} />
                    <Tooltip formatter={(v) => `${v.toFixed(2)}%`} />
                    <Bar dataKey="lift" name="Revenue lift" isAnimationActive={false}>
                      {liftData.map((d, k) => <Cell key={d.key} fill={d.key === 'oracle' ? '#d1d5db' : d.key === m.active_model ? '#667eea' : COLORS[(k + 2) % COLORS.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="chart-box">
                <div className="chart-title">Feature importance ({imp.data?.model_label})</div>
                {imp.data?.ready && (
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={imp.data.grouped} layout="vertical" margin={{ left: 30 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis type="number" fontSize={12} unit="%" />
                      <YAxis type="category" dataKey="label" fontSize={12} width={120} />
                      <Tooltip formatter={(v) => `${v}%`} />
                      <Bar dataKey="pct" name="Importance" isAnimationActive={false}>{imp.data.grouped.map((g, k) => <Cell key={g.group} fill={COLORS[k % COLORS.length]} />)}</Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>
            <p className="chart-caption" style={{ marginTop: '1rem' }}>
              Demand model (learns units sold vs. price): R² = {m.demand_model.r2_vs_expected} against true demand; its revenue peak lands
              within {m.demand_model.optimum_mae_pct.toFixed(1)}% of the true optimal price on average.
            </p>
          </section>

          <section className="section">
            <RevenueCurve products={products} initialProductId={initialProductId} />
          </section>
        </>
      )}
    </>
  );
}
