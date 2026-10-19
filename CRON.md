# Self-Evolution Cron

Render free doesn't have cron internally. Use **cron-job.org** (free):

1. Go to https://cron-job.org/en/members/jobs/add/
2. Create job:
   - URL: `https://bot-saros-backend.onrender.com/api/evolve`
   - Method: POST
   - Header: `X-Cron-Secret: <CRON_SECRET>` (same value as the backend env var — without it the endpoint returns 401)
   - Schedule: Every Friday 00:00 UTC (or daily 00:00)
   - Timeout: 180s
3. Save — it will hit /api/evolve automatically

Alternatively, use **GitHub Actions** cron:

```yaml
# .github/workflows/evolve.yml
on:
  schedule:
    - cron: '0 0 * * 5'  # Friday
jobs:
  evolve:
    runs-on: ubuntu-latest
    steps:
      - run: curl -fsS -X POST -H "X-Cron-Secret: ${{ secrets.CRON_SECRET }}" https://bot-saros-backend.onrender.com/api/evolve
```

Manual: from /admin while signed in with an email listed in ADMIN_EMAILS


## LLM Auto-Invention (كل أسبوع)

إضافة Cron ثانية:

- URL: `https://bot-saros-backend.onrender.com/api/llm/evolve?prompt=innovative+futures+strategy&n=3`
- Method: POST
- Header: `X-Cron-Secret: <CRON_SECRET>`
- Schedule: Every Saturday 02:00 UTC

الـ LLM هيولد 3 استراتيجيات جديدة، يباك تست كل واحدة، ولو WR ≥60% و PF ≥1.2 يضيفها تلقائياً للـ Elite ويبعتلك تليجرام.
