import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useDebounced } from '../utils/hooks';
import { categoryIcon, constraintLabel, factorLabel, money, pct } from '../utils/format';

const eventScore = (isHoliday, days) => (isHoliday ? 1 : 0.8 * Math.exp(-days / 4));

function Slider({ label, value, min, max, step = 1, unit = '', onChange, format }) {
  return (
    <div className="slider-row">
      <label>{label}</label>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      <output>{format ? format(value) : value}{unit}</output>
    </div>
  );
}

export default function PriceSimulator({ products, initialProductId }) {
  const [productId, setProductId] = useState(initialProductId || products[0]?.id);
  const product = products.find((p) => p.id === productId);
  const [live, setLive] = useState(null);      // live context, used for "Reset" + initial slider values
  const [vals, setVals] = useState(null);
  const [markup, setMarkup] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const reqId = useRef(0);

  // load the live context whenever the product changes
  useEffect(() => {
    if (!productId) return;
    api.get(`/prices/${productId}/current`).then((p) => {
      const c = p.context;
      const v = {
        temperature: c.temperature, precipitation: c.precipitation, hour_of_day: c.hour_of_day,
        traffic: Math.round((c.page_views_1h / Math.max(c.expected_page_views, 1)) * 100), stock_level: c.stock_level,
        competitor_price: Math.round(c.competitor_price), is_holiday: !!c.is_holiday, days_to_event: Math.min(c.days_to_event, 60),
      };
      setLive(v); setVals(v); setMarkup(0);
    }).catch((e) => setError(e.message));
  }, [productId]);

  const debounced = useDebounced({ vals, markup }, 350);
  useEffect(() => {
    if (!debounced.vals || !productId) return;
    const id = ++reqId.current;
    const v = debounced.vals;
    setBusy(true);
    api.post('/simulate_price', {
      product_id: productId,
      features: {
        temperature: v.temperature, precipitation: v.precipitation, hour_of_day: v.hour_of_day,
        traffic_index: v.traffic / 100, stock_level: v.stock_level, competitor_price: v.competitor_price,
        is_holiday: v.is_holiday ? 1 : 0, days_to_event: v.is_holiday ? 0 : v.days_to_event,
        event_score: eventScore(v.is_holiday, v.days_to_event),
      },
      manual_adjustments: debounced.markup ? { markup_pct: debounced.markup } : undefined,
    }).then((r) => { if (id === reqId.current) { setResult(r); setError(null); } })
      .catch((e) => id === reqId.current && setError(e.message))
      .finally(() => id === reqId.current && setBusy(false));
  }, [debounced, productId]);

  if (!product) return <section className="section"><p className="muted">Add a product first.</p></section>;
  const set = (k) => (x) => setVals((s) => ({ ...s, [k]: x }));
  const apply = (patch) => setVals((s) => ({ ...s, ...patch }));
  const base = product.base_price;
  const presets = [
    ['🌧️ Heavy rain evening', { precipitation: 0.9, temperature: 22, hour_of_day: 20 }],
    ['☀️ Hot afternoon', { precipitation: 0, temperature: 38, hour_of_day: 15 }],
    ['🎉 Festival rush', { is_holiday: true, days_to_event: 0, traffic: Math.round((live?.traffic || 100) * 1.8) }],
    ['📦 Overstock clearance', { stock_level: product.max_stock, traffic: Math.round((live?.traffic || 100) * 0.5) }],
    ['⚠️ Almost sold out', { stock_level: Math.max(1, Math.round(product.max_stock * 0.03)) }],
    ['🏷️ Competitor undercuts', { competitor_price: Math.round(base * 0.8) }],
  ];

  return (
    <section className="section">
      <h2 className="section-title">🧪 Price Simulator</h2>
      <p className="section-subtitle">Change the conditions and watch the model re-price instantly. Nothing is saved — this is a safe what-if sandbox.</p>

      <div className="row" style={{ marginBottom: '1rem' }}>
        <div className="field" style={{ maxWidth: 280 }}>
          <label>Product</label>
          <select value={productId} onChange={(e) => setProductId(Number(e.target.value))}>
            {products.map((p) => <option key={p.id} value={p.id}>{categoryIcon(p.category)} {p.name}</option>)}
          </select>
        </div>
        <button className="btn secondary" style={{ marginTop: '1.3rem' }} onClick={() => { setVals(live); setMarkup(0); }}>↺ Reset to live conditions</button>
      </div>

      {vals && (
        <div className="grid-2" style={{ gridTemplateColumns: '1.1fr 1fr', alignItems: 'start' }}>
          <div>
            <div className="preset-row">
              {presets.map(([label, patch]) => <button key={label} className="btn secondary small" onClick={() => apply(patch)}>{label}</button>)}
            </div>
            <Slider label="Temperature" value={vals.temperature} min={-5} max={45} step={0.5} unit="°C" onChange={set('temperature')} />
            <Slider label="Rain intensity" value={vals.precipitation} min={0} max={1} step={0.05} onChange={set('precipitation')} format={(v) => `${Math.round(v * 100)}%`} />
            <Slider label="Hour of day" value={vals.hour_of_day} min={0} max={23} onChange={set('hour_of_day')} format={(v) => `${String(v).padStart(2, '0')}:00`} />
            <Slider label="Traffic vs normal" value={vals.traffic} min={10} max={Math.max(300, vals.traffic)} step={5} onChange={set('traffic')} format={(v) => `${v}%`} />
            <Slider label="Stock level" value={vals.stock_level} min={0} max={Math.max(product.max_stock, vals.stock_level)} onChange={set('stock_level')} />
            <Slider label="Competitor price" value={vals.competitor_price} min={Math.round(base * 0.5)} max={Math.round(base * 1.5)} onChange={set('competitor_price')} format={(v) => money(v)} />
            <Slider label="Days to event" value={vals.days_to_event} min={0} max={60} onChange={set('days_to_event')} />
            <div className="slider-row">
              <label>Holiday today</label>
              <input type="checkbox" checked={vals.is_holiday} onChange={(e) => set('is_holiday')(e.target.checked)} style={{ width: 20, height: 20 }} />
              <span />
            </div>
            <Slider label="Manual markup" value={markup} min={-20} max={20} onChange={setMarkup} unit="%" />
          </div>

          <div className="sim-result" style={{ opacity: busy ? 0.7 : 1 }}>
            {error && <div className="msg err">{error}</div>}
            {result && (
              <>
                <div className="muted small">Recommended price</div>
                <div className="sim-price">{money(result.final_price)}</div>
                <div style={{ fontWeight: 700, color: result.total_change >= 0 ? 'var(--danger-color)' : 'var(--success-color)' }}>
                  {pct(result.total_change)} vs. base {money(result.base_price)}
                </div>
                <p style={{ margin: '.9rem 0' }}>{result.rationale}</p>
                <div className="badge-row" style={{ marginTop: 0, marginBottom: '1rem' }}>
                  {result.constraints_applied.map((c) => <span key={c} className="badge warn">⛔ {constraintLabel(c)}</span>)}
                  {result.expected && <span className={`badge ${result.expected.revenue_lift_pct >= 0 ? 'ok' : 'bad'}`}>Revenue vs base {pct(result.expected.revenue_lift_pct, 1)}</span>}
                </div>
                {Object.entries(result.factors).map(([k, v]) => (
                  <div key={k} className="slider-row" style={{ gridTemplateColumns: '130px 1fr 70px', padding: '.15rem 0' }}>
                    <label style={{ fontWeight: 500, fontSize: '.85rem' }}>{factorLabel(k)}</label>
                    <div className="factor-bar"><div className={`factor-fill ${v > 0 ? 'positive' : 'negative'}`} style={{ width: `${Math.min(Math.abs(v) * 3, 100)}%` }} /></div>
                    <output style={{ color: v > 0 ? 'var(--danger-color)' : v < 0 ? 'var(--success-color)' : undefined }}>{v > 0 ? '+' : ''}{v}%</output>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
