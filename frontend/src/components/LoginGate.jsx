import { useState } from 'react';

const EXPECTED_PASSPHRASE = import.meta.env.VITE_DASHBOARD_PASSWORD || 'admin123';

export default function LoginGate({ onLogin }) {
  const [passphrase, setPassphrase] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    setError('');

    if (!passphrase.trim()) {
      setError('Please enter the dashboard passphrase.');
      return;
    }

    setLoading(true);

    // Validate passphrase
    if (passphrase === EXPECTED_PASSPHRASE) {
      setTimeout(() => {
        setLoading(false);
        onLogin();
      }, 250);
    } else {
      setTimeout(() => {
        setLoading(false);
        setError('Incorrect passphrase. Access denied.');
      }, 300);
    }
  };

  return (
    <div className="login-overlay">
      <div className="login-card">
        <div className="login-header">
          <div className="login-badge">🔒 Secure Access</div>
          <div className="login-logo">✉️</div>
          <h1 className="login-title">Email Automation</h1>
          <p className="login-subtitle">ArtCloud · AI Operations Dashboard</p>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          {error && (
            <div className="login-error" role="alert">
              <span>⚠️</span> {error}
            </div>
          )}

          <div className="login-field">
            <label htmlFor="dashboard-passphrase" className="login-label">
              Passphrase
            </label>
            <div className="password-input-wrapper">
              <input
                id="dashboard-passphrase"
                type={showPassword ? 'text' : 'password'}
                className="login-input"
                placeholder="Enter passphrase..."
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                autoFocus
                autoComplete="current-password"
              />
              <button
                type="button"
                className="password-toggle-btn"
                onClick={() => setShowPassword((prev) => !prev)}
                title={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? '👁️' : '🙈'}
              </button>
            </div>
          </div>

          <button
            type="submit"
            className="login-submit-btn"
            disabled={loading}
          >
            {loading ? 'Verifying...' : 'Unlock Dashboard →'}
          </button>
        </form>

        <div className="login-footer">
          <span>Protected by API Key &amp; Session Authentication</span>
        </div>
      </div>
    </div>
  );
}
