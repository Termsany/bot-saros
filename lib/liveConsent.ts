/**
 * Must stay byte-for-byte identical to backend/app/user_live_activation.py's
 * CONSENT_TEXT — the backend is the source of truth and does the exact-match
 * check; this copy is only for display so the user can type it to confirm.
 */
export const CONSENT_TEXT =
  "I own this exchange account and these API keys. I am enabling LIVE trading " +
  "with my own capital, at my own risk, independent of the platform operator. " +
  "I understand this can lose money and I accept full responsibility."
