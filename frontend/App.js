import React, { useState, useCallback, useEffect } from 'react';
import { useConversation } from '@elevenlabs/react';
import './App.css';

const AGENT_ID = 'agent_3901kgmswk5ve9etvy9c1h4g2e40';
const API_URL = 'http://168.231.87.2:8000';

function App() {
  const [messages, setMessages] = useState([]);
  const [textInput, setTextInput] = useState('');
  const [sessionId] = useState('session-' + Date.now());
  const [showAudit, setShowAudit] = useState(false);
  const [auditData, setAuditData] = useState(null);
  const [latestProfile, setLatestProfile] = useState(null);
  const [loading, setLoading] = useState(false);

  const conversation = useConversation({
    onConnect: () => console.log('Connected to ElevenLabs'),
    onDisconnect: () => console.log('Disconnected'),
    onMessage: (msg) => {
      setMessages(prev => [...prev, {
        role: msg.source === 'user' ? 'user' : 'assistant',
        text: msg.message,
      }]);
    },
    onError: (err) => console.error('ElevenLabs error:', err),
  });

  const startCall = useCallback(async () => {
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      await conversation.startSession({ agentId: AGENT_ID });
    } catch (err) {
      console.error('Failed to start:', err);
    }
  }, [conversation]);

  const endCall = useCallback(async () => {
    await conversation.endSession();
  }, [conversation]);

  const sendText = async () => {
    if (!textInput.trim()) return;
    const userMsg = textInput;
    setTextInput('');
    setMessages(prev => [...prev, { role: 'user', text: userMsg }]);
    setLoading(true);

    try {
      const resp = await fetch(`${API_URL}/chat/${sessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg }),
      });
      const data = await resp.json();
      setMessages(prev => [...prev, { role: 'assistant', text: data.reply }]);
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', text: 'Error: ' + err.message }]);
    }
    setLoading(false);
  };

  const fetchAudit = async () => {
    try {
      const [auditResp, profileResp] = await Promise.all([
        fetch(`${API_URL}/audit`),
        fetch(`${API_URL}/audit/latest-profile`),
      ]);
      setAuditData(await auditResp.json());
      setLatestProfile(await profileResp.json());
    } catch (err) {
      console.error('Failed to fetch audit:', err);
    }
  };

  useEffect(() => {
    if (showAudit) fetchAudit();
  }, [showAudit]);

  return (
    <div className="App">
      <header className="App-header">
        <h1>Explainable AI Financial Advisor</h1>
        <p className="subtitle">MiFID II Investment Suitability Assessment</p>
        <p className="status">
          Status: {conversation.status}
          {conversation.isSpeaking && ' — Agent speaking...'}
        </p>
      </header>

      <div className="architecture-bar">
        <span className="arch-item brain">Brain: Ollama llama3.1:8b (On-Premises VPS)</span>
        <span className="arch-item voice">Voice: ElevenLabs (STT + TTS)</span>
        <span className="arch-item backend">Backend: FastAPI</span>
      </div>

      <div className="controls">
        {conversation.status !== 'connected' ? (
          <button className="btn start" onClick={startCall}>
            Start Voice Assessment
          </button>
        ) : (
          <button className="btn end" onClick={endCall}>
            End Call
          </button>
        )}
        <button
          className={`btn audit-btn ${showAudit ? 'active' : ''}`}
          onClick={() => { setShowAudit(!showAudit); }}
        >
          {showAudit ? 'Hide' : 'Show'} Audit Trail
        </button>
      </div>

      <div className="chat-box">
        {messages.length === 0 && (
          <div className="empty-state">
            <p>Start a voice call or type below to begin the investment suitability assessment.</p>
            <p className="hint">The AI advisor will guide you through a series of questions to determine your investor profile.</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <strong>{m.role === 'user' ? 'You' : 'Advisor'}:</strong>
            {' '}{m.text}
          </div>
        ))}
        {loading && <div className="msg assistant loading">Advisor is thinking...</div>}
      </div>

      <div className="text-input">
        <input
          type="text"
          value={textInput}
          onChange={e => setTextInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !loading && sendText()}
          placeholder="Type a message to the advisor..."
          disabled={loading}
        />
        <button onClick={sendText} disabled={loading}>Send</button>
      </div>

      {showAudit && (
        <div className="audit-panel">
          <div className="audit-header">
            <h2>Explainability — Audit Trail</h2>
            <button className="btn refresh-btn" onClick={fetchAudit}>Refresh</button>
          </div>

          {latestProfile && latestProfile.result && (
            <div className="profile-result">
              <h3>Latest Profile Assessment</h3>
              <div className="profile-badge">{latestProfile.result.profile}</div>
              <p className="profile-score">Score: {latestProfile.result.score}</p>

              <div className="explanation-section">
                <h4>Block Scores</h4>
                <div className="score-grid">
                  {Object.entries(latestProfile.result.explanation.block_scores).map(([key, val]) => (
                    <div key={key} className="score-item">
                      <span className="score-label">{key.replace(/_/g, ' ')}</span>
                      <span className="score-value">{val}</span>
                    </div>
                  ))}
                </div>
              </div>

              {latestProfile.result.explanation.restrictions_applied.length > 0 && (
                <div className="explanation-section">
                  <h4>Restrictions Applied</h4>
                  {latestProfile.result.explanation.restrictions_applied.map((r, i) => (
                    <div key={i} className="restriction-item">
                      <strong>{r.rule}</strong>
                      <p>{r.reason}</p>
                      <p className="effect">{r.effect}</p>
                    </div>
                  ))}
                </div>
              )}

              {latestProfile.result.explanation.coherence_checks.length > 0 && (
                <div className="explanation-section warning">
                  <h4>Coherence Warnings</h4>
                  {latestProfile.result.explanation.coherence_checks.map((c, i) => (
                    <div key={i} className="warning-item">{c.detail}</div>
                  ))}
                </div>
              )}

              <div className="explanation-section">
                <h4>Recommended Allocation</h4>
                <div className="allocation-grid">
                  {Object.entries(latestProfile.result.allocation).map(([asset, pct]) => (
                    <div key={asset} className="allocation-item">
                      <div className="allocation-bar" style={{width: `${pct}%`}}></div>
                      <span>{asset}: {pct}%</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="explanation-section">
                <h4>Suitable Products</h4>
                <ul>
                  {latestProfile.result.recommended_products.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>

              <p className="disclaimer">{latestProfile.result.disclaimer}</p>
              <p className="model-info">Assessed by: {latestProfile.result.assessed_by}</p>
            </div>
          )}

          {auditData && (
            <div className="audit-log">
              <h3>Decision Log ({auditData.total_entries} entries)</h3>
              <p className="audit-meta">Model: {auditData.model} | Server: {auditData.server}</p>
              <div className="log-entries">
                {auditData.entries.slice().reverse().slice(0, 20).map((entry, i) => (
                  <div key={i} className={`log-entry ${entry.type}`}>
                    <span className="log-type">{entry.type}</span>
                    <span className="log-time">{entry.timestamp}</span>
                    {entry.last_user_message && <p className="log-msg">User: {entry.last_user_message}</p>}
                    {entry.response && <p className="log-msg">AI: {entry.response}</p>}
                    {entry.profile && <p className="log-msg">Profile: {entry.profile} (score {entry.score})</p>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <footer className="App-footer">
        <p>Explainable AI Demo — All decisions made on-premises by Ollama (llama3.1:8b)</p>
        <p>ElevenLabs provides voice only (speech-to-text + text-to-speech)</p>
      </footer>
    </div>
  );
}

export default App;
