/*
 * The report exactly as it will be filed: the JSON people attach on
 * 1930 / cybercrime.gov.in / Chakshu. Shown in full so nothing is hidden.
 */
import './ReportJson.css'

export default function ReportJson({ report }) {
  return (
    <pre className="report-json t-code" tabIndex={0} aria-label="report.json">
      {JSON.stringify(report, null, 2)}
    </pre>
  )
}
