# Manual Binance Pay / USDT deployment

Do these in order. Do not deploy the routes before the database migration.

1. Back up Supabase, then run `supabase_crypto_payments.sql` in the SQL editor.
2. Add server-only environment variables to Vercel:
   - `ADMIN_EMAILS`
   - `BINANCE_PAY_ID` and optionally `BINANCE_PAY_NICKNAME`
   - One address per network you actually verified: `CRYPTO_PLASMA_ADDRESS`, `CRYPTO_BSC_ADDRESS`, `CRYPTO_TRON_ADDRESS`, `CRYPTO_POLYGON_ADDRESS`, `CRYPTO_ARBITRUM_ADDRESS`
   - Optional prices: `CRYPTO_STARTER_USDT`, `CRYPTO_PRO_USDT`, `CRYPTO_ELITE_USDT`
3. Never configure an address unless the destination supports **USDT on that exact network**. Each configured option becomes visible to customers.
4. Deploy the web app and backend together so both enforce `tier_expires_at`.
5. Test without transferring money: login, create a request, confirm it stays `pending`, reject it in `/admin`, then create another and approve it using a clearly marked test/reference record.
6. For a real request, verify Binance Pay Order ID inside the receiving Binance account, or verify the TxID, asset, network, destination, amount, and confirmations on the correct chain explorer before approving.

Binance Pay on a personal account has no trusted merchant webhook in this implementation. A customer-supplied reference is only a lookup aid and never activates a plan automatically.
