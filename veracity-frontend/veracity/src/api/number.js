/*
 * POST /api/number/check: the lookup behind Step 2 (Check number).
 *
 * Request:  { "number": "+91 98765 43210", "region": "IN" }
 *           region is only used when the number has no +country code.
 *
 * Response:
 * {
 *   "valid": true,
 *   "number_type": "MOBILE",            // see TYPE_LABELS below
 *   "country": "India",                 // null if unknown
 *   "location": "India",                // finer when known, e.g. "London"
 *   "original_carrier": "Airtel",       // carrier first issued to; null if unknown
 *   "is_international": false,          // country differs from `region`
 *   "e164_format": "+919876543210",
 *   "national_digits": "9876543210",
 *   "timezones": ["Asia/Calcutta"]
 * }
 *
 * 422 with { "detail": "..." } when the text isn't a phone number at all.
 */
import { apiRequest } from './client'

export const DEFAULT_REGION = 'IN'

export function checkNumber(number, { region = DEFAULT_REGION, signal } = {}) {
  return apiRequest('/api/number/check', {
    method: 'POST',
    body: JSON.stringify({ number, region }),
    signal,
  })
}

/* phonenumbers' PhoneNumberType names → words for the UI */
const TYPE_LABELS = {
  MOBILE: 'Mobile',
  FIXED_LINE: 'Landline',
  FIXED_LINE_OR_MOBILE: 'Landline or mobile',
  TOLL_FREE: 'Toll-free',
  PREMIUM_RATE: 'Premium rate',
  SHARED_COST: 'Shared cost',
  VOIP: 'Internet (VoIP)',
  PERSONAL_NUMBER: 'Personal number',
  PAGER: 'Pager',
  UAN: 'Company number (UAN)',
  VOICEMAIL: 'Voicemail',
  UNKNOWN: 'Unknown',
}

/**
 * Turn the raw response into label/value rows for the result panel.
 * Kept pure (no React), like buildChecks in health.js.
 */
export function buildNumberRows(details) {
  const unknown = 'Not known'
  return [
    { id: 'e164', label: 'Number', value: details.e164_format, mono: true },
    { id: 'type', label: 'Line type', value: TYPE_LABELS[details.number_type] ?? details.number_type },
    { id: 'country', label: 'Country', value: details.country ?? unknown },
    // Only worth a row when it says more than the country does
    details.location &&
      details.location !== details.country && { id: 'location', label: 'Area', value: details.location },
    { id: 'carrier', label: 'Original carrier', value: details.original_carrier ?? unknown },
    { id: 'intl', label: 'International', value: details.is_international ? 'Yes' : 'No' },
    { id: 'tz', label: 'Time zone', value: details.timezones.join(', ') || unknown, mono: true },
  ].filter(Boolean)
}
