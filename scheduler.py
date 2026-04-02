"""
scheduler.py — Standalone scheduler for server-side automated Tuesday sends.

Run this script from cron every 5 minutes:
    */5 * * * * cd /path/to/app && python scheduler.py >> logs/cron.log 2>&1

Or run continuously:
    python scheduler.py

This handles FR-01 (automated Tuesday delivery) and FR-11 (Tuesday-only job)
independently of the Streamlit browser session.
"""

import json
import time
import logging
import smtplib
import ssl
import requests
from datetime import datetime, timedelta
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_FILE = DATA_DIR / "config.json"
HISTORY_FILE = DATA_DIR / "send_history.json"

HARDCODED_RECIPIENTS = ["nictipoff@gmail.com", "mdk32366@gmail.com"]

# Logging
LOGS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s UTC] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOGS_DIR / f"scheduler_{datetime.utcnow().strftime('%Y%m')}.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scheduler")


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        cfg["recipients"] = HARDCODED_RECIPIENTS
        return cfg
    return None


def save_config(cfg):
    cfg["recipients"] = HARDCODED_RECIPIENTS
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def jaccard_similarity(a, b):
    a_t, b_t = set(a.lower().split()), set(b.lower().split())
    if not a_t or not b_t:
        return 0.0
    return len(a_t & b_t) / len(a_t | b_t)


def deduplicate(articles):
    unique = []
    for art in articles:
        title = art.get("title", "")
        if not any(jaccard_similarity(title, e.get("title", "")) > 0.7 for e in unique):
            unique.append(art)
    return unique


def fetch_news(api_key, region, category="general"):
    from_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = f"{region} sports" if category == "sports" else region
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": query, "from": from_date, "sortBy": "publishedAt",
                    "language": "en", "pageSize": 20, "apiKey": api_key},
            timeout=15,
        )
        data = resp.json()
        if data.get("status") != "ok":
            return []
        articles = [a for a in data.get("articles", [])
                    if a.get("title") and a.get("url") and a.get("title") != "[Removed]"]
        articles = deduplicate(articles)
        return [{
            "title": a.get("title", ""),
            "description": a.get("description") or a.get("content") or "",
            "url": a.get("url", ""),
            "source": a.get("source", {}).get("name", "Unknown"),
            "published_at": a.get("publishedAt", ""),
        } for a in articles[:7]]
    except Exception as e:
        log.error(f"Fetch error ({category}): {e}")
        return []


def build_html(region, headlines, sports):
    today = datetime.utcnow().strftime("%A, %B %d, %Y")

    def render(articles, color):
        if not articles:
            return "<p><em>No articles available this week.</em></p>"
        out = ""
        for a in articles:
            desc = (a.get("description") or "")[:300]
            out += f"""<div style="border-left:3px solid {color};padding:10px 14px;margin-bottom:14px;background:#f9fafb;">
              <h3 style="margin:0 0 5px;font-size:14px;"><a href="{a['url']}" style="color:#111;">{a['title']}</a></h3>
              {"<p style='margin:0 0 6px;font-size:12px;color:#444;'>" + desc + "</p>" if desc else ""}
              <span style="font-size:11px;color:#888;">{a.get('source','')} · {a.get('published_at','')[:10]}</span>
              <br><a href="{a['url']}" style="font-size:12px;color:{color};">Read more →</a>
            </div>"""
        return out

    return f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
<div style="background:#1e3a5f;color:#fff;padding:20px;border-radius:6px 6px 0 0;">
  <h1 style="margin:0;font-size:20px;">{region} News Digest</h1>
  <p style="margin:4px 0 0;font-size:12px;opacity:.8;">{today}</p>
</div>
<div style="padding:20px;border:1px solid #e5e7eb;">
  <h2 style="color:#1d4ed8;border-bottom:2px solid #1d4ed8;padding-bottom:6px;">🗞 Regional Headlines</h2>
  {render(headlines, '#1d4ed8')}
  <h2 style="color:#15803d;border-bottom:2px solid #15803d;padding-bottom:6px;">🏆 Sports News</h2>
  {render(sports, '#15803d')}
</div>
<div style="font-size:11px;color:#999;text-align:center;padding:12px;">
  Regional News Digest · Frisco, TX · <a href="mailto:{HARDCODED_RECIPIENTS[0]}" style="color:#999;">Manage preferences</a>
