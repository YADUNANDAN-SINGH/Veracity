/*
 * Step 4 · Report (Design System §4).
 *
 * What to do first (1930, cybercrime.gov.in, Chakshu), then the score and how
 * it was built, the evidence (red flags, voice), the optional community report,
 * and the JSON itself. The report is the one POST /api/session/{id}/stop
 * returned in Step 3 (or the demo call's, while the backend has no sessions).
 */
import Panel from '../../components/ui/Panel'
import Button from '../../components/ui/Button'
import Badge from '../../components/ui/Badge'
import AlertBanner from '../../components/ui/AlertBanner'
import RedFlagList from '../../components/live/RedFlagList'
import RiskSummary from '../../components/report/RiskSummary'
import CommunityReport from '../../components/report/CommunityReport'
import ReportJson from '../../components/report/ReportJson'
import { REPORT_LINKS, downloadReport } from '../../api/report'
import { describeCategory } from '../../constants/scamCategories'
import './ReportPage.css'

const RISK_TITLE = { HIGH: 'High-risk call', MEDIUM: 'Medium-risk call', LOW: 'Low-risk call' }
const VOICE_STATES = {
  LIKELY_HUMAN: { tone: 'low', label: 'Likely human' },
  UNCERTAIN: { tone: 'medium', label: 'Uncertain' },
  LIKELY_AI: { tone: 'high', label: 'Likely AI' },
}

/**
 * @param {object}   props
 * @param {object}   props.report   the §1.7 JSON report, or null
 * @param {Function} props.onBack   back to Step 3
 * @param {Function} props.onNewCall  Step 2, for the next call
 */
export default function ReportPage({ report, onBack, onNewCall }) {
  if (!report) {
    return (
      <main className="report-page">
        <Panel title="No report yet">
          <p className="muted report-page__empty">End a monitored call in Step 3 to build its report.</p>
          <Button onClick={onBack}>Back to the call</Button>
        </Panel>
      </main>
    )
  }

  const demo = report.call?.capture_method === 'demo_replay'
  const flags = (report.script?.red_flags ?? []).map((flag) => ({
    ...flag,
    severity: flag.severity ?? describeCategory(flag.category).severity,
  }))

  return (
    <main className="report-page">
      <header className="report-page__intro">
        <div className="report-page__who">
          <p className="t-overline muted">
            STEP 4 OF 4 · EVIDENCE REPORT <span className="t-code">{report.report_id.slice(0, 8)}</span> ·{' '}
            {formatDate(report.generated_at)}
          </p>
          <h1 className="t-title">
            {RISK_TITLE[report.overall.risk_level] ?? 'Call'} from{' '}
            <span className="report-page__number">{report.call.caller_number || 'an unknown number'}</span>
          </h1>
        </div>
        <Button variant="primary" icon="download" onClick={() => downloadReport(report)}>
          Download JSON
        </Button>
      </header>

      {demo && (
        <AlertBanner tone="info" title="Demo report">
          Built from the scripted call in Step 3, not a real one. The backend will write this same JSON for real calls.
        </AlertBanner>
      )}

      <Panel title="What to do now">
        <div className="report-page__todo">
          <p className="t-body-sm">
            <strong>Lost money?</strong> Call 1930 now and file at cybercrime.gov.in. Attach the JSON file.
          </p>
          <p className="t-body-sm">
            <strong>No money lost?</strong> Report the number on Chakshu within 30 days of the call.
          </p>
          <div className="report-page__links">
            <Button href={REPORT_LINKS.helpline} icon="phone">
              Call 1930
            </Button>
            <Button href={REPORT_LINKS.cybercrime} iconRight="external-link">
              cybercrime.gov.in
            </Button>
            <Button href={REPORT_LINKS.chakshu} iconRight="external-link">
              Chakshu
            </Button>
          </div>
        </div>
      </Panel>

      <div className="report-page__grid">
        <div className="report-page__col">
          <Panel title="Overall">
            <RiskSummary report={report} />
          </Panel>
          {report.number && (
            <Panel title="Number">
              <NumberFacts number={report.number} />
            </Panel>
          )}
          <Panel title="Voice">
            <VoiceFacts report={report} />
          </Panel>
        </div>
        <div className="report-page__col">
          <Panel title="Red flags" action={<span className="t-body-sm muted">exact words, as said</span>} flush>
            <RedFlagList flags={flags} live={false} />
          </Panel>
          <Panel title="Add to community reports">
            <CommunityReport report={report} />
          </Panel>
        </div>
      </div>

      <Panel
        title="report.json"
        action={
          <Button variant="ghost" size="sm" icon="download" onClick={() => downloadReport(report)}>
            Download
          </Button>
        }
        flush
      >
        <ReportJson report={report} />
      </Panel>

      <footer className="report-page__footer">
        <p className="t-body-sm muted">This report is evidence, not proof. Scores are model estimates.</p>
        <Button variant="ghost" onClick={onNewCall}>
          Check another call
        </Button>
      </footer>
    </main>
  )
}

