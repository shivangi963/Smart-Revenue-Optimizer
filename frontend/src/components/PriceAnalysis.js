import React from 'react';
import {
  categoryIcon, categoryLabel, clockTime, constraintLabel, factorLabel, modelLabel, money, num, pct,
} from '../utils/format';

function FactorCard({ name, value }) {
  const up = value > 0;
  return (
    <div className="factor-card">
      <div className="factor-header">
        <span className="factor-name">{factorLabel(name)}</span>
        <span className={`factor-value ${value === 0 ? '' : up ? 'positive' : 'negative'}`}>{up ? '+' : ''}{value}%</span>
      </div>
      <div className="factor-bar">
        <div className={`factor-fill ${up ? 'positive' : 'negative'}`} style={{ width: `${Math.min(Math.abs(value) * 3, 100)}%` }} />
      </div>
    </div>
  );
}

export default function PriceAnalysis({ product, price, holidays, onRefresh, refreshing }) {
  if (!product || !price) return null;
  const change = price.total_change || 0;
  const dir = change > 0 ? 'increase' : change < 0 ? 'decrease' : 'neutral';
  const w = price.weather;
  const ex = price.expected;
  const conf = Math.round((price.confidence || 0) * 100);
  const factors = Object.entries(price.factors || {});

  return (
    <section className="section price-section">
      <div className="row between">
        <h2 className="section-title" style={{ marginBottom: '1rem' }}>💰 Price Analysis</h2>
        <button className="btn secondary small" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? 'Recalculating…' : '↻ Recalculate now'}
        </button>
      </div>
      <div className="price-card">
        <div className="price-header">
          <div className="product-info">
            <div className="product-icon-large">{categoryIcon(product.category)}</div>
            <div>
              <h3 className="product-title">{product.name}</h3>
              <p className="product-subtitle">{categoryLabel(product.category)}</p>
            </div>
          </div>
          <div className="price-change">
            <span className={`change-badge ${dir}`}>{change > 0 ? '↗' : change < 0 ? '↘' : '→'} {Math.abs(change).toFixed(1)}%</span>
          </div>
        </div>

        <div className="price-comparison">
          <div className="price-item">
            <div className="price-label">Base Price</div>
            <div className="price-value base">{money(price.base_price)}</div>
          </div>
          <div className="price-arrow">→</div>
          <div className="price-item">
            <div className="price-label">Current Price</div>
            <div className={`price-value current ${dir === 'neutral' ? '' : dir}`}>{money(price.final_price)}</div>
          </div>
        </div>

        <div className="badge-row" style={{ marginBottom: '1rem' }}>
          <span className={`badge ${conf >= 90 ? 'ok' : conf >= 75 ? 'info' : 'warn'}`} title="Expected revenue at this price vs. the best price in the allowed range">
            Revenue-efficiency {conf}%
          </span>
          <span className="badge info">{modelLabel(price.model_type)} · {price.model_version}</span>
          <span className="badge">Allowed range {money(price.allowed_range.min)} – {money(price.allowed_range.max)}</span>
          {(price.constraints_applied || []).map((c) => <span key={c} className="badge warn">⛔ {constraintLabel(c)}</span>)}
        </div>

        <div className="external-factors">
          {w && (
            <div className="weather-card">
              <h4>🌤️ Current Weather</h4>
              <div className="weather-details">
                <div className="temp">{w.temperature}°C</div>
                <div className="condition">{w.condition}</div>
                <div className="location">{w.city} {w.source === 'simulated' && <span className="badge warn" title="Live weather API unreachable - using deterministic simulated weather">simulated</span>}</div>
                <div className="precip">Rain intensity: {Math.round(w.precipitation * 100)}%</div>
              </div>
            </div>
          )}
          {holidays.length > 0 && (
            <div className="holidays-card">
              <h4>🎉 Upcoming Events</h4>
              <div className="holidays-list">
                {holidays.slice(0, 3).map((h) => (
                  <div key={`${h.name}-${h.date}`} className={`holiday-item ${h.impact}`}>
                    <span className="holiday-name">{h.name}</span>
                    <span className="holiday-days">{h.days_until === 0 ? 'today' : `in ${h.days_until} days`}</span>
                  </div>
                ))}
                {holidays.length > 3 && <div className="more-holidays muted small">+{holidays.length - 3} more events</div>}
              </div>
            </div>
          )}
        </div>

        <div className="factors-section">
          <h4 className="factors-title">📊 Factors Influencing Price</h4>
          <div className="factors-grid">{factors.map(([k, v]) => <FactorCard key={k} name={k} value={v} />)}</div>
          <p className="chart-caption">Exact Shapley contributions of each factor group to the model's price (red = pushes price up, green = pushes it down).</p>
        </div>

        <div className="explanation-box">
          <h4 className="explanation-title">📝 Price Justification</h4>
          <p className="explanation-text">{price.explanation}</p>
        </div>

        {ex && (
          <div className="impact-grid">
            <div className="info-item"><span className="info-label">Expected orders / hour</span>
              <span className="info-value">{num(ex.units_per_hour_base, 1)} → {num(ex.units_per_hour_final, 1)}</span></div>
            <div className="info-item"><span className="info-label">Expected revenue / hour</span>
              <span className="info-value">{money(ex.revenue_per_hour_base)} → {money(ex.revenue_per_hour_final)}</span></div>
            <div className="info-item"><span className="info-label">Revenue vs. base price</span>
              <span className="info-value" style={{ color: ex.revenue_lift_pct >= 0 ? 'var(--success-color)' : 'var(--danger-color)' }}>{pct(ex.revenue_lift_pct, 2)}</span></div>
          </div>
        )}

        <div className="info-grid" style={{ marginTop: '1rem' }}>
          <div className="info-item"><span className="info-label">Last updated</span><span className="info-value">{clockTime(price.timestamp)}</span></div>
          <div className="info-item"><span className="info-label">Computed in</span><span className="info-value">{price.latency_ms} ms</span></div>
          <div className="info-item"><span className="info-label">Product ID</span><span className="info-value">{product.id}</span></div>
        </div>
      </div>
    </section>
  );
}
