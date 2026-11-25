import React, { useCallback, useEffect, useState } from 'react';
import './App.css';
import { API_BASE, api } from './api';
import { setCurrency } from './utils/format';
import KpiStrip from './components/KpiStrip';
import ProductSelector from './components/ProductSelector';
import PriceAnalysis from './components/PriceAnalysis';
import RevenueImpactChart from './components/RevenueImpactChart';
import PriceSimulator from './components/PriceSimulator';
import PriceHistoryChart from './components/PriceHistoryChart';
import ModelAnalytics from './components/ModelAnalytics';
import AdminPanel from './components/AdminPanel';
import CurrencyConverter from './components/CurrencyConverter';
import AccountPanel from './components/AccountPanel';

const TABS = [
  ['dashboard', '📊 Dashboard'],
  ['simulator', '🧪 Simulator'],
  ['history', '📈 History & Forecast'],
  ['model', '🤖 Model Analytics'],
  ['admin', '⚙️ Admin', 'admin'],        // third item = role required
  ['currency', '💱 Currency'],
  ['account', '👤 Account'],
];
const REFRESH_MS = 30000;

const FEATURES = [
  ['🌤️', 'Weather Impact', 'Umbrella prices rise in the rain, ice cream in the heat, hot drinks when it is cold - using live weather.'],
  ['⏰', 'Time & Season', 'Evening peaks, weekends and seasonal buying patterns are learned from data, not hard-coded.'],
  ['📈', 'Demand Sensing', 'Page views, add-to-cart and conversion rates (smoothed over recent observations) move prices automatically.'],
  ['📦', 'Stock Management', 'Scarce items earn a premium; overstocked items are discounted to clear.'],
  ['🎉', 'Festivals & Events', 'Real holiday calendar (Diwali, Dussehra, Christmas…) lifts prices as the event approaches.'],
  ['🛡️', 'Business Guardrails', 'Min/max price, margin floor and a per-update change cap keep every price safe and explainable.'],
];

