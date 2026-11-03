/*
 * Replayed calls only: type a line and the backend hears it as the caller's
 * words. It goes through the same scam rules as everything else, so judges can
 * try their own scam phrases (or harmless ones) on the live call.
 */
import { useState } from 'react'
import Button from '../ui/Button'
import { sayToSession } from '../../api/session'
import './SayBox.css'

const TRIES = [
  'Don’t tell anyone. Buy gift cards and read me the numbers right now.',
  'This is Officer Davis. There is a warrant for your arrest.',
  'Can you pick up some milk on the way home?',
]

export default function SayBox({ sessionId, disabled }) {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)

  async function say(line) {
    const value = line.trim()
    if (!value || sending) return
    setSending(true)
    setError(null)
    try {
      await sayToSession(sessionId, value)
      setText('')
    } catch (err) {
      setError(err)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="say-box">
      <form
        className="say-box__row"
        onSubmit={(event) => {
          event.preventDefault()
          say(text)
        }}
      >
        <input
          className="say-box__input"
          value={text}
          onChange={(event) => setText(event.target.value)}
          maxLength={300}
          placeholder="Type what the caller says…"
          aria-label="What the caller says"
          disabled={disabled}
        />
        <Button type="submit" disabled={disabled || sending || !text.trim()}>
          Say it
        </Button>
      </form>
      <div className="say-box__tries">
        {TRIES.map((line) => (
          <button key={line} type="button" className="say-box__try t-body-sm" disabled={disabled || sending} onClick={() => say(line)}>
            “{line}”
          </button>
        ))}
      </div>
      {error && <p className="t-body-sm say-box__error">{error.message}</p>}
    </div>
  )
}
