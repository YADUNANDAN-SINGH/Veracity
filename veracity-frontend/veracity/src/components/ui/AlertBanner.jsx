/*
 * Full-width message (Design System §5 · AlertBanner).
 * Rule: at most one banner per screen.
 *
 * tone: 'danger' (live scam alert) | 'caution' | 'info' (brand-tinted notes)
 * Danger banners are announced immediately to screen readers.
 */
import Icon from './Icon'
import './AlertBanner.css'

const TONE_ICON = {
  danger: 'octagon',
  caution: 'alert-triangle',
  info: 'info',
}

export default function AlertBanner({ tone = 'info', title, children }) {
  return (
    <div className={`alert alert--${tone}`} role={tone === 'danger' ? 'alert' : 'note'}>
      <Icon name={TONE_ICON[tone]} size={16} className="alert__icon" />
      <div className="alert__content">
        {title && <p className="t-label">{title}</p>}
        {children && <div className="t-body-sm">{children}</div>}
      </div>
    </div>
  )
}
