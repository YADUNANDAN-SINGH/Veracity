/*
 * The 64px top bar (Design System §5 · AppHeader):
 * logo · step progress · [SIMULATION MODE] · Offline · call status.
 *
 * "Offline" is always visible: privacy is a principle, and nothing
 * leaves the laptop during a call.
 */
import Logo from '../ui/Logo'
import Icon from '../ui/Icon'
import CallStatus from '../ui/CallStatus'
import FlowSteps from './FlowSteps'
import './AppHeader.css'

export default function AppHeader({ step, simulation = false, callStatus = 'idle', elapsed }) {
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
        <CallStatus status={callStatus} elapsed={elapsed} />
      </div>
    </header>
  )
}
