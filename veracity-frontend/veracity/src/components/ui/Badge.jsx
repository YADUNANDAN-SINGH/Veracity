/*
 * A verdict in one or two words with its icon (Design System §5 · RiskBadge).
 * Never colour alone: every tone carries an icon and words.
 *
 * tone: 'low' | 'medium' | 'high' | 'neutral'
 */
import Icon from './Icon'
import './Badge.css'

const TONE_ICON = {
  low: 'check-circle',
  medium: 'alert-triangle',
  high: 'octagon',
  neutral: 'help-circle',
}

export default function Badge({ tone = 'neutral', icon, children }) {
  return (
    <span className={`badge badge--${tone} t-label`}>
      <Icon name={icon ?? TONE_ICON[tone]} size={12} />
      {children}
    </span>
  )
}
