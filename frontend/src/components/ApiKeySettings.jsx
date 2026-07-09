import { useEffect, useState } from 'react'

// Stored client-side only -- this key never touches our database, it's sent
// per-request straight through to Gemini via the backend. Kept in
// localStorage so it survives a page refresh without asking the user again.
const STORAGE_KEY = 'signal_gemini_api_key'

export function getStoredGeminiKey() {
  try {
    return localStorage.getItem(STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export default function ApiKeySettings({ onKeyChange }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [savedKey, setSavedKey] = useState('')

  useEffect(() => {
    const existing = getStoredGeminiKey()
    setSavedKey(existing)
    setDraft(existing)
  }, [])

  function save() {
    const trimmed = draft.trim()
    try {
      if (trimmed) localStorage.setItem(STORAGE_KEY, trimmed)
      else localStorage.removeItem(STORAGE_KEY)
    } catch {
      // localStorage unavailable (private mode etc) -- key just won't persist
    }
    setSavedKey(trimmed)
    onKeyChange?.(trimmed)
    setOpen(false)
  }

  function clear() {
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {}
    setDraft('')
    setSavedKey('')
    onKeyChange?.('')
  }

  return (
    <>
      <button className="icon-btn" onClick={() => setOpen(true)}>
        {savedKey ? '🔑 Your key active' : '🔑 Add Gemini key'}
      </button>

      {open && (
        <div className="modal-overlay" onClick={() => setOpen(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3>Use your own Gemini API key</h3>
            <p className="modal-desc">
              Summaries normally run on this app's shared Gemini key, which has a limited
              free quota shared across every visitor. Add your own key to generate as many
              AI summaries as you want, on your own quota. It's stored only in your browser
              (localStorage) and sent straight through to Google with each summary request —
              it's never saved on our server or database.
            </p>
            <input
              type="password"
              placeholder="Paste your Gemini API key (starts with AIza...)"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="modal-input"
              autoFocus
            />
            <p className="modal-hint">
              Don't have one? Get a free key at{' '}
              <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
                aistudio.google.com/apikey
              </a>
              .
            </p>
            <div className="modal-actions">
              {savedKey && (
                <button className="btn btn-ghost" onClick={clear}>
                  Remove key
                </button>
              )}
              <button className="btn" onClick={() => setOpen(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={save} disabled={!draft.trim() && !savedKey}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
