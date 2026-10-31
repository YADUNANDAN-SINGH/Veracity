/*
 * Step 4 · Report helpers.
 *
 *   GET  /api/report/{id}      the finished report (Step 3 already has it from /stop)
 *   POST /api/number/report    { number, category, note } → adds a community report
 *
 * If the backend is an older build without /api/number/report (404), community
 * reports are kept in this browser's localStorage so the flow can still be shown.
 */
import { apiRequest } from './client'

const LOCAL_KEY = 'veracity-community-reports'

/** Where to report, from the Design System §2 copy. */
export const REPORT_LINKS = {
  helpline: 'tel:1930',
  cybercrime: 'https://cybercrime.gov.in',
  chakshu: 'https://sancharsaathi.gov.in/sfc/',
}

/** Scam types for the community report (the LLM's scam_type values, in words). */
export const SCAM_TYPES = [
  { id: 'digital_arrest', label: 'Digital arrest' },
  { id: 'bank_kyc', label: 'Bank or KYC' },
  { id: 'family_emergency', label: 'Family emergency' },
  { id: 'parcel_courier', label: 'Parcel or courier' },
  { id: 'investment', label: 'Investment' },
  { id: 'lottery_prize', label: 'Lottery or prize' },
  { id: 'tech_support', label: 'Tech support' },
  { id: 'other', label: 'Other' },
]

/** Best guess at the scam type from the red flags, to preselect in the form. */
export function guessScamType(report) {
  const categories = new Set((report?.script?.red_flags ?? []).map((f) => f.category))
  if (report?.script?.scam_type) return report.script.scam_type
  if (categories.has('THREAT_ARREST') || (categories.has('AUTHORITY_IMPERSONATION') && categories.has('PAYMENT_PRESSURE'))) {
    return 'digital_arrest'
  }
  if (categories.has('FAMILY_EMERGENCY')) return 'family_emergency'
  if (categories.has('KYC_ACCOUNT_BLOCK') || categories.has('OTP_PIN_REQUEST')) return 'bank_kyc'
  if (categories.has('PARCEL_COURIER')) return 'parcel_courier'
  if (categories.has('PRIZE_LOTTERY')) return 'lottery_prize'
  if (categories.has('REMOTE_ACCESS')) return 'tech_support'
  return 'other'
}

/**
 * Add the number to the community report list.
 * @returns {Promise<{ stored: 'backend' | 'browser' }>}
 */
export async function submitCommunityReport({ number, category, note }) {
  try {
    await apiRequest('/api/number/report', { method: 'POST', body: JSON.stringify({ number, category, note }) })
    return { stored: 'backend' }
  } catch (error) {
    if (error.status !== 404) throw error
    const saved = readLocal()
    saved.push({ number, category, note, reported_at: new Date().toISOString() })
    localStorage.setItem(LOCAL_KEY, JSON.stringify(saved))
    return { stored: 'browser' }
  }
}

function readLocal() {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_KEY)) ?? []
  } catch {
    return []
  }
}

/** Save the report as a .json file the user can attach on 1930 / cybercrime.gov.in / Chakshu. */
export function downloadReport(report) {
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `veracity-report-${report.report_id.slice(0, 8)}.json`
  link.click()
  URL.revokeObjectURL(url)
}
