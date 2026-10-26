# Authentication and focused security audit

Date: 2026-10-26

## Scope

- Authentication page UI and client-side Supabase usage.
- Frontend client artifacts and configuration exposure.
- Backend authentication and protected/admin endpoint regression checks.

## Verified

- The authentication page does not render the Supabase project URL or provider diagnostics.
- Login, registration, and password-reset failures use safe Arabic messages and do not expose provider error text.
- Password-reset redirect is constrained to the current site origin and `/auth`.
- Backend rejects anonymous access to a protected endpoint with HTTP 401.
- Backend rejects an authenticated non-admin from an admin endpoint with HTTP 403.
- Client source/config and generated client artifacts contain no service-role, service-key, Stripe secret-key, or webhook-secret markers.
- `ALLOW_LIVE_TRADING=false` remains the audited test configuration; no live-trading setting was changed.

## NOT VERIFIED

- Live Supabase dashboard settings, including RLS policies, email-confirmation policy, password-reset redirect allow-list, provider configuration, session lifetime, and leaked-secret status, were not accessible from this workspace.
- Production deployment bundle and CDN cache were not inspected; local `.next/static` artifacts were inspected by regression test.

## Findings

- Fixed visible project URL/provider status leakage on `/auth`.
- Fixed raw authentication error leakage by mapping failures to user-facing Arabic messages.
- Added password-reset UI flow without changing session/token handling or redirecting to user-controlled URLs.
- Existing backend auth code and focused rejection tests provide fail-closed checks for protected and admin routes; no backend production files were modified.
