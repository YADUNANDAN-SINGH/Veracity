/*
 * The 11 scam-script categories (Project Document §1.6) in words for the UI.
 * title: the red-flag heading, said as what the caller is doing to you.
 * short: the tag shown after the evidence in the transcript.
 * severity: 1–3, used when a flag arrives without one (e.g. in a saved report).
 */
export const SCAM_CATEGORIES = {
  OTP_PIN_REQUEST: { title: 'Asks for an OTP, PIN or CVV', short: 'OTP', severity: 3 },
  AUTHORITY_IMPERSONATION: { title: 'Claims to be police, CBI or an official', short: 'Authority', severity: 3 },
  THREAT_ARREST: { title: 'Threatens arrest (“digital arrest”)', short: 'Threat', severity: 3 },
  PAYMENT_PRESSURE: { title: 'Pushes you to transfer money', short: 'Payment', severity: 3 },
  REMOTE_ACCESS: { title: 'Asks you to install an app or share your screen', short: 'Remote access', severity: 3 },
  SECRECY: { title: 'Tells you to keep it secret', short: 'Secrecy', severity: 2 },
  KYC_ACCOUNT_BLOCK: { title: 'Says your account or SIM will be blocked', short: 'KYC', severity: 2 },
  PARCEL_COURIER: { title: 'Talks about a parcel or courier in your name', short: 'Parcel', severity: 2 },
  FAMILY_EMERGENCY: { title: 'Claims a family member is in trouble', short: 'Family', severity: 2 },
  PRIZE_LOTTERY: { title: 'Says you have won a prize', short: 'Prize', severity: 2 },
  URGENCY: { title: 'Rushes you to act right now', short: 'Urgency', severity: 1 },
}

/** Fallback for a category the backend adds before the UI knows it. */
export function describeCategory(category) {
  return SCAM_CATEGORIES[category] ?? { title: category.toLowerCase().replaceAll('_', ' '), short: category, severity: 1 }
}
