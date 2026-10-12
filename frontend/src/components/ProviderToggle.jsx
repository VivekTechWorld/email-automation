import { useState, useCallback } from 'react';
import { setProvider } from '../api';

/**
 * ProviderToggle — Live AI provider switcher card
 * Default: Gemini (Cloud). Toggle to Local only if Ollama is set up.
 */
export default function ProviderToggle({ provider, onProviderChange, onToast }) {
  const [switching, setSwitching] = useState(false);
  const isGemini = provider === 'gemini';

  const handleToggle = useCallback(async () => {
    const next = isGemini ? 'local' : 'gemini';
    setSwitching(true);
    try {
      await setProvider(next);
      onProviderChange(next);
      onToast(
        `✅ Switched to ${next === 'gemini' ? 'Gemini 1.5 Flash' : 'Local Ollama'}`,
        'success'
      );
    } catch (err) {
      onToast(`❌ ${err.message}`, 'error');
    } finally {
      setSwitching(false);
    }
  }, [isGemini, onProviderChange, onToast]);

  return (
    <div className={`provider-card ${isGemini ? 'active-gemini' : 'active-local'}`}>
      {/* Left: current provider info */}
      <div className="provider-info">
        <div className={`provider-icon ${isGemini ? 'gemini' : 'local'}`}>
          {isGemini ? '✦' : '🖥️'}
        </div>
        <div>
          <div className="provider-label">
            {isGemini ? 'Gemini 1.5 Flash' : 'Local Ollama'}
          </div>
          <div className="provider-desc">
            {isGemini
              ? 'Google Cloud AI — gemini-1.5-flash (free tier) · Active'
              : 'Local models — email-support-v2 + qwen2.5:7b · Requires Ollama'}
          </div>
        </div>
      </div>

      {/* Right: toggle + status badge */}
      <div className="provider-toggle-wrap">
        {switching && (
          <span className="provider-switching">Switching…</span>
        )}

        <span className={`provider-option ${!isGemini ? 'active' : ''}`}>
          Local
        </span>

        <label
          className="toggle-switch"
          title={switching ? 'Switching…' : `Switch to ${isGemini ? 'Local Ollama' : 'Gemini'}`}
        >
          <input
            type="checkbox"
            checked={isGemini}
            onChange={handleToggle}
            disabled={switching}
            id="provider-toggle"
          />
          <span className="toggle-track" />
          <span className="toggle-thumb" />
        </label>

        <span className={`provider-option ${isGemini ? 'active' : ''}`}>
          Gemini
        </span>

        <span className={`provider-status-badge ${provider}`}>
          {isGemini ? '☁️ Cloud · Active' : '⚡ Local'}
        </span>
      </div>
    </div>
  );
}
