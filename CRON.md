# Self-Evolution Cron

Render free doesn't have cron internally. Use **cron-job.org** (free):

1. Go to https://cron-job.org/en/members/jobs/add/
2. Create job:
   - URL: `https://bot-saros-backend.onrender.com/api/evolve`
   - Method: POST
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
      - run: curl -X POST https://bot-saros-backend.onrender.com/api/evolve
```

Manual: POST https://bot-saros-backend.onrender.com/api/evolve from /admin