export default function MainApp({ user, onLogout, onUserChange }) {
  const isAdmin = user.role === 'admin';
  const [boot, setBoot] = useState({ loading: true, error: null });
  const [products, setProducts] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [price, setPrice] = useState(null);
  const [holidays, setHolidays] = useState([]);
  const [health, setHealth] = useState(null);
  const [tab, setTab] = useState('dashboard');
  const [priceError, setPriceError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadProducts = useCallback(async () => {
    const list = await api.get('/products');
    setProducts(list);
    setSelectedId((prev) => (prev && list.some((p) => p.id === prev) ? prev : list[0]?.id ?? null));
    return list;
  }, []);

  const loadHealth = useCallback(() => api.get('/health').then(setHealth).catch(() => setHealth(null)), []);

  const loadPrice = useCallback(async (id, force = false) => {
    if (!id) return;
    try {
      const fresh = await api.get(`/prices/${id}/current${force ? '?refresh=true' : ''}`);
      setPrice(fresh);
      setProducts((list) => list.map((p) => (p.id === id ? { ...p, current_price: fresh.final_price } : p)));
      setPriceError(null);
    } catch (e) { setPriceError(e.message); }
  }, []);

  const boot_ = useCallback(async () => {
    setBoot({ loading: true, error: null });
    try {
      const [config, , hol] = await Promise.all([
        api.get('/api/config'), loadProducts(), api.get('/api/holidays/upcoming?days=60'), loadHealth(),
      ]);
      setCurrency(config.currency);
      setHolidays(hol.upcoming_holidays);
      setBoot({ loading: false, error: null });
    } catch (e) { setBoot({ loading: false, error: e.message }); }
  }, [loadProducts, loadHealth]);

  useEffect(() => { boot_(); }, [boot_]);

  useEffect(() => {
    if (!selectedId) return undefined;
    setPrice(null);
    loadPrice(selectedId);
    const t = setInterval(() => { loadPrice(selectedId); loadProducts(); loadHealth(); }, REFRESH_MS);
    return () => clearInterval(t);
  }, [selectedId, loadPrice, loadProducts, loadHealth]);

  const recalc = async () => { setRefreshing(true); await loadPrice(selectedId, true); await loadProducts(); setRefreshing(false); };
  const afterAdminChange = async () => { await loadProducts(); await loadPrice(selectedId, true); };

  if (boot.loading) {
    return <div className="loading"><h1>🎯 Smart Revenue Optimizer</h1><div className="spinner" /><p>Connecting to the pricing engine…</p></div>;
  }
  if (boot.error) {
    return (
      <div className="error-screen">
        <h2>⚠️ Can't reach the backend</h2>
        <p className="muted" style={{ margin: '.5rem 0 1rem' }}>{boot.error}. Start the API in a terminal, then retry:</p>
        <code>cd backend</code><code>python run.py</code>
        <p className="muted small">Expected at {API_BASE} (override with REACT_APP_API_URL).</p>
        <button className="btn" style={{ marginTop: '1rem' }} onClick={boot_}>Retry</button>
      </div>
    );
  }

  const selected = products.find((p) => p.id === selectedId);
  const training = health?.model?.state === 'training';
  const online = !!health;

  return (
    <div className="app">
      <header className="header">
        <div className="user-bar">
          <span className="user-chip" title={isAdmin ? 'Administrator' : 'Viewer (read-only)'}>👤 {user.username} · {isAdmin ? 'admin' : 'viewer'}</span>
          <button className="btn secondary small" onClick={onLogout}>Sign out</button>
        </div>
        <div className="header-content">
          <h1>🎯 Smart Revenue Optimizer</h1>
          <p>Explainable, real-time dynamic pricing powered by machine learning</p>
          {/*<div className="status-row">
            <div className={`status ${online ? '' : 'off'}`}>
              <span className={`status-indicator ${online ? 'online' : ''}`} />
              {online ? 'Backend connected' : 'Backend offline'}
            </div>
            {online && (
              <div className={`status ${training ? 'warn' : ''}`}>
                <span className="status-indicator online" />
                {training ? 'Training model… (fallback rules active)' : `Model: ${modelLabel(health.model.active)}`}
              </div>
            )}
          </div>*/}
        </div>
      </header>

      <nav className="tabs"><div className="tabs-inner">
        {TABS.filter(([, , role]) => !role || role === user.role).map(([id, label]) => <button key={id} className={`tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>{label}</button>)}
      </div></nav>

      <main className="main-content">
        {user.must_change_password && tab !== 'account' && (
          <div className="banner">🔐 You are signed in with a temporary password. <button className="btn small" style={{ marginLeft: '.5rem' }} onClick={() => setTab('account')}>Change it now</button></div>
        )}
        {training && <div className="banner info">⏳ The ML model is being trained for the first time (about a minute). Prices use simple rules meanwhile and will switch to the model automatically.</div>}

        {tab === 'dashboard' && (
          <>
            <KpiStrip />
            <ProductSelector products={products} selectedId={selectedId} onSelect={setSelectedId} />
            {priceError && <div className="msg err">{priceError}</div>}
            <PriceAnalysis product={selected} price={price} holidays={holidays} onRefresh={recalc} refreshing={refreshing} />
            <RevenueImpactChart />
            <section className="section info-section">
              <h2 className="section-title">⚙️ How Smart Revenue Optimizer Works</h2>
              <div className="features-grid">
                {FEATURES.map(([icon, title, text]) => (
                  <div key={title} className="feature-card"><div className="feature-icon">{icon}</div><h3 className="feature-title">{title}</h3><p className="feature-description">{text}</p></div>
                ))}
              </div>
            </section>
          </>
        )}
        {tab === 'simulator' && <PriceSimulator products={products} initialProductId={selectedId} />}
        {tab === 'history' && <PriceHistoryChart products={products} initialProductId={selectedId} />}
        {tab === 'model' && <ModelAnalytics products={products} initialProductId={selectedId} isAdmin={isAdmin} />}
        {tab === 'admin' && isAdmin && <AdminPanel products={products} onChanged={afterAdminChange} currentUser={user} />}
        {tab === 'currency' && <CurrencyConverter products={products} />}
        {tab === 'account' && <AccountPanel user={user} onUserChange={onUserChange} />}
      </main>

      <footer className="footer">
        <div className="footer-content">
          <p className="footer-text">Smart Revenue Optimizer • Machine Learning Project</p>
          <p className="footer-subtext">React + FastAPI + scikit-learn • Explainable real-time price optimisation</p>
          <div className="footer-links">
            <span className="api-status"><span className={`status-dot ${online ? 'online' : ''}`} /> API: {API_BASE}</span>
            <span className="refresh-hint">Prices refresh automatically every 30 seconds</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
