import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { useAsync } from '../utils/hooks';
import { categoryIcon, getCurrency } from '../utils/format';

export default function CurrencyConverter({ products }) {
  const base = getCurrency();
  const cur = useAsync(() => api.get('/api/exchange/currencies'), []);
  const rates = useAsync(() => api.get(`/api/exchange/rates?base=${base}`), [base]);
  const [amount, setAmount] = useState(products[0]?.current_price || products[0]?.base_price || 100);
  const [from, setFrom] = useState(base);
  const [to, setTo] = useState(base === 'USD' ? 'EUR' : 'USD');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!(amount > 0)) { setResult(null); return undefined; }
    const t = setTimeout(() => {
      api.get(`/api/exchange/convert?amount=${amount}&from_currency=${from}&to_currency=${to}`)
        .then((r) => { setResult(r); setError(null); }).catch((e) => setError(e.message));
    }, 300);
    return () => clearTimeout(t);
  }, [amount, from, to]);

  const currencies = cur.data?.currencies || {};
  const fmt = (v, code) => new Intl.NumberFormat('en-US', { style: 'currency', currency: code, maximumFractionDigits: 2 }).format(v);

  return (
    <section className="section">
      <h2 className="section-title">💱 Currency Converter</h2>
      <p className="section-subtitle">Show today's prices to international shoppers in their own currency.</p>
      <div className="form-grid" style={{ maxWidth: 780 }}>
        <div className="field"><label>Amount</label><input type="number" min="0" value={amount} onChange={(e) => setAmount(Number(e.target.value))} /></div>
        <div className="field"><label>From</label>
          <select value={from} onChange={(e) => setFrom(e.target.value)}>{Object.entries(currencies).map(([c, v]) => <option key={c} value={c}>{c} — {v.name}</option>)}</select></div>
        <div className="field"><label>To</label>
          <select value={to} onChange={(e) => setTo(e.target.value)}>{Object.entries(currencies).map(([c, v]) => <option key={c} value={c}>{c} — {v.name}</option>)}</select></div>
        <button className="btn secondary" onClick={() => { setFrom(to); setTo(from); }}>⇄ Swap</button>
      </div>
      {error && <div className="msg err">{error}</div>}
      {result && (
        <div className="sim-result" style={{ marginTop: '1.25rem', maxWidth: 780 }}>
          <div className="muted">{fmt(result.amount, result.from_currency)} =</div>
          <div className="sim-price">{fmt(result.converted_amount, result.to_currency)}</div>
          <div className="muted small">1 {result.from_currency} = {result.rate} {result.to_currency} · {result.date}{' '}
            {result.source === 'offline-fallback' && <span className="badge warn">approximate offline rates</span>}</div>
        </div>
      )}

      <h3 style={{ margin: '2rem 0 .75rem' }}>Current prices in other currencies</h3>
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Product</th>{['USD', 'EUR', 'GBP', 'AED', 'SGD'].map((c) => <th key={c} className="num">{c}</th>)}</tr></thead>
          <tbody>
            {rates.data && products.map((p) => (
              <tr key={p.id}>
                <td>{categoryIcon(p.category)} {p.name} <span className="muted">({fmt(p.current_price || p.base_price, base)})</span></td>
                {['USD', 'EUR', 'GBP', 'AED', 'SGD'].map((c) => <td key={c} className="num">{fmt((p.current_price || p.base_price) * rates.data.rates[c], c)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
