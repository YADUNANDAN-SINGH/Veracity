/*
 * Actions (Design System §5 · Button).
 * Rule: one primary button per screen.
 *
 * variant: 'primary' | 'secondary' | 'ghost' | 'danger'
 * size:    'md' | 'sm'
 * href:    renders a link styled as a button (external links open in a new tab)
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
  href,
  children,
  ...rest
}) {
  const classes = `btn btn--${variant} btn--${size} ${className}`.trim()
  const content = (
    <>
      {icon && <Icon name={icon} size={14} />}
      <span>{children}</span>
      {iconRight && <Icon name={iconRight} size={14} />}
    </>
  )

  if (href) {
    const external = href.startsWith('http')
    return (
      <a className={classes} href={href} {...(external && { target: '_blank', rel: 'noreferrer' })} {...rest}>
        {content}
      </a>
    )
  }
  return (
    <button type={type} className={classes} {...rest}>
      {content}
    </button>
  )
}
