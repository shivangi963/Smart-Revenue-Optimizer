import React, { useState } from 'react';
import { api } from '../api';
import { useAsync } from '../utils/hooks';
import { categoryIcon, categoryLabel, money, num } from '../utils/format';
import UserManagement from './UserManagement';

const CATEGORIES = ['umbrella', 'ice_cream', 'ticket', 'hot_beverage', 'generic'];
const EMPTY_PRODUCT = { sku: '', name: '', category: 'umbrella', base_price: '', cost: '', price_min: '', price_max: '', price_step: 1, current_stock: 100, max_stock: 200 };
const EMPTY_RULE = { scope: 'global', scope_value: '', rule_type: 'max_markup_pct', value: 0.2, note: '' };

function Flash({ msg }) { return msg ? <div className={`msg ${msg.ok ? 'ok' : 'err'}`}>{msg.text}</div> : null; }

function Products({ products, onChanged }) {
  const [form, setForm] = useState(EMPTY_PRODUCT);
  const [msg, setMsg] = useState(null);
  const [stock, setStock] = useState({});
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const run = async (fn, ok) => {
    try { await fn(); setMsg({ ok: true, text: ok }); await onChanged(); }
    catch (e) { setMsg({ ok: false, text: e.message }); }
  };
  const add = (e) => {
    e.preventDefault();
    const n = (v) => (v === '' ? undefined : Number(v));
    const body = { ...form, base_price: Number(form.base_price), cost: Number(form.cost), price_min: n(form.price_min),
      price_max: n(form.price_max), price_step: Number(form.price_step), current_stock: Number(form.current_stock), max_stock: Number(form.max_stock) };
    Object.keys(body).forEach((k) => body[k] === undefined && delete body[k]);
    run(async () => { await api.post('/products', body); setForm(EMPTY_PRODUCT); }, `Product "${form.name}" added and priced`);
  };

  return (
    <section className="section">
      <h2 className="section-title">📦 Products</h2>
      <Flash msg={msg} />
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Product</th><th className="num">Base</th><th className="num">Cost</th><th className="num">Min – Max</th>
            <th className="num">Price now</th><th>Stock (units)</th><th /></tr></thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id}>
                <td>{categoryIcon(p.category)} <strong>{p.name}</strong><div className="muted small">{p.sku} · {categoryLabel(p.category)}</div></td>
                <td className="num">{money(p.base_price)}</td><td className="num">{money(p.cost)}</td>
                <td className="num">{p.price_min > 0 ? money(p.price_min) : 'no min'} – {p.price_max < 1e6 ? money(p.price_max) : 'no max'}</td>
                <td className="num"><strong>{money(p.current_price)}</strong></td>
                <td>
                  <div className="row" style={{ gap: '.4rem' }}>
                    <input className="inline" type="number" min="0" style={{ width: 90 }} value={stock[p.id] ?? p.current_stock}
                           onChange={(e) => setStock((s) => ({ ...s, [p.id]: e.target.value }))} />
                    <button className="btn secondary small" disabled={stock[p.id] === undefined || stock[p.id] === ''}
                            onClick={() => run(async () => { await api.post(`/products/${p.id}/update_stock`, { new_stock: Number(stock[p.id]) }); setStock((s) => { const c = { ...s }; delete c[p.id]; return c; }); }, `Stock for ${p.name} updated - price recalculated`)}>Set</button>
                    <span className="muted small">/ {num(p.max_stock)}</span>
                  </div>
                </td>
                <td className="right"><button className="btn danger small" onClick={() => window.confirm(`Deactivate ${p.name}?`) && run(() => api.del(`/products/${p.id}`), `${p.name} deactivated`)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 style={{ margin: '1.75rem 0 .75rem' }}>Add a product</h3>
      <form onSubmit={add}>
        <div className="form-grid">
          <div className="field"><label>SKU</label><input required value={form.sku} onChange={set('sku')} placeholder="UMB-002" /></div>
          <div className="field"><label>Name</label><input required value={form.name} onChange={set('name')} placeholder="Compact Umbrella" /></div>
          <div className="field"><label>Category</label>
            <select value={form.category} onChange={set('category')}>{CATEGORIES.map((c) => <option key={c} value={c}>{categoryLabel(c)}</option>)}</select></div>
          <div className="field"><label>Base price</label><input required type="number" min="1" step="any" value={form.base_price} onChange={set('base_price')} /></div>
          <div className="field"><label>Unit cost</label><input required type="number" min="0" step="any" value={form.cost} onChange={set('cost')} /></div>
          <div className="field"><label>Min price</label><input type="number" min="0" step="any" value={form.price_min} onChange={set('price_min')} placeholder="optional" /></div>
          <div className="field"><label>Max price</label><input type="number" min="0" step="any" value={form.price_max} onChange={set('price_max')} placeholder="optional" /></div>
          <div className="field"><label>Price step</label><input type="number" min="0.01" step="any" value={form.price_step} onChange={set('price_step')} /></div>
          <div className="field"><label>Stock</label><input type="number" min="0" value={form.current_stock} onChange={set('current_stock')} /></div>
          <div className="field"><label>Max stock</label><input type="number" min="1" value={form.max_stock} onChange={set('max_stock')} /></div>
          <button className="btn" type="submit">+ Add product</button>
        </div>
      </form>
    </section>
  );
}

