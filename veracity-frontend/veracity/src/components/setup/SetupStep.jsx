/*
 * One row of the system check, built from GET /api/health
 * (Design System §5 · SetupStep).
 *
 * Never colour alone: every status pairs a colour with a shape
 * (filled check, "!", triangle, number) and a word (OK, Fix this…).
 */
import Icon from '../ui/Icon'
import './SetupStep.css'

const STATUS_WORD = {
  ok: 'OK',
  fail: 'Fix this',
  warn: 'Optional',
  pending: 'Checking…',
}

export default function SetupStep({ index, title, status, detail, fix, statusText }) {
  return (
    <li className={`setup-step setup-step--${status}`}>
      <span className="setup-step__marker" aria-hidden="true">
        {status === 'ok' && <Icon name="check" size={13} />}
        {status === 'fail' && '!'}
        {status === 'warn' && <Icon name="alert-triangle" size={13} />}
        {status === 'pending' && index}
      </span>

      <div className="setup-step__body">
        <p className="t-label">{title}</p>
        <p className="t-body-sm muted">{detail}</p>
        {fix && <code className="code-chip setup-step__fix">{fix}</code>}
      </div>

      <span className="setup-step__status t-label">{statusText ?? STATUS_WORD[status]}</span>
    </li>
  )
}
