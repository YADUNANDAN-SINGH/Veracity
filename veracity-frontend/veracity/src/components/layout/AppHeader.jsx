/*
 * The 64px top bar (Design System §5 · AppHeader):
 * logo · step progress · [SIMULATION MODE] · Offline · theme · call status.
 *
 * "Offline" is always visible: privacy is a principle, and nothing
 * leaves the laptop during a call.
 */
import Logo from '../ui/Logo'
import Icon from '../ui/Icon'
import CallStatus from '../ui/CallStatus'
import FlowSteps from './FlowSteps'
import { useTheme } from '../../hooks/useTheme'
import './AppHeader.css'

export default function AppHeader({ step, simulation = false, callStatus = 'idle', elapsed }) {
  const { theme, toggle } = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'

  return (
    <header className="app-header">
      <Logo />

      <div className="app-header__steps">
        <FlowSteps current={step} />
      </div>

      <div className="app-header__meta">
        {simulation && (
          <span className="app-header__sim t-code">
            <Icon name="terminal" size={13} />
            SIMULATION MODE
          </span>
        )}
        <span className="app-header__offline t-body-sm">
          <Icon name="lock" size={13} />
          Offline
        </span>
        <button
          type="button"
          className="app-header__theme"
          onClick={toggle}
          aria-label={`Switch to ${next} mode`}
          title={`Switch to ${next} mode`}
        >
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={15} />
        </button>
        <CallStatus status={callStatus} elapsed={elapsed} />
      </div>
    </header>
  )
}
