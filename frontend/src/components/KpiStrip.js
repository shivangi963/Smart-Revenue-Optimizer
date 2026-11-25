import React from 'react';
import { api } from '../api';
import { useAsync } from '../utils/hooks';
import { modelLabel, money, num, pct } from '../utils/format';

export default function KpiStrip() {
  const { data } = useAsync(() => api.get('/api/dashboard/stats'), [], 30000);
  if (!data) return <div className="kpi-grid" aria-busy="true" />;

  const { summary, revenue, model_performance: mp, latency } = data;
  const lift = revenue.total.lift_pct;
  return (
    <div className="kpi-grid">
      <div className="kpi-card">
        <div className="kpi-label">Active products</div>
        <div className="kpi-value">{summary.active_products}</div>
        <div className="kpi-sub">avg price vs base {pct(summary.avg_price_change)}</div>
      </div>
      <div className="kpi-card">
        <div className="kpi-label">Price updates (24h)</div>
        <div className="kpi-value">{num(summary.total_price_updates)}</div>
        <div className="kpi-sub">every one explained &amp; audited</div>
      </div>
      <div className={`kpi-card ${lift > 0 ? 'good' : 'warn'}`}>
        <div className="kpi-label">Revenue lift (24h)</div>
        <div className={`kpi-value ${lift > 0 ? 'good' : ''}`}>{pct(lift, 2)}</div>
        <div className="kpi-sub">{money(revenue.total.gain)} vs. static pricing</div>
      </div>
      <div className="kpi-card">
        <div className="kpi-label">Active model</div>
        <div className="kpi-value">{mp ? `R² ${mp.r2.toFixed(3)}` : '—'}</div>
        <div className="kpi-sub">{modelLabel(summary.model_type)}</div>
      </div>
      <div className="kpi-card">
        <div className="kpi-label">Pricing latency</div>
        <div className="kpi-value">{latency.p50_ms !== null ? `${latency.p50_ms} ms` : '—'}</div>
        <div className="kpi-sub">median{latency.p95_ms !== null ? ` · p95 ${latency.p95_ms} ms` : ''}</div>
      </div>
    </div>
  );
}
