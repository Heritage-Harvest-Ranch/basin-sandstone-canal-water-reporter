# basin-sandstone-canal-water-reporter

Daily reporter for Sandstone canal water orders from the Greybull Valley Irrigation District report page.

## What it does

- Fetches the water orders page: https://greybullvalleyid.com/water-orders/
- Parses and stores the current day's Sandstone canal orders in `data/YYYY-MM-DD.json`
- Looks at the previous two days of stored Sandstone orders to identify neighbors who may still be receiving water from a previous order
- Builds and emails a daily digest to `info@heritageharvestranch.com`

## Automation

GitHub Actions workflow:

- `.github/workflows/daily-sandstone-water-report.yml`
- Scheduled at both `15:00` and `16:00` UTC
- Script enforces running only when local `America/Denver` hour is 9, so one run is skipped and the 9am MT run proceeds across DST changes
- Commits updated `data/*.json` snapshots back to the repository when daily data changes

Required repository secrets for email:

- `SMTP_HOST`
- `SMTP_PORT` (optional, defaults to `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `EMAIL_FROM` (optional)
- `EMAIL_TO` (optional, defaults to `info@heritageharvestranch.com` if not set)