function Rules({ products, onChanged }) {
  const rules = useAsync(() => api.get('/rules'), []);
  const types = useAsync(() => api.get('/rules/types'), []);
  const [form, setForm] = useState(EMPTY_RULE);
  const [msg, setMsg] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const typeInfo = (t) => types.data?.rule_types.find((x) => x.type === t);

  const run = async (fn, ok) => {
    try { await fn(); setMsg({ ok: true, text: ok }); rules.reload(); await onChanged(); }
    catch (e) { setMsg({ ok: false, text: e.message }); }
  };
  const add = (e) => {
    e.preventDefault();
    run(() => api.post('/rules', { ...form, value: Number(form.value), scope_value: form.scope === 'global' ? null : form.scope_value, note: form.note || null }),
      'Rule created - all prices recalculated');
  };
  const scopeName = (r) => {
    if (r.scope === 'global') return 'All products';
    if (r.scope === 'category') return `Category: ${categoryLabel(r.scope_value)}`;
    const p = products.find((x) => String(x.id) === String(r.scope_value));
    return `Product: ${p ? p.name : r.scope_value}`;
  };

  return (
    <section className="section">
      <h2 className="section-title">🛡️ Pricing Guardrails</h2>
      <p className="section-subtitle">Business rules the ML model can never break. A product-level rule beats a category rule, which beats a global rule; ties go to the stricter one.</p>
      <Flash msg={msg} />
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Applies to</th><th>Rule</th><th className="num">Value</th><th>Note</th><th>Status</th><th /></tr></thead>
          <tbody>
            {(rules.data || []).map((r) => (
              <tr key={r.id} className={r.is_active ? '' : 'dim'}>
                <td>{scopeName(r)}</td>
                <td>{typeInfo(r.rule_type)?.description || r.rule_type}</td>
                <td className="num">{r.rule_type === 'freeze' ? '—' : r.value}</td>
                <td>{r.note || ''}</td>
                <td><button className={`btn small ${r.is_active ? '' : 'secondary'}`} onClick={() => run(() => api.put(`/rules/${r.id}`, { is_active: !r.is_active }), r.is_active ? 'Rule paused' : 'Rule activated')}>{r.is_active ? 'Active' : 'Paused'}</button></td>
                <td className="right"><button className="btn danger small" onClick={() => run(() => api.del(`/rules/${r.id}`), 'Rule deleted')}>Delete</button></td>
              </tr>
            ))}
            {rules.data?.length === 0 && <tr><td colSpan="6" className="muted">No custom rules yet. Each product already has its own min/max, margin floor and 10% per-update change limit.</td></tr>}
          </tbody>
        </table>
      </div>

      <h3 style={{ margin: '1.75rem 0 .75rem' }}>Add a rule</h3>
      <form onSubmit={add}>
        <div className="form-grid">
          <div className="field"><label>Scope</label>
            <select value={form.scope} onChange={set('scope')}><option value="global">All products</option><option value="category">A category</option><option value="product">One product</option></select></div>
          {form.scope === 'category' && <div className="field"><label>Category</label>
            <select required value={form.scope_value} onChange={set('scope_value')}><option value="">Choose…</option>{CATEGORIES.map((c) => <option key={c} value={c}>{categoryLabel(c)}</option>)}</select></div>}
          {form.scope === 'product' && <div className="field"><label>Product</label>
            <select required value={form.scope_value} onChange={set('scope_value')}><option value="">Choose…</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>}
          <div className="field"><label>Rule</label>
            <select value={form.rule_type} onChange={set('rule_type')}>{(types.data?.rule_types || []).map((t) => <option key={t.type} value={t.type}>{t.description}</option>)}</select></div>
          {form.rule_type !== 'freeze' && <div className="field"><label>Value · <span style={{ textTransform: 'none' }}>{typeInfo(form.rule_type)?.unit}</span></label>
            <input required type="number" min="0" step="any" value={form.value} onChange={set('value')} /></div>}
          <div className="field"><label>Note</label><input value={form.note} onChange={set('note')} placeholder="e.g. Diwali sale cap" /></div>
          <button className="btn" type="submit">+ Add rule</button>
        </div>
      </form>
    </section>
  );
}

export default function AdminPanel({ products, onChanged, currentUser }) {
  return (<><Products products={products} onChanged={onChanged} /><Rules products={products} onChanged={onChanged} /><UserManagement currentUser={currentUser} /></>);
}
