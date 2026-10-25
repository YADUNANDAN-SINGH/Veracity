/*
 * The four steps of the dashboard journey, shown in the header
 * (Design System §5 · FlowSteps). Done steps get a check, the current
 * step is a brand pill, upcoming steps show their number.
 */
import Icon from '../ui/Icon'
import { STEPS } from '../../constants/steps'
import './FlowSteps.css'

export default function FlowSteps({ current }) {
  return (
    <nav aria-label="Progress">
      <ol className="flow-steps">
        {STEPS.map((step, index) => {
          const state = step.id < current ? 'done' : step.id === current ? 'current' : 'upcoming'

          return (
            <li key={step.id} className="flow-steps__item">
              {index > 0 && <span className="flow-steps__rule" aria-hidden="true" />}
              <span
                className={`flow-steps__step flow-steps__step--${state}`}
                aria-current={state === 'current' ? 'step' : undefined}
              >
                <span className="flow-steps__marker" aria-hidden="true">
                  {state === 'done' ? <Icon name="check" size={11} /> : step.id}
                </span>
                <span className="flow-steps__label">{step.label}</span>
                {state === 'done' && <span className="visually-hidden"> (done)</span>}
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
