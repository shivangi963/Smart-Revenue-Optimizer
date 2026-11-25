import React, { useState } from 'react';
import { api, setToken } from '../api';
import { dateTime } from '../utils/format';

export default function AccountPanel({ user, onUserChange }) {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' });
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (form.next !== form.confirm) { setMsg({ ok: false, text: 'The new passwords do not match.' }); return; }
    setBusy(true);
    try {
      const session = await api.post('/auth/change-password', { current_password: form.current, new_password: form.next });
      setToken(session.access_token);                 // old tokens (other devices) are now invalid; this one continues
      onUserChange(session.user);
      setForm({ current: '', next: '', confirm: '' });
      setMsg({ ok: true, text: 'Password changed. Any other signed-in devices have been signed out.' });
    } catch (err) { setMsg({ ok: false, text: err.message }); } finally { setBusy(false); }
  };

  return (
    <section className="section">
      <h2 className="section-title">👤 My Account</h2>
      <div className="kpi-grid" style={{ maxWidth: 720 }}>
        <div className="kpi-card"><div className="kpi-label">Username</div><div className="kpi-value" style={{ fontSize: '1.3rem' }}>{user.username}</div></div>
        <div className="kpi-card"><div className="kpi-label">Role</div><div className="kpi-value" style={{ fontSize: '1.3rem' }}>{user.role === 'admin' ? 'Administrator' : 'Viewer'}</div>
          <div className="kpi-sub">{user.role === 'admin' ? 'can change prices, rules, products' : 'read-only access'}</div></div>
        <div className="kpi-card"><div className="kpi-label">Last sign-in</div><div className="kpi-value" style={{ fontSize: '1.1rem' }}>{user.last_login ? dateTime(user.last_login) : '—'}</div></div>
      </div>

      <h3 style={{ margin: '.5rem 0 .75rem' }}>Change password</h3>
      {user.must_change_password && <div className="banner">🔐 You are using a temporary password. Please choose your own now.</div>}
      {msg && <div className={`msg ${msg.ok ? 'ok' : 'err'}`}>{msg.text}</div>}
      <form onSubmit={submit} style={{ maxWidth: 420 }}>
        <div className="field"><label>Current password</label><input type="password" autoComplete="current-password" required value={form.current} onChange={set('current')} /></div>
        <div className="field" style={{ marginTop: '.75rem' }}><label>New password (min 8 characters)</label><input type="password" autoComplete="new-password" minLength={8} required value={form.next} onChange={set('next')} /></div>
        <div className="field" style={{ marginTop: '.75rem' }}><label>Confirm new password</label><input type="password" autoComplete="new-password" minLength={8} required value={form.confirm} onChange={set('confirm')} /></div>
        <button className="btn" type="submit" style={{ marginTop: '1rem' }} disabled={busy}>{busy ? 'Saving…' : 'Change password'}</button>
      </form>
    </section>
  );
}
