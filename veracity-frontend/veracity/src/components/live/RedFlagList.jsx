/*
 * The flag events (Design System §5 · RedFlag), most severe first, then earliest.
 * Each one shows what the caller did, their exact words, when, the category,
 * its severity and whether a rule or the local LLM found it.
 */
import Icon from '../ui/Icon'
import { describeCategory } from '../../constants/scamCategories'
import { formatClock } from '../../utils/formatTime'
import './RedFlagList.css'

const SEVERITY = {
  3: { tone: 'high', icon: 'octagon' },
  2: { tone: 'medium', icon: 'alert-triangle' },
  1: { tone: 'low', icon: 'info' },
}

const SOURCE_LABEL = { rule: 'rule', llm: 'local LLM' }

export default function RedFlagList({ flags, live }) {
  if (flags.length === 0) {
    return (
      <p className="red-flags__empty t-body-sm muted">
        {live ? 'None yet. Scam phrases the caller says will appear here with their exact words.' : 'No red flags were found.'}
      </p>
    )
  }

  const sorted = [...flags].sort((a, b) => b.severity - a.severity || a.t - b.t)
  return (
    <ul className="red-flags">
      {sorted.map((flag) => {
        const severity = SEVERITY[flag.severity] ?? SEVERITY[1]
        return (
          <li key={`${flag.category}-${flag.t}-${flag.source}`} className={`red-flag red-flag--${severity.tone}`}>
            <Icon name={severity.icon} size={16} className="red-flag__icon" />
            <div className="red-flag__body">
              <p className="t-label">{describeCategory(flag.category).title}</p>
              <p className="t-body-sm">“{flag.evidence}”</p>
              <p className="red-flag__meta t-code muted">
                <span>{formatClock(flag.t)}</span>
                <span>{flag.category}</span>
                <span className="red-flag__severity" aria-label={`severity ${flag.severity} of 3`}>
                  {[1, 2, 3].map((n) => (
                    <i key={n} className={n <= flag.severity ? 'is-on' : undefined} aria-hidden="true" />
                  ))}
                  <span aria-hidden="true">sev {flag.severity}</span>
                </span>
                <span>{SOURCE_LABEL[flag.source] ?? flag.source}</span>
              </p>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
