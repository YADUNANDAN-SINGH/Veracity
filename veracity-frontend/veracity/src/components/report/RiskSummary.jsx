/*
 * The report's overall verdict (Design System §5 · RiskSummary): the risk
 * level and score the backend decided, its top reasons, and how the score
 * was built (Project Document §1.8 fusion), so nobody has to trust a bare number.
 */
import Badge from '../ui/Badge'
import Icon from '../ui/Icon'
import './RiskSummary.css'

const LEVELS = {
  HIGH: { tone: 'high', label: 'High risk' },
  MEDIUM: { tone: 'medium', label: 'Medium risk' },
  LOW: { tone: 'low', label: 'Low risk' },
}

export default function RiskSummary({ report }) {
  const { overall } = report
  const level = LEVELS[overall.risk_level] ?? LEVELS.LOW
  const parts = buildParts(report)
  const weighted = Math.round(parts.reduce((sum, p) => sum + p.points, 0))

  return (
    <div className="risk-summary">
      <div className="risk-summary__head">
        <Badge tone={level.tone}>{level.label.toUpperCase()}</Badge>
        <p className="risk-summary__score">
          {overall.score}
          <span className="t-code muted">/100</span>
        </p>
      </div>

      {overall.top_reasons.length > 0 && (
        <ul className="risk-summary__reasons">
          {overall.top_reasons.map((reason) => (
            <li key={reason} className={`t-body-sm risk-summary__reason--${level.tone}`}>
              <Icon name={level.tone === 'low' ? 'info' : 'alert-triangle'} size={14} />
              {reason}
            </li>
          ))}
        </ul>
      )}

      <div className="risk-summary__built">
        <p className="t-overline muted">HOW THE SCORE IS BUILT</p>
        <table className="risk-summary__table t-body-sm">
          <tbody>
            {parts.map((part) => (
              <tr key={part.label}>
                <th scope="row">{part.label}</th>
                <td className="t-code">{part.value ?? '–'}</td>
                <td className="t-code muted">× {part.weight.toFixed(2)}</td>
                <td className="t-code">{Math.round(part.points)}</td>
              </tr>
            ))}
            <tr className="risk-summary__total">
              <th scope="row">Weighted</th>
              <td />
              <td />
              <td className="t-code">{weighted}</td>
            </tr>
          </tbody>
        </table>
        {overrideNote(parts, overall.score, weighted) && (
          <p className="t-body-sm muted">{overrideNote(parts, overall.score, weighted)}</p>
        )}
        {parts[0].value === null && (
          <p className="t-body-sm muted">The number has no rule score yet, so it adds nothing.</p>
        )}
        <p className="t-code muted risk-summary__scale">HIGH ≥ 70 · MEDIUM ≥ 40 · LOW below 40</p>
      </div>
    </div>
  )
}

/** Number × 0.25 + voice peak × 0.40 + script × 0.35. */
function buildParts(report) {
  const number = report.number?.rule_score ?? null
  const voice = Math.round((report.voice?.max_p_ai ?? 0) * 100)
  const script = report.script?.script_score ?? 0
  return [
    { label: 'Number', value: number, weight: 0.25, points: (number ?? 0) * 0.25 },
    { label: 'Voice peak', value: voice, weight: 0.4, points: voice * 0.4 },
    { label: 'Script', value: script, weight: 0.35, points: script * 0.35 },
  ]
}

/** Voice ≥ 85 or script ≥ 80 is enough on its own: say why the score is above the weighted sum. */
function overrideNote(parts, score, weighted) {
  if (score <= weighted) return null
  const [, voice, script] = parts
  if (script.value >= 80 && script.value === score) return 'Script score ≥ 80 is enough on its own, so the score is raised to it.'
  if (voice.value >= 85 && voice.value === score) return 'Voice peak ≥ 85 is enough on its own, so the score is raised to it.'
  return 'One signal was strong enough on its own, so the score is raised to it.'
}
