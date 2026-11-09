/*
 * The 64px top bar (Design System §5 · AppHeader):
 * logo · step progress · [mode pill] · Offline / On this machine · theme · call status.
 *
 * "Offline" is visible on the phone build: privacy is a principle, and the
 * call's audio never leaves the laptop. The judge builds run locally too, and say so.
 */
import Logo from '../ui/Logo'
import Icon from '../ui/Icon'
import CallStatus from '../ui/CallStatus'
import FlowSteps from './FlowSteps'
import { useTheme } from '../../hooks/useTheme'
import './AppHeader.css'

/**
 * @param {object}  props
 * @param {boolean} props.simulation  VERA_FAKE=1 or the in-browser demo call
 * @param {boolean} props.judgeBuild  the Docker judge builds (VERA_MODE=judge)
 * @param {boolean} props.replay      the current call is a replayed scenario
 */
export default function AppHeader({ step, simulation = false, judgeBuild = false, replay = false, callStatus = 'idle', elapsed }) {
  const { theme, toggle } = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'
  const pill = judgeBuild ? 'JUDGE MODE' : replay ? 'REPLAYED CALL' : simulation ? 'SIMULATION MODE' : null

  return (
    <header className="app-header">
      <Logo />

      <div className="app-header__steps">
        <FlowSteps current={step} />
      </div>

      <div className="app-header__meta">
        {pill && (
          <span className="app-header__sim t-code">
            <Icon name="terminal" size={13} />
            {pill}
          </span>
        )}
        {judgeBuild ? (
          <span className="app-header__offline t-body-sm" title="Call audio, transcripts and scores stay on this machine. Only the payment goes to PayPal.">
            <Icon name="lock" size={13} />
            On this machine
          </span>
        ) : (
          <span className="app-header__offline t-body-sm" title="The call's audio never leaves this laptop">
            <Icon name="lock" size={13} />
            Offline
          </span>
        )}
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