const SERIES = {
  invalid: 'Not a valid number',
  international: 'International',
  '1600_regulated': '1600 (banks and agencies)',
  '140_telemarketing': '140 (telemarketing)',
  mobile: 'Mobile',
  fixed_line: 'Landline',
  toll_free: 'Toll-free',
  other: 'Other',
}

/** The number at the time of the call: what it is, how often it was reported, and its rule score. */
function NumberFacts({ number }) {
  const rows = [
    { label: 'Number', value: number.e164, mono: true },
    { label: 'Series', value: SERIES[number.series] ?? number.series ?? number.type },
    { label: 'Original carrier', value: number.original_carrier ?? 'Not known' },
  ]
  if (number.community_reports !== undefined) {
    rows.push({ label: 'Community reports', value: number.community_reports, mono: true })
  }
  if (number.rule_score !== null && number.rule_score !== undefined) {
    rows.push({ label: 'Rule score', value: `${number.rule_score}/100`, mono: true })
  }

  return (
    <div className="report-page__voice">
      <dl className="report-page__facts">
        {rows.map((row) => (
          <div key={row.label}>
            <dt className="t-body-sm muted">{row.label}</dt>
            <dd className={row.mono ? 't-code' : 't-body-sm'}>{row.value}</dd>
          </div>
        ))}
      </dl>
      {number.reasons?.length > 0 && (
        <ul className="report-page__reasons t-body-sm">
          {number.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function VoiceFacts({ report }) {
  const voice = report.voice ?? {}
  const state = VOICE_STATES[voice.final_state]
  const rows = [
    { label: 'Final state', value: state ? <Badge tone={state.tone}>{state.label}</Badge> : 'Not scored' },
    { label: 'Peak', value: `${Math.round((voice.max_p_ai ?? 0) * 100)}%`, mono: true },
    { label: 'Windows scored', value: voice.windows?.length ?? 0, mono: true },
    { label: 'Model', value: voice.model_id ?? '–', mono: true },
    { label: 'Audio saved', value: report.evidence?.audio_saved ? 'Yes' : 'No' },
  ]
  if (report.evidence?.audio_sha256) rows.push({ label: 'SHA-256', value: report.evidence.audio_sha256, mono: true })

  return (
    <div className="report-page__voice">
      <dl className="report-page__facts">
        {rows.map((row) => (
          <div key={row.label}>
            <dt className="t-body-sm muted">{row.label}</dt>
            <dd className={row.mono ? 't-code' : 't-body-sm'}>{row.value}</dd>
          </div>
        ))}
      </dl>
      <p className="t-body-sm muted">The AI-voice % is a calibrated model estimate, not proof.</p>
    </div>
  )
}

/** "31 OCT 2026, 12:10 AM" for the overline. */
function formatDate(iso) {
  return new Date(iso)
    .toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' })
    .toUpperCase()
}
