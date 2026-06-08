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

### Ad-hoc manual runs

A second workflow (`.github/workflows/adhoc-sandstone-water-report.yml`) can be triggered manually from the Actions tab. It accepts an optional date input (`YYYY-MM-DD`) and skips the 9am time gate.

## Self-hosted runner setup (Raspberry Pi)

The irrigation district's server blocks requests from cloud/datacenter IP ranges (GitHub-hosted runners included). A self-hosted runner on a home network resolves this since the fetch goes out over a residential IP.

### 1. Clone the repo

```bash
git clone https://github.com/heritage-harvest-ranch/basin-sandstone-canal-water-reporter.git
cd basin-sandstone-canal-water-reporter
pip3 install -r requirements.txt
```

### 2. Register a self-hosted runner

In the GitHub repo go to **Settings → Actions → Runners → New self-hosted runner**, select Linux/ARM64 (for Pi 4/5), and follow the generated instructions to download and configure the runner agent on the Pi.

### 3. Point the workflow at the self-hosted runner

In `.github/workflows/daily-sandstone-water-report.yml` and `.github/workflows/adhoc-sandstone-water-report.yml`, change:

```yaml
runs-on: ubuntu-latest
```

to:

```yaml
runs-on: self-hosted
```

### 4. Alternatively, use cron directly on the Pi

Skip the runner agent entirely and schedule the script with cron (`crontab -e`):

```cron
# 9am MT — runs at 15:00 UTC (MDT) and 16:00 UTC (MST) to cover DST
0 15 * * 1-6 cd /home/pi/basin-sandstone-canal-water-reporter && python3 water_reporter.py
0 16 * * 1-6 cd /home/pi/basin-sandstone-canal-water-reporter && python3 water_reporter.py --enforce-mountain-9am
```

The `--enforce-mountain-9am` flag on the 16:00 UTC line prevents a double-send during standard time when both jobs fire near 9am MT.

Set the SMTP environment variables in `/etc/environment` or a `.env` file sourced by the cron job.

## Required repository secrets for email:

- `SMTP_HOST`
- `SMTP_PORT` (optional, defaults to `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `EMAIL_FROM` (optional)
- `EMAIL_TO` (optional, defaults to `info@heritageharvestranch.com` if not set)