import React, { useState } from 'react';
import { api } from '../api';
import { useAsync } from '../utils/hooks';
import { dateTime } from '../utils/format';

export default function UserManagement({ currentUser }) {
  const users = useAsync(() => api.get('/auth/users'), []);
  const [msg, setMsg] = useState(null);
  const [form, setForm] = useState({ username: '', password: '', role: 'viewer' });
  const [reset, setReset] = useState({ id: null, password: '' });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const run = async (fn, ok) => {
    try { await fn(); setMsg({ ok: true, text: ok }); users.reload(); } catch (e) { setMsg({ ok: false, text: e.message }); }
  };

  return (
    <section className="section">
      <h2 className="section-title">👥 Users &amp; Access</h2>
      <p className="section-subtitle"><strong>Administrators</strong> can change prices, products, rules and models. <strong>Viewers</strong> can look at everything and run what-if simulations, but cannot change anything.</p>
      {msg && <div className={`msg ${msg.ok ? 'ok' : 'err'}`}>{msg.text}</div>}
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last sign-in</th><th /></tr></thead>
          <tbody>
            {(users.data || []).map((u) => {
              const me = u.id === currentUser.id;
              return (
                <React.Fragment key={u.id}>
                  <tr className={u.is_active ? '' : 'dim'}>
                    <td><strong>{u.username}</strong> {me && <span className="badge info">you</span>} {u.must_change_password && <span className="badge warn">temp password</span>}</td>
                    <td><span className={`badge ${u.role === 'admin' ? 'ok' : ''}`}>{u.role}</span></td>
                    <td>{u.is_active ? 'Active' : 'Disabled'}</td>
                    <td>{u.last_login ? dateTime(u.last_login) : 'never'}</td>
                    <td className="right">
                      <div className="row" style={{ justifyContent: 'flex-end', gap: '.35rem' }}>
                        <button className="btn secondary small" disabled={me} onClick={() => run(() => api.put(`/auth/users/${u.id}`, { role: u.role === 'admin' ? 'viewer' : 'admin' }), `${u.username} is now ${u.role === 'admin' ? 'a viewer' : 'an administrator'}`)}>Make {u.role === 'admin' ? 'viewer' : 'admin'}</button>
                        <button className="btn secondary small" disabled={me} onClick={() => run(() => api.put(`/auth/users/${u.id}`, { is_active: !u.is_active }), u.is_active ? `${u.username} disabled and signed out` : `${u.username} enabled`)}>{u.is_active ? 'Disable' : 'Enable'}</button>
                        <button className="btn secondary small" onClick={() => setReset(reset.id === u.id ? { id: null, password: '' } : { id: u.id, password: '' })}>Reset password</button>
                        <button className="btn danger small" disabled={me} onClick={() => window.confirm(`Delete user ${u.username}?`) && run(() => api.del(`/auth/users/${u.id}`), `${u.username} deleted`)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                  {reset.id === u.id && (
                    <tr><td colSpan="5">
                      <form className="row" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.put(`/auth/users/${u.id}`, { password: reset.password }); setReset({ id: null, password: '' }); }, `Password reset for ${u.username} - they must change it at next sign-in`); }}>
                        <input className="inline" type="password" minLength={8} required placeholder="New temporary password (min 8)" style={{ width: 280 }} value={reset.password} onChange={(e) => setReset({ id: u.id, password: e.target.value })} />
                        <button className="btn small" type="submit">Save</button>
                      </form>
                    </td></tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <h3 style={{ margin: '1.75rem 0 .75rem' }}>Add a user</h3>
      <form onSubmit={(e) => { e.preventDefault(); run(async () => { await api.post('/auth/users', form); setForm({ username: '', password: '', role: 'viewer' }); }, `User ${form.username} created`); }}>
        <div className="form-grid">
          <div className="field"><label>Username</label><input required minLength={3} value={form.username} onChange={set('username')} autoComplete="off" /></div>
          <div className="field"><label>Password (min 8)</label><input required type="password" minLength={8} value={form.password} onChange={set('password')} autoComplete="new-password" /></div>
          <div className="field"><label>Role</label><select value={form.role} onChange={set('role')}><option value="viewer">Viewer (read-only)</option><option value="admin">Administrator</option></select></div>
          <button className="btn" type="submit">+ Add user</button>
        </div>
      </form>
    </section>
  );
}
