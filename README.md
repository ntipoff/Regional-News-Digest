# Weekly Regional News Digest 📰

A Streamlit application that automatically emails a curated regional news digest every Tuesday.

**Recipients:** nictipoff@gmail.com · mdk32366@gmail.com

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the app

```bash
streamlit run app.py
```

The app opens at http://localhost:8501

If your browser does not open automatically, open it manually or use this macOS one-liner:

```bash
open http://localhost:8501
```

For a combined startup + open command (macOS/Linux):

```bash
streamlit run app.py --server.port 8501 &
sleep 2
open http://localhost:8501
```

---

## Setup Checklist

### Step 1 — Get a News API Key
- Sign up free at https://newsapi.org
- Copy your API key (free tier: ~100 requests/day)

### Step 2 — Configure Gmail SMTP
- Enable 2-Factor Authentication on your Gmail account
- Generate an **App Password**: Google Account → Security → App Passwords
- Use your Gmail address as SMTP username and the App Password (not your main password)

### Step 3 — Configure the App
1. Open the **Settings** tab
2. Select your **Region**
3. Set your **Send Time** (UTC)
4. Enter your **News API key**
5. Enter **SMTP credentials**
6. Click **Save All Settings**

### Step 4 — Test It
1. Go to the **Preview & Test Send** tab
2. Click **Fetch & Preview News** to see what articles will be included
3. Click **Send Test Email Now** to send a test to both recipients

---

## How the Auto-Send Works

The app checks on every page load whether:
- It is currently **Tuesday**
- The current UTC time is within **15 minutes** of your configured send time
- A send has **not already occurred today**
- The app is **not paused**

> ⚠️ **Important:** For fully automated delivery without needing the browser open, run the app on a server and use the included scheduler script (see below).

---

## Automated Scheduling (Server Deployment)

For unattended Tuesday sends, use the companion scheduler:

```bash
# Run the scheduler (checks every 5 minutes)
python scheduler.py
```

Or add to cron:
```
# Run every 5 minutes to check if it's time to send
*/5 * * * * cd /path/to/app && python scheduler.py >> logs/cron.log 2>&1
```

---

## Project Structure

```
news_digest_app/
├── app.py                  # Main Streamlit application
├── scheduler.py            # Standalone scheduler for server use
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── data/
│   ├── config.json         # App configuration (auto-created, do not commit!)
│   └── send_history.json   # Delivery history (auto-created)
└── logs/
    └── digest_YYYYMM.log   # Monthly log files (auto-created)
```

---

## Requirements Coverage

| Requirement | Status |
|-------------|--------|
| FR-01 Automated Tuesday Delivery | ✅ Auto-send on page load + scheduler |
| FR-02 Dual Recipient Delivery | ✅ Hardcoded recipients |
| FR-03 Email Structure & Formatting | ✅ HTML + plain-text MIME |
| FR-04 Sender Identity & Branding | ✅ Configurable sender name |
| FR-05 Region Configuration Interface | ✅ Dropdown with 70+ regions |
| FR-06 Region Coverage Validation | ✅ Check Coverage button |
| FR-07 Multiple Region Profiles | 🔜 Future version |
| FR-08 Regional Headlines Fetching | ✅ NewsAPI integration |
| FR-09 Regional Sports Fetching | ✅ Sports category query |
| FR-10 Content Filtering & Quality | ✅ Dedup + validation |
| FR-11 Tuesday-Only Scheduled Job | ✅ Weekday + time check |
| FR-12 Manual Test Send | ✅ Preview & Test Send tab |
| FR-13 Configuration Storage | ✅ data/config.json |
| FR-14 Delivery History & Logging | ✅ History tab + CSV export |
| FR-15 Pause / Resume Delivery | ✅ Dashboard toggle |

---

## Security Notes

- `data/config.json` contains your API keys and SMTP password — **never commit this file to source control**
- Add `data/` to your `.gitignore`
- Use Gmail App Passwords, not your main account password
- The config file stores credentials in plain JSON — for production, consider using environment variables

---

## Troubleshooting

**"No articles available"**
- Check your News API key is valid
- Some regions have limited English-language coverage
- Free NewsAPI tier may have hit rate limits

**"SMTP Authentication Failed"**
- Ensure you're using an App Password, not your Gmail password
- Confirm 2FA is enabled on the Gmail account
- For non-Gmail SMTP, update host/port in Settings

**Emails not sending automatically**
- The Streamlit app must be open in a browser (or use scheduler.py on a server)
- Confirm the app is not paused (Dashboard tab)
- Check logs/ for error details
