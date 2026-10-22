import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = p => fs.readFileSync(new URL(`../${p}`, import.meta.url), 'utf8')

test('manual payment submission is authenticated and never grants a tier', () => {
  const src = read('app/api/payments/manual/route.ts')
  const auth = read('lib/server-auth.ts')
  assert.match(src, /authenticatedUser\(req\)/)
  assert.match(auth, /auth\.getUser\(token\)/)
  assert.match(src, /crypto_payment_requests/)
  assert.doesNotMatch(src, /profiles[\s\S]{0,120}update/)
  assert.match(src, /status:\s*"pending"/)
})

test('admin approval is authenticated, idempotent, atomic, and time-bounded', () => {
  const src = read('app/api/admin/payments/route.ts')
  const sql = read('supabase_crypto_payments.sql')
  assert.match(src, /requireAdmin/)
  assert.match(src, /rpc\("approve_crypto_payment"/)
  assert.match(sql, /for update/i)
  assert.match(sql, /status\s*<>\s*'pending'/i)
  assert.match(sql, /tier_expires_at/i)
  assert.match(sql, /status='approved'/i)
})

test('database migration prevents reference reuse and client-side approval', () => {
  const sql = read('supabase_crypto_payments.sql')
  assert.match(sql, /unique\s*\(method,\s*network,\s*reference\)/i)
  assert.match(sql, /enable row level security/i)
  assert.match(sql, /revoke\s+insert[^;]+crypto_payment_requests/i)
  assert.match(sql, /tier_expires_at/i)
})

test('payment page offers manual Binance Pay and configured low-fee transfer networks', () => {
  const src = read('app/pay/page.tsx')
  assert.match(src, /Binance Pay/)
  assert.match(src, /Plasma/)
  assert.match(src, /reference/i)
  assert.match(src, /\/api\/payments\/manual/)
  assert.match(src, /لا يتم تفعيل الباقة قبل المراجعة/)
})

test('pricing routes paid users to the manual payment page', () => {
  const src = read('components/Pricing.tsx')
  assert.match(src, /\/pay\?tier=/)
  assert.doesNotMatch(src, /\/api\/stripe\/checkout/)
})
