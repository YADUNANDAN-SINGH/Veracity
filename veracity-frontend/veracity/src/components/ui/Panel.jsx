/*
 * The white card every screen is built from (Design System §5 · Panel).
 * One job per panel: number, input, voice, script, transcript, red flags, report.
 *
 * `action` renders on the right of the title bar (a button or a badge).
 * Set `flush` when children draw their own rows edge to edge (e.g. a list).
 */
import './Panel.css'

export default function Panel({ title, action, flush = false, className = '', children }) {
  const titleId = title ? `panel-${title.toLowerCase().replace(/\W+/g, '-')}` : undefined

  return (
    <section className={`panel ${className}`.trim()} aria-labelledby={titleId}>
      {title && (
        <header className="panel__header">
          <h2 id={titleId} className="t-subheading">
            {title}
          </h2>
          {action}
        </header>
      )}
      <div className={flush ? 'panel__body panel__body--flush' : 'panel__body'}>{children}</div>
    </section>
  )
}
