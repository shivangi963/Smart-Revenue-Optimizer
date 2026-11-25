import React, { useCallback, useEffect, useState } from 'react';
import './App.css';
import { API_BASE, api, getToken, setToken, setUnauthorizedHandler } from './api';
import Login from './components/Login';
import MainApp from './MainApp';

// Authentication shell: decides between "checking", "sign in", "backend unreachable" and the app itself.
export default function App() {
  const [state, setState] = useState({ phase: 'checking', user: null, error: null, notice: null });

  const check = useCallback(async () => {
    setState((s) => ({ ...s, phase: 'checking', error: null }));
    try {
      const status = await api.get('/auth/status');          // public endpoint
      if (!status.auth_enabled || getToken()) {
        const me = await api.get('/auth/me');
        setState({ phase: 'in', user: me, error: null, notice: null });
      } else {
        setState({ phase: 'login', user: null, error: null, notice: null });
      }
    } catch (e) {
      if (e.status === 401) setState((prev) => ({ phase: 'login', user: null, error: null, notice: prev.notice }));
      else setState({ phase: 'error', user: null, error: e.message, notice: null });
    }
  }, []);

  useEffect(() => {
    // any 401 from the API (expired / revoked session) drops us back to the sign-in screen
    setUnauthorizedHandler((message) => setState({ phase: 'login', user: null, error: null, notice: message }));
    check();
    return () => setUnauthorizedHandler(null);
  }, [check]);

  const logout = () => { setToken(null); setState({ phase: 'login', user: null, error: null, notice: null }); };

  if (state.phase === 'checking') {
    return <div className="loading"><h1>🎯 Smart Revenue Optimizer</h1><div className="spinner" /><p>Connecting…</p></div>;
  }
  if (state.phase === 'error') {
    return (
      <div className="error-screen">
        <h2>⚠️ Can't reach the backend</h2>
        <p className="muted" style={{ margin: '.5rem 0 1rem' }}>{state.error}. Start the API in a terminal, then retry:</p>
        <code>cd backend</code><code>python run.py</code>
        <p className="muted small">Expected at {API_BASE} (override with REACT_APP_API_URL).</p>
        <button className="btn" style={{ marginTop: '1rem' }} onClick={check}>Retry</button>
      </div>
    );
  }
  if (state.phase === 'login') {
    return <Login notice={state.notice} onLoggedIn={(user) => setState({ phase: 'in', user, error: null, notice: null })} />;
  }
  return <MainApp key={state.user.id} user={state.user} onLogout={logout}
                  onUserChange={(user) => setState((s) => ({ ...s, user }))} />;
}
