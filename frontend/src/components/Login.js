
import React, { useEffect, useState } from 'react';
import { api, login } from '../api';

export default function Login({ onLoggedIn, notice }) {
  const [mode, setMode] = useState('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [show, setShow] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);

  useEffect(() => {
    api.get('/auth/status')
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  const switchMode = (nextMode) => {
    setMode(nextMode);
    setError(null);
    setSuccess(null);
    setPassword('');
    setConfirmPassword('');
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSuccess(null);

    const cleanUsername = username.trim();

    try {
      if (mode === 'register') {
        if (password !== confirmPassword) {
          throw new Error('Passwords do not match.');
        }

        if (password.length < 8) {
          throw new Error('Password must contain at least 8 characters.');
        }

        await api.post('/auth/register', {
          username: cleanUsername,
          password,
        });

        setSuccess('Account created successfully! Signing you in...');

        const session = await login(cleanUsername, password);
        onLoggedIn(session.user);
      } else {
        const session = await login(cleanUsername, password);
        onLoggedIn(session.user);
      }
    } catch (err) {
      setError(err.message || 'Something went wrong.');
      setPassword('');
      setConfirmPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="login-logo">🎯</div>

        <h1>Smart Revenue Optimizer</h1>

        <p className="muted">
          {mode === 'login'
            ? 'Sign in to manage prices'
            : 'Create your account to get started'}
        </p>

        {notice && mode === 'login' && (
          <div className="msg err">{notice}</div>
        )}

        {error && (
          <div className="msg err" role="alert">{error}</div>
        )}

        {success && (
          <div className="msg ok" role="status">{success}</div>
        )}

        <div className="field" style={{ marginTop: '.75rem' }}>
          <label htmlFor="u">Username</label>
          <input
            id="u"
            autoFocus
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>

        <div className="field" style={{ marginTop: '.75rem' }}>
          <label htmlFor="p">Password</label>
          <div className="pw-row">
            <input
              id="p"
              type={show ? 'text' : 'password'}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button
              type="button"
              className="btn secondary small"
              onClick={() => setShow((s) => !s)}
            >
              {show ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>

        {mode === 'register' && (
          <div className="field" style={{ marginTop: '.75rem' }}>
            <label htmlFor="confirm-password">Confirm Password</label>
            <input
              id="confirm-password"
              type={show ? 'text' : 'password'}
              autoComplete="new-password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </div>
        )}

        <button
          className="btn login-btn"
          type="submit"
          disabled={busy || !username.trim() || !password ||
            (mode === 'register' && !confirmPassword)}
        >
          {busy
            ? mode === 'login' ? 'Signing in…' : 'Creating account…'
            : mode === 'login' ? 'Sign in' : 'Create Account'}
        </button>

        <p className="muted" style={{ textAlign: 'center', marginTop: '1.25rem' }}>
          {mode === 'login'
            ? "Don't have an account? "
            : 'Already have an account? '}
          <button
            type="button"
            onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}
            style={{
              border: 'none',
              background: 'none',
              color: 'var(--primary-dark)',
              fontWeight: 700,
              cursor: 'pointer',
              fontSize: 'inherit',
            }}
          >
            {mode === 'login' ? 'Register' : 'Sign in'}
          </button>
        </p>

        {mode === 'login' && status?.default_credentials && (
          <div className="banner info" style={{ marginTop: '1.25rem', marginBottom: 0 }}>
            <strong>First run:</strong> demo account{' '}
            <code>{status.hint_username}</code> /{' '}
            <code>{status.hint_password}</code>.
            You will be asked to change the password after signing in.

            <div>
              <button
                type="button"
                className="btn secondary small"
                style={{ marginTop: '.5rem' }}
                onClick={() => {
                  setUsername(status.hint_username);
                  setPassword(status.hint_password);
                }}
              >
                Fill in
              </button>
            </div>
          </div>
        )}
      </form>
    </div>
  );
}
