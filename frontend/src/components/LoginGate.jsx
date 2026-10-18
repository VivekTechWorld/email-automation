import { useState } from 'react';
import { Mail, LogIn } from 'lucide-react';
import { login } from '../api';

export default function LoginGate({ onLogin, notice }) {
  const [passphrase, setPassphrase] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!passphrase.trim()) {
      setError('Please enter the dashboard password.');
      return;
    }

    // The password is checked by the backend — it is never stored in this bundle.
    setLoading(true);
    try {
      await login(passphrase);
      onLogin();
    } catch (err) {
      setError(err.message === 'Failed to fetch'
        ? 'Cannot reach the backend. Is the API server running?'
        : err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="card login-card">
        <div className="login-head">
          <div className="brand-mark"><Mail size={24} /></div>
          <div className="login-title">Email Automation</div>
          <div className="login-sub">Sign in to manage replies, leads and knowledge</div>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          {error && <div className="notice error" role="alert">{error}</div>}
          {!error && notice && <div className="notice info" role="status">{notice}</div>}

          <div className="field">
            <label htmlFor="dashboard-passphrase" className="field-label">Password</label>
            <div className="password-wrap">
              <input
                id="dashboard-passphrase"
                type={showPassword ? 'text' : 'password'}
                className="input"
                placeholder="Enter password"
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                autoFocus
                autoComplete="current-password"
              />
              <button type="button" className="btn btn-ghost" onClick={() => setShowPassword((v) => !v)}>
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </div>
          </div>

          <button type="submit" className="btn btn-primary" disabled={loading}>
            <LogIn size={16} />{loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div className="login-foot">Password is verified by the server · sessions expire automatically</div>
      </div>
    </div>
  );
}
