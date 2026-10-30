/*
 * The 11 scam-script categories (Project Document §1.6) in words for the UI.
 * title: the red-flag heading, said as what the caller is doing to you.
 * short: the tag shown after the evidence in the transcript.
 */
export const SCAM_CATEGORIES = {
  OTP_PIN_REQUEST: { title: 'Asks for an OTP, PIN or CVV', short: 'OTP' },
  AUTHORITY_IMPERSONATION: { title: 'Claims to be police, CBI or an official', short: 'Authority' },
  THREAT_ARREST: { title: 'Threatens arrest (“digital arrest”)', short: 'Threat' },
  PAYMENT_PRESSURE: { title: 'Pushes you to transfer money', short: 'Payment' },
  REMOTE_ACCESS: { title: 'Asks you to install an app or share your screen', short: 'Remote access' },
  SECRECY: { title: 'Tells you to keep it secret', short: 'Secrecy' },
  KYC_ACCOUNT_BLOCK: { title: 'Says your account or SIM will be blocked', short: 'KYC' },
  PARCEL_COURIER: { title: 'Talks about a parcel or courier in your name', short: 'Parcel' },
  FAMILY_EMERGENCY: { title: 'Claims a family member is in trouble', short: 'Family' },
  PRIZE_LOTTERY: { title: 'Says you have won a prize', short: 'Prize' },
  URGENCY: { title: 'Rushes you to act right now', short: 'Urgency' },
}

/** Fallback for a category the backend adds before the UI knows it. */
export function describeCategory(category) {
  return SCAM_CATEGORIES[category] ?? { title: category.toLowerCase().replaceAll('_', ' '), short: category }
}