</div>
</body></html>"""


def build_plain(region, headlines, sports):
    today = datetime.utcnow().strftime("%A, %B %d, %Y")
    lines = [f"YOUR {region.upper()} NEWS DIGEST — {today}", "=" * 60,
             "\nREGIONAL HEADLINES\n" + "-" * 40]
    for a in headlines:
        lines += [f"\n{a['title']}", a.get("description", "")[:200],
                  f"Source: {a.get('source','')}  |  {a.get('published_at','')[:10]}",
                  f"URL: {a['url']}"]
    lines += ["\n\nSPORTS NEWS\n" + "-" * 40]
    for a in sports:
        lines += [f"\n{a['title']}", a.get("description", "")[:200],
                  f"Source: {a.get('source','')}  |  {a.get('published_at','')[:10]}",
                  f"URL: {a['url']}"]
    lines += ["\n\nRegional News Digest · Frisco, TX"]
    return "\n".join(lines)


def send_digest(cfg, headlines, sports):
    region = cfg["region"]
    today = datetime.utcnow().strftime("%A, %B %d, %Y")
    subject = f"Your {region} News Digest — Tuesday, {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{cfg.get('sender_name','Regional News Digest')} <{cfg['smtp_user']}>"
    msg["To"] = ", ".join(cfg["recipients"])
    msg.attach(MIMEText(build_plain(region, headlines, sports), "plain"))
    msg.attach(MIMEText(build_html(region, headlines, sports), "html"))

    results = {"success": [], "failed": []}
    context = ssl.create_default_context()
    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        for recipient in cfg["recipients"]:
            try:
                server.sendmail(cfg["smtp_user"], recipient, msg.as_string())
                results["success"].append(recipient)
                log.info(f"Delivered to {recipient}")
            except Exception as e:
                results["failed"].append(recipient)
                log.error(f"Failed to deliver to {recipient}: {e}")
    return results


def should_run(cfg):
    now = datetime.utcnow()
    if now.weekday() != 1:
        return False
    if cfg.get("paused"):
        return False
    last_sent = cfg.get("last_sent_date", "")
    if last_sent == now.strftime("%Y-%m-%d"):
        return False
    try:
        h, m = map(int, cfg.get("send_time", "07:00").split(":"))
        scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
        diff = (now - scheduled).total_seconds()
        return -60 <= diff <= 3600  # within 1 hour after scheduled time (catch-up, FR-11)
    except Exception:
        return False


def run():
    cfg = load_config()
    if not cfg:
        log.warning("No config found. Configure the app in Streamlit first.")
        return

    if not should_run(cfg):
        log.debug("Not time to send.")
        return

    log.info(f"Starting digest run for region: {cfg['region']}")
    start = datetime.utcnow()

    # Fetch with retry (FR-01 AC3)
    headlines, sports = [], []
    for attempt in range(3):
        headlines = fetch_news(cfg["news_api_key"], cfg["region"], "general")
        sports = fetch_news(cfg["news_api_key"], cfg["region"], "sports")
        if headlines or sports:
            break
        log.warning(f"Fetch attempt {attempt+1} returned no results, retrying...")
        time.sleep(10)

    log.info(f"Fetched {len(headlines)} headlines, {len(sports)} sports articles.")

    try:
        result = send_digest(cfg, headlines, sports)
        ok = len(result["success"]) > 0
    except Exception as e:
        log.error(f"Send failed: {e}")
        result = {"success": [], "failed": cfg["recipients"]}
        ok = False

    duration = (datetime.utcnow() - start).total_seconds()

    entry = {
        "date": start.strftime("%Y-%m-%d %H:%M UTC"),
        "region": cfg["region"],
        "is_test": False,
        "headline_count": len(headlines),
        "sports_count": len(sports),
        "status": "success" if ok else "failed",
        "delivered_to": result["success"],
        "failed_to": result["failed"],
        "error": None if ok else "Send failed",
        "duration_seconds": round(duration, 1),
    }
    history = load_history()
    history.insert(0, entry)
    save_history(history[:84])

    if ok:
        cfg["last_sent_date"] = start.strftime("%Y-%m-%d")
        save_config(cfg)
        log.info(f"Digest sent successfully in {duration:.1f}s")
    else:
        log.error("Digest send failed.")


if __name__ == "__main__":
    # Single-run mode (for cron)
    run()
