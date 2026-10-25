/*
 * On/off switch with a label and a one-line consequence
 * (Design System §5 · Toggle). Uses role="switch" so screen readers
 * announce it as on/off rather than as a checkbox.
 */
import { useId } from 'react'
import './Toggle.css'

export default function Toggle({ label, description, checked, onChange, disabled = false }) {
  const id = useId()

  return (
    <div className="toggle">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-describedby={description ? `${id}-desc` : undefined}
        className="toggle__switch"
        onClick={() => onChange(!checked)}
        disabled={disabled}
      >
        <span className="toggle__thumb" />
      </button>
      <div>
        <label htmlFor={id} className="t-label toggle__label">
          {label}
        </label>
        {description && (
          <p id={`${id}-desc`} className="t-body-sm muted">
            {description}
          </p>
        )}
      </div>
    </div>
  )
}
