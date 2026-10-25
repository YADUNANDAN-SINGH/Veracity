/*
 * Actions (Design System §5 · Button).
 * Rule: one primary button per screen.
 *
 * variant: 'primary' | 'secondary' | 'ghost' | 'danger'
 * size:    'md' | 'sm'
 */
import Icon from './Icon'
import './Button.css'

export default function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  iconRight,
  type = 'button',
  className = '',
  children,
  ...rest
}) {
  return (
    <button
      type={type}
      className={`btn btn--${variant} btn--${size} ${className}`.trim()}
      {...rest}
    >
      {icon && <Icon name={icon} size={14} />}
      <span>{children}</span>
      {iconRight && <Icon name={iconRight} size={14} />}
    </button>
  )
}
