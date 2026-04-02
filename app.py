"""
Weekly Regional News Digest — Streamlit Application
Version 1.0
"""

import streamlit as st
import json
import os
import csv
import io
import hashlib
import smtplib
import ssl
import requests
import time
import re
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Weekly Regional News Digest",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_FILE = DATA_DIR / "config.json"
HISTORY_FILE = DATA_DIR / "send_history.json"
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ── Hardcoded recipients (FR-02) ──────────────────────────────────────────────
HARDCODED_RECIPIENTS = ["nictipoff@gmail.com", "mdk32366@gmail.com"]

# ── Default config ─────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "region": "",
    "region_query": "",
    "send_time": "07:00",
    "paused": False,
    "sender_name": "Regional News Digest",
    "news_api_key": "",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "last_sent_date": "",
    "recipients": HARDCODED_RECIPIENTS,
}

# ── US Regions list ────────────────────────────────────────────────────────────
US_REGIONS = {
    "Alabama": "Alabama",
    "Alaska": "Alaska",
    "Arizona": "Arizona",
    "Arkansas": "Arkansas",
    "California": "California",
    "Colorado": "Colorado",
    "Connecticut": "Connecticut",
    "Delaware": "Delaware",
    "Florida": "Florida",
    "Georgia": "Georgia",
    "Hawaii": "Hawaii",
    "Idaho": "Idaho",
    "Illinois": "Illinois",
    "Indiana": "Indiana",
    "Iowa": "Iowa",
    "Kansas": "Kansas",
    "Kentucky": "Kentucky",
    "Louisiana": "Louisiana",
    "Maine": "Maine",
    "Maryland": "Maryland",
    "Massachusetts": "Massachusetts",
    "Michigan": "Michigan",
    "Minnesota": "Minnesota",
    "Mississippi": "Mississippi",
    "Missouri": "Missouri",
    "Montana": "Montana",
    "Nebraska": "Nebraska",
    "Nevada": "Nevada",
    "New Hampshire": "New Hampshire",
    "New Jersey": "New Jersey",
    "New Mexico": "New Mexico",
    "New York": "New York",
    "North Carolina": "North Carolina",
    "North Dakota": "North Dakota",
    "Ohio": "Ohio",
    "Oklahoma": "Oklahoma",
    "Oregon": "Oregon",
    "Pennsylvania": "Pennsylvania",
    "Rhode Island": "Rhode Island",
    "South Carolina": "South Carolina",
    "South Dakota": "South Dakota",
    "Tennessee": "Tennessee",
    "Texas": "Texas",
    "Utah": "Utah",
    "Vermont": "Vermont",
    "Virginia": "Virginia",
    "Washington": "Washington",
    "West Virginia": "West Virginia",
    "Wisconsin": "Wisconsin",
    "Wyoming": "Wyoming",
    # Metro areas
    "New York City, NY": "New York City",
    "Los Angeles, CA": "Los Angeles",
    "Chicago, IL": "Chicago",
    "Houston, TX": "Houston",
    "Phoenix, AZ": "Phoenix",
    "Philadelphia, PA": "Philadelphia",
    "San Antonio, TX": "San Antonio",
    "San Diego, CA": "San Diego",
    "Dallas, TX": "Dallas",
    "San Francisco, CA": "San Francisco",
    "Seattle, WA": "Seattle",
    "Denver, CO": "Denver",
    "Boston, MA": "Boston",
    "Nashville, TN": "Nashville",
    "Austin, TX": "Austin",
    "Miami, FL": "Miami",
    "Atlanta, GA": "Atlanta",
    "Minneapolis, MN": "Minneapolis",
    "Portland, OR": "Portland",
    "Las Vegas, NV": "Las Vegas",
    # Countries
    "United Kingdom": "United Kingdom",
    "Canada": "Canada",
    "Australia": "Australia",
    "India": "India",
}

# ═══════════════════════════════════════════════════════════════════════════════
# Config helpers
# ═══════════════════════════════════════════════════════════════════════════════

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            # Merge with defaults for any new keys
            merged = {**DEFAULT_CONFIG, **cfg}
            merged["recipients"] = HARDCODED_RECIPIENTS  # always enforce
            return merged
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    cfg["recipients"] = HARDCODED_RECIPIENTS  # always enforce (FR-02)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# History helpers
# ═══════════════════════════════════════════════════════════════════════════════

def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_history(history: list):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def append_history_entry(entry: dict):
    history = load_history()
    history.insert(0, entry)
    history = history[:84]  # keep ~12 weeks (84 Tuesdays ≫ 12 weeks)
    save_history(history)


# ═══════════════════════════════════════════════════════════════════════════════
# News fetching (FR-08, FR-09, FR-10)
# ═══════════════════════════════════════════════════════════════════════════════

def jaccard_similarity(a: str, b: str) -> float:
    a_tokens = set(a.lower().split())
    b_tokens = set(b.lower().split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def deduplicate_articles(articles: list) -> list:
    """Remove near-duplicate articles using Jaccard similarity (FR-10)."""
    unique = []
    for article in articles:
        title = article.get("title", "")
        is_dup = False
        for existing in unique:
            if jaccard_similarity(title, existing.get("title", "")) > 0.7:
                is_dup = True
                break
        if not is_dup:
            unique.append(article)
    return unique


def is_valid_article(article: dict) -> bool:
    """Validate article has required fields (FR-10)."""
    return bool(
        article.get("title")
        and article.get("url")
        and article.get("title") != "[Removed]"
    )


def fetch_news(api_key: str, region: str, category: str = "general") -> list:
    """
    Fetch news from NewsAPI.org for a given region and category.
    category: 'general' for headlines, 'sports' for sports news (FR-08, FR-09)
    """
    if not api_key:
        return []

    from_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build query
    if category == "sports":
        query = f"{region} sports"
    else:
        query = region

    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "from": from_date,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 20,
            "apiKey": api_key,
        }
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        if data.get("status") != "ok":
            return []

        articles = data.get("articles", [])
        # Filter valid articles
        articles = [a for a in articles if is_valid_article(a)]
        # Deduplicate
        articles = deduplicate_articles(articles)
        # Normalize fields
        normalized = []
        for a in articles:
            normalized.append({
                "title": a.get("title", ""),
                "description": a.get("description") or a.get("content") or "",
                "url": a.get("url", ""),
                "source": a.get("source", {}).get("name", "Unknown Source"),
                "published_at": a.get("publishedAt", ""),
                "paywall": False,
            })
        return normalized[:7]  # max 7 per section (FR-03)

    except Exception as e:
        log_event(f"News fetch error ({category}): {e}")
        return []


def validate_region_coverage(api_key: str, region: str) -> dict:
    """Check if region has sufficient news coverage (FR-06)."""
    headlines = fetch_news(api_key, region, "general")
    sports = fetch_news(api_key, region, "sports")
    return {
        "headline_count": len(headlines),
        "sports_count": len(sports),
        "sufficient": len(headlines) >= 3 and len(sports) >= 3,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Email composition (FR-03, FR-04)
# ═══════════════════════════════════════════════════════════════════════════════

def format_published_date(iso_str: str) -> str:
    try:
        dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%b %d, %Y %I:%M %p UTC")
    except Exception:
        return iso_str or "Unknown date"


def build_html_email(region: str, headlines: list, sports: list, is_test: bool = False) -> str:
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    test_banner = """
    <div style="background:#b45309;color:#fff;text-align:center;padding:8px 16px;
                font-family:Arial,sans-serif;font-size:13px;font-weight:bold;letter-spacing:.05em;">
        TEST EMAIL — Not a scheduled send
    </div>""" if is_test else ""

    def render_articles(articles: list, section_color: str) -> str:
        if not articles:
            return '<p style="color:#6b7280;font-style:italic;font-size:14px;">No articles available for this region this week.</p>'
        html = ""
        for a in articles:
            desc = a.get("description", "")
            if desc and len(desc) > 300:
                desc = desc[:300].rsplit(" ", 1)[0] + "…"
            pub = format_published_date(a.get("published_at", ""))
            paywall_note = ' <span style="background:#fef3c7;color:#92400e;padding:1px 6px;border-radius:3px;font-size:11px;">Subscription may be required</span>' if a.get("paywall") else ""
            html += f"""
            <div style="border-left:3px solid {section_color};padding:12px 16px;margin-bottom:16px;background:#f9fafb;border-radius:0 6px 6px 0;">
              <h3 style="margin:0 0 6px;font-size:15px;font-family:Arial,sans-serif;color:#111827;line-height:1.4;">
                <a href="{a['url']}" style="color:#111827;text-decoration:none;">{a['title']}</a>
              </h3>
              {"<p style='margin:0 0 8px;font-size:13px;color:#374151;line-height:1.6;'>" + desc + "</p>" if desc else ""}
              <div style="font-size:11px;color:#9ca3af;">
                <strong style="color:#6b7280;">{a.get('source','')}</strong> &bull; {pub}{paywall_note}
              </div>
              <a href="{a['url']}" style="display:inline-block;margin-top:8px;font-size:12px;color:{section_color};font-weight:600;text-decoration:none;">Read more →</a>
            </div>"""
        return html

    headline_html = render_articles(headlines, "#1d4ed8")
    sports_html = render_articles(sports, "#15803d")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Your {region} News Digest</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;">
{test_banner}
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid #e5e7eb;">

      <!-- Header -->
      <tr><td style="background:#1e3a5f;padding:28px 32px;">
        <p style="margin:0 0 4px;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#93c5fd;font-weight:600;">Weekly Digest</p>
        <h1 style="margin:0 0 8px;font-size:22px;color:#ffffff;line-height:1.3;">{region} News Digest</h1>
        <p style="margin:0;font-size:13px;color:#bfdbfe;">{today}</p>
      </td></tr>

      <!-- Body -->
      <tr><td style="padding:28px 32px;">

        <!-- Headlines -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
          <tr><td style="border-bottom:2px solid #1d4ed8;padding-bottom:8px;margin-bottom:16px;">
            <h2 style="margin:0;font-size:16px;color:#1d4ed8;letter-spacing:.04em;text-transform:uppercase;">🗞 Regional Headlines</h2>
          </td></tr>
          <tr><td style="padding-top:16px;">{headline_html}</td></tr>
        </table>

        <!-- Sports -->
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="border-bottom:2px solid #15803d;padding-bottom:8px;margin-bottom:16px;">
            <h2 style="margin:0;font-size:16px;color:#15803d;letter-spacing:.04em;text-transform:uppercase;">🏆 Sports News</h2>
          </td></tr>
          <tr><td style="padding-top:16px;">{sports_html}</td></tr>
        </table>

      </td></tr>

      <!-- Footer -->
      <tr><td style="background:#f9fafb;padding:20px 32px;border-top:1px solid #e5e7eb;">
        <p style="margin:0 0 6px;font-size:11px;color:#9ca3af;text-align:center;">
          You are receiving this email as a subscriber of the Weekly Regional News Digest.
        </p>
        <p style="margin:0;font-size:11px;color:#9ca3af;text-align:center;">
          Regional News Digest · Frisco, TX · 
          <a href="mailto:nictipoff@gmail.com" style="color:#9ca3af;">Manage preferences</a>
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


def build_plain_text_email(region: str, headlines: list, sports: list, is_test: bool = False) -> str:
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    lines = []
    if is_test:
        lines.append("*** TEST EMAIL — Not a scheduled send ***\n")
    lines.append(f"YOUR {region.upper()} NEWS DIGEST — {today}")
    lines.append("=" * 60)

    lines.append("\n🗞  REGIONAL HEADLINES\n" + "-" * 40)
    if not headlines:
        lines.append("No articles available this week.")
    for a in headlines:
        lines.append(f"\n{a['title']}")
        if a.get("description"):
            lines.append(a["description"][:200])
        lines.append(f"Source: {a.get('source','')} | {format_published_date(a.get('published_at',''))}")
        lines.append(f"Read more: {a['url']}")

    lines.append("\n\n🏆  SPORTS NEWS\n" + "-" * 40)
    if not sports:
        lines.append("No sports articles available this week.")
    for a in sports:
        lines.append(f"\n{a['title']}")
        if a.get("description"):
            lines.append(a["description"][:200])
        lines.append(f"Source: {a.get('source','')} | {format_published_date(a.get('published_at',''))}")
        lines.append(f"Read more: {a['url']}")

    lines.append("\n\n" + "=" * 60)
    lines.append("You are receiving this as a subscriber of Weekly Regional News Digest.")
    lines.append("Regional News Digest · Frisco, TX")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Email sending (FR-01, FR-02)
# ═══════════════════════════════════════════════════════════════════════════════

def send_email(cfg: dict, region: str, headlines: list, sports: list, is_test: bool = False) -> dict:
    """Send digest email to both recipients. Returns result dict."""
    today_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    prefix = "[TEST] " if is_test else ""
    subject = f"{prefix}Your {region} News Digest — Tuesday, {today_str}"

    html_body = build_html_email(region, headlines, sports, is_test)
    text_body = build_plain_text_email(region, headlines, sports, is_test)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{cfg['sender_name']} <{cfg['smtp_user']}>"
    msg["To"] = ", ".join(cfg["recipients"])

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    results = {"success": [], "failed": [], "error": None}

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(cfg["smtp_user"], cfg["smtp_password"])
            for recipient in cfg["recipients"]:
                try:
                    server.sendmail(cfg["smtp_user"], recipient, msg.as_string())
                    results["success"].append(recipient)
                except Exception as e:
                    results["failed"].append({"email": recipient, "error": str(e)})
    except Exception as e:
        results["error"] = str(e)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Logging (FR-14)
# ═══════════════════════════════════════════════════════════════════════════════

def log_event(message: str):
    log_file = LOGS_DIR / f"digest_{datetime.now(timezone.utc).strftime('%Y%m')}.log"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Scheduler check — is it time to send? (FR-01, FR-11)
# ═══════════════════════════════════════════════════════════════════════════════

def should_send_today(cfg: dict) -> bool:
    """Return True if it's Tuesday and we haven't sent today."""
    now = datetime.now(timezone.utc)
    if now.weekday() != 1:  # 1 = Tuesday
        return False
    if cfg.get("paused"):
        return False
    last_sent = cfg.get("last_sent_date", "")
    today_str = now.strftime("%Y-%m-%d")
    return last_sent != today_str


def is_send_time_now(cfg: dict) -> bool:
    """Check if current UTC time is within 15 minutes of configured send time."""
    try:
        h, m = map(int, cfg.get("send_time", "07:00").split(":"))
        now = datetime.now(timezone.utc)
        scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
        diff = abs((now - scheduled).total_seconds())
        return diff <= 900  # 15-minute window (FR-01 AC1)
    except Exception:
        return False


def run_digest(cfg: dict, is_test: bool = False) -> dict:
    """Fetch news and send digest. Returns a result summary."""
    region = cfg.get("region", "")
    if not region:
        return {"ok": False, "error": "No region configured (FR-05)."}
    if not cfg.get("news_api_key"):
        return {"ok": False, "error": "No News API key configured."}
    if not cfg.get("smtp_user") or not cfg.get("smtp_password"):
        return {"ok": False, "error": "SMTP credentials not configured."}

    start_time = datetime.now(timezone.utc)
    log_event(f"{'TEST ' if is_test else ''}Digest run started for region: {region}")

    # Fetch with retry (FR-01 AC3)
    headlines, sports = [], []
    for attempt in range(3):
        headlines = fetch_news(cfg["news_api_key"], region, "general")
        sports = fetch_news(cfg["news_api_key"], region, "sports")
        if headlines or sports:
            break
        if attempt < 2:
            time.sleep(5)

    send_result = send_email(cfg, region, headlines, sports, is_test)
    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    ok = len(send_result["success"]) > 0
    status = "success" if ok else "failed"

    history_entry = {
        "date": start_time.strftime("%Y-%m-%d %H:%M UTC"),
        "region": region,
        "is_test": is_test,
        "headline_count": len(headlines),
        "sports_count": len(sports),
        "status": status,
        "delivered_to": send_result["success"],
        "failed_to": [f["email"] for f in send_result["failed"]],
        "error": send_result.get("error"),
        "duration_seconds": round(duration, 1),
    }
    append_history_entry(history_entry)

    if ok and not is_test:
        cfg["last_sent_date"] = start_time.strftime("%Y-%m-%d")
        save_config(cfg)

    log_event(f"Digest {'TEST ' if is_test else ''}completed: {status} | headlines={len(headlines)} | sports={len(sports)} | duration={duration:.1f}s")

    return {"ok": ok, "entry": history_entry, "send_result": send_result}


# ═══════════════════════════════════════════════════════════════════════════════
# Auto-send check on page load
# ═══════════════════════════════════════════════════════════════════════════════

def auto_send_check(cfg: dict):
    """Called on every page load — fires digest if Tuesday + correct time."""
    if should_send_today(cfg) and is_send_time_now(cfg):
        result = run_digest(cfg, is_test=False)
        if result.get("ok"):
            st.toast("✅ Tuesday digest sent automatically!", icon="📬")
        else:
            st.toast(f"⚠️ Auto-send failed: {result.get('error','Unknown error')}", icon="❌")


# ═══════════════════════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
  .block-container { padding-top: 1.5rem; }
  .stTabs [data-baseweb="tab"] { font-size: 14px; font-weight: 500; }
  .metric-card {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 16px 20px; text-align: center;
  }
  .metric-card .val { font-size: 28px; font-weight: 700; color: #1e3a5f; }
  .metric-card .lbl { font-size: 12px; color: #64748b; margin-top: 2px; }
  .status-ok   { color: #15803d; font-weight: 600; }
  .status-fail { color: #b91c1c; font-weight: 600; }
  .status-test { color: #9333ea; font-weight: 600; }
  .region-banner {
    background: linear-gradient(90deg,#1e3a5f,#1d4ed8);
    color: white; border-radius: 8px; padding: 14px 20px;
    font-size: 15px; font-weight: 600; margin-bottom: 1rem;
  }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Main app layout
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    cfg = load_config()

    # Auto-send check on every page load (FR-01, FR-11)
    auto_send_check(cfg)

    # ── Header ────────────────────────────────────────────────────────────────
    col_logo, col_title, col_status = st.columns([1, 5, 2])
    with col_logo:
        st.markdown("## 📰")
    with col_title:
        st.markdown("### Weekly Regional News Digest")
        st.caption("Automated Tuesday email delivery · nictipoff@gmail.com · mdk32366@gmail.com")
    with col_status:
        now = datetime.now(timezone.utc)
        days_until_tuesday = (1 - now.weekday()) % 7
        next_tue = (now + timedelta(days=days_until_tuesday)).strftime("%b %d")
        paused_badge = "🔴 PAUSED" if cfg.get("paused") else "🟢 ACTIVE"
        st.markdown(f"**{paused_badge}**")
        st.caption(f"Next send: Tuesday, {next_tue}")

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_dash, tab_settings, tab_preview, tab_history = st.tabs([
        "📊  Dashboard", "⚙️  Settings", "🔍  Preview & Test Send", "📋  Delivery History"
    ])

    # ════════════════════════════════════════════════════════════════════
    # TAB 1 — DASHBOARD
    # ════════════════════════════════════════════════════════════════════
    with tab_dash:
        if cfg.get("region"):
            st.markdown(f'<div class="region-banner">📍 Active Region: {cfg["region"]}</div>', unsafe_allow_html=True)
        else:
            st.warning("⚠️ No region configured. Go to **Settings** to select a region before the next Tuesday send.", icon="🗺️")

        history = load_history()
        total_sends = len([h for h in history if not h.get("is_test")])
        success_sends = len([h for h in history if not h.get("is_test") and h.get("status") == "success"])
        total_tests = len([h for h in history if h.get("is_test")])
        last_status = history[0].get("status", "—") if history else "No sends yet"

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f'<div class="metric-card"><div class="val">{total_sends}</div><div class="lbl">Scheduled Sends</div></div>', unsafe_allow_html=True)
        with c2:
            rate = f"{int(success_sends/total_sends*100)}%" if total_sends else "—"
            st.markdown(f'<div class="metric-card"><div class="val">{rate}</div><div class="lbl">Success Rate</div></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="metric-card"><div class="val">{total_tests}</div><div class="lbl">Test Sends</div></div>', unsafe_allow_html=True)
        with c4:
            color_class = "status-ok" if last_status == "success" else ("status-test" if last_status == "—" else "status-fail")
            st.markdown(f'<div class="metric-card"><div class="val {color_class}" style="font-size:16px;">{last_status.upper()}</div><div class="lbl">Last Send Status</div></div>', unsafe_allow_html=True)

        st.markdown("")

        # Configuration status
        st.subheader("Configuration Health")
        checks = {
            "Region configured": bool(cfg.get("region")),
            "News API key set": bool(cfg.get("news_api_key")),
            "SMTP host configured": bool(cfg.get("smtp_host")),
            "SMTP credentials set": bool(cfg.get("smtp_user") and cfg.get("smtp_password")),
            "Send time configured": bool(cfg.get("send_time")),
            "Scheduling active (not paused)": not cfg.get("paused", False),
        }
        col_a, col_b = st.columns(2)
        items = list(checks.items())
        for i, (label, ok) in enumerate(items):
            col = col_a if i < 3 else col_b
            with col:
                icon = "✅" if ok else "❌"
                st.markdown(f"{icon} {label}")

        st.markdown("")

        # Pause toggle (FR-15)
        st.subheader("Delivery Control")
        col_pause, col_info = st.columns([2, 3])
        with col_pause:
            if cfg.get("paused"):
                if st.button("▶️  Resume Sending", use_container_width=True, type="primary"):
                    cfg["paused"] = False
                    save_config(cfg)
                    st.success("Delivery resumed. Next send: this Tuesday (if today) or next Tuesday.")
                    st.rerun()
            else:
                if st.button("⏸️  Pause Sending", use_container_width=True):
                    cfg["paused"] = True
                    save_config(cfg)
                    st.info("Delivery paused. No emails will be sent until resumed.")
                    st.rerun()
        with col_info:
            if cfg.get("paused"):
                st.warning("Sending is **paused**. Missed Tuesdays will not be retroactively sent when resumed. (FR-15)")
            else:
                st.info(f"Digest will auto-send every Tuesday at **{cfg.get('send_time','07:00')} UTC**.")

    # ════════════════════════════════════════════════════════════════════
    # TAB 2 — SETTINGS
    # ════════════════════════════════════════════════════════════════════
    with tab_settings:
        st.subheader("Region Configuration")

        region_options = ["— Select a region —"] + sorted(US_REGIONS.keys())
        current_idx = 0
        if cfg.get("region") in region_options:
            current_idx = region_options.index(cfg["region"])

        selected_region = st.selectbox(
            "Geographic Region (FR-05)",
            options=region_options,
            index=current_idx,
            help="This region drives both Headline and Sports News fetching. Changes take effect on the next Tuesday send."
        )

        if selected_region != "— Select a region —" and cfg.get("news_api_key"):
            col_val, col_btn = st.columns([4, 1])
            with col_btn:
                if st.button("Check Coverage", help="Validate news availability for this region (FR-06)"):
                    with st.spinner("Checking coverage..."):
                        coverage = validate_region_coverage(cfg["news_api_key"], selected_region)
                    if coverage["sufficient"]:
                        st.success(f"✅ Good coverage: {coverage['headline_count']} headlines, {coverage['sports_count']} sports articles found.")
                    else:
                        st.warning(f"⚠️ Limited coverage: {coverage['headline_count']} headlines, {coverage['sports_count']} sports articles. You can still save this region.")

        st.divider()
        st.subheader("Delivery Schedule")
        send_time = st.time_input(
            "Send Time (UTC) (FR-01)",
            value=datetime.strptime(cfg.get("send_time", "07:00"), "%H:%M").time(),
            help="Time (UTC) to send every Tuesday. Default: 7:00 AM UTC."
        )

        st.divider()
        st.subheader("Sender Identity (FR-04)")
        sender_name = st.text_input("From Name", value=cfg.get("sender_name", "Regional News Digest"))

        st.divider()
        st.subheader("API Configuration (FR-13)")
        st.caption("Credentials are stored locally in data/config.json. Never commit this file to source control.")

        with st.expander("📰 News API Key (NewsAPI.org)", expanded=not bool(cfg.get("news_api_key"))):
            st.markdown("Get a free key at [newsapi.org](https://newsapi.org) — free tier supports ~100 requests/day.")
            news_api_key = st.text_input("News API Key", value=cfg.get("news_api_key", ""), type="password")

        with st.expander("📧 SMTP / Email Settings", expanded=not bool(cfg.get("smtp_user"))):
            st.markdown("For Gmail: use an [App Password](https://support.google.com/accounts/answer/185833) (not your main password).")
            smtp_host = st.text_input("SMTP Host", value=cfg.get("smtp_host", "smtp.gmail.com"))
            smtp_port = st.number_input("SMTP Port", value=cfg.get("smtp_port", 587), min_value=1, max_value=65535)
            smtp_user = st.text_input("SMTP Username (email)", value=cfg.get("smtp_user", ""))
            smtp_password = st.text_input("SMTP Password / App Password", value=cfg.get("smtp_password", ""), type="password")

        st.divider()
        st.subheader("Recipients (FR-02)")
        st.info("Recipients are fixed per requirements. Both addresses receive identical content.")
        for r in HARDCODED_RECIPIENTS:
            st.markdown(f"📧 `{r}`")

        st.markdown("")
        if st.button("💾  Save All Settings", type="primary", use_container_width=True):
            if selected_region == "— Select a region —":
                st.error("Please select a region before saving.")
            else:
                cfg["region"] = selected_region
                cfg["region_query"] = US_REGIONS.get(selected_region, selected_region)
                cfg["send_time"] = send_time.strftime("%H:%M")
                cfg["sender_name"] = sender_name
                cfg["news_api_key"] = news_api_key
                cfg["smtp_host"] = smtp_host
                cfg["smtp_port"] = int(smtp_port)
                cfg["smtp_user"] = smtp_user
                cfg["smtp_password"] = smtp_password
                save_config(cfg)
                log_event(f"Configuration saved. Region: {selected_region}, send_time: {send_time.strftime('%H:%M')}")
                st.success("✅ Settings saved. Changes take effect on the next scheduled run.")
                st.rerun()

    # ════════════════════════════════════════════════════════════════════
    # TAB 3 — PREVIEW & TEST SEND
    # ════════════════════════════════════════════════════════════════════
    with tab_preview:
        st.subheader("Preview & Test Send (FR-12)")
        st.info("A test send fetches live news and delivers to both recipients with a **[TEST]** subject prefix. It does not affect the scheduled Tuesday send.")

        region = cfg.get("region", "")
        if not region:
            st.warning("Configure a region in **Settings** first.")
        elif not cfg.get("news_api_key"):
            st.warning("Configure a News API key in **Settings** first.")
        else:
            col_fetch, col_send = st.columns(2)

            with col_fetch:
                if st.button("🔍  Fetch & Preview News", use_container_width=True):
                    with st.spinner(f"Fetching latest news for {region}..."):
                        headlines = fetch_news(cfg["news_api_key"], region, "general")
                        sports = fetch_news(cfg["news_api_key"], region, "sports")
                    st.session_state["preview_headlines"] = headlines
                    st.session_state["preview_sports"] = sports
                    st.success(f"Fetched {len(headlines)} headlines and {len(sports)} sports articles.")

            with col_send:
                smtp_ready = bool(cfg.get("smtp_user") and cfg.get("smtp_password"))
                if not smtp_ready:
                    st.button("📬  Send Test Email", disabled=True, use_container_width=True, help="Configure SMTP in Settings first.")
                else:
                    if st.button("📬  Send Test Email Now", type="primary", use_container_width=True):
                        with st.spinner("Sending test email..."):
                            result = run_digest(cfg, is_test=True)
                        if result.get("ok"):
                            entry = result["entry"]
                            st.success(f"✅ Test email sent to: {', '.join(entry['delivered_to'])}")
                        else:
                            st.error(f"❌ Send failed: {result.get('error') or result['entry'].get('error')}")

            # Preview pane
            if "preview_headlines" in st.session_state:
                headlines = st.session_state["preview_headlines"]
                sports = st.session_state["preview_sports"]

                st.markdown("---")
                preview_col1, preview_col2 = st.columns(2)

                with preview_col1:
                    st.markdown(f"**🗞 Regional Headlines** ({len(headlines)} articles)")
                    if not headlines:
                        st.caption("No headlines found for this region.")
                    for a in headlines:
                        with st.container(border=True):
                            st.markdown(f"**{a['title']}**")
                            if a.get("description"):
                                st.caption(a["description"][:200])
                            st.caption(f"🔗 {a.get('source','')} · {format_published_date(a.get('published_at',''))}")

                with preview_col2:
                    st.markdown(f"**🏆 Sports News** ({len(sports)} articles)")
                    if not sports:
                        st.caption("No sports articles found for this region.")
                    for a in sports:
                        with st.container(border=True):
                            st.markdown(f"**{a['title']}**")
                            if a.get("description"):
                                st.caption(a["description"][:200])
                            st.caption(f"🔗 {a.get('source','')} · {format_published_date(a.get('published_at',''))}")

                # HTML email preview
                st.markdown("---")
                with st.expander("📄 View HTML Email Source"):
                    html = build_html_email(region, headlines, sports, is_test=True)
                    st.code(html, language="html")

    # ════════════════════════════════════════════════════════════════════
    # TAB 4 — DELIVERY HISTORY
    # ════════════════════════════════════════════════════════════════════
    with tab_history:
        st.subheader("Delivery History (FR-14)")
        history = load_history()

        if not history:
            st.info("No sends recorded yet. History will appear here after the first send.")
        else:
            # Export CSV (FR-14 AC3)
            def history_to_csv(history_data):
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=[
                    "date","region","is_test","headline_count","sports_count",
                    "status","delivered_to","failed_to","error","duration_seconds"
                ])
                writer.writeheader()
                for row in history_data:
                    row_copy = row.copy()
                    row_copy["delivered_to"] = "; ".join(row_copy.get("delivered_to", []))
                    row_copy["failed_to"] = "; ".join(row_copy.get("failed_to", []))
                    writer.writerow(row_copy)
                return output.getvalue()

            csv_data = history_to_csv(history)
            st.download_button(
                "⬇️  Export History as CSV",
                data=csv_data,
                file_name=f"digest_history_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )

            st.markdown("")

            # Summary metrics
            scheduled = [h for h in history if not h.get("is_test")]
            tests = [h for h in history if h.get("is_test")]
            successes = [h for h in scheduled if h.get("status") == "success"]

            m1, m2, m3 = st.columns(3)
            m1.metric("Scheduled Sends", len(scheduled))
            m2.metric("Success Rate", f"{int(len(successes)/len(scheduled)*100)}%" if scheduled else "—")
            m3.metric("Test Sends", len(tests))

            st.markdown("")

            # History table
            for entry in history[:84]:  # last 12 weeks
                is_test = entry.get("is_test", False)
                status = entry.get("status", "unknown")

                if is_test:
                    status_html = '<span class="status-test">TEST</span>'
                elif status == "success":
                    status_html = '<span class="status-ok">SUCCESS</span>'
                else:
                    status_html = '<span class="status-fail">FAILED</span>'

                delivered = ", ".join(entry.get("delivered_to", []))
                failed = ", ".join(entry.get("failed_to", []))
                error_note = f" — ⚠️ {entry.get('error')}" if entry.get("error") else ""

                with st.expander(f"{entry.get('date','?')}  ·  {entry.get('region','?')}  ·  {status.upper()}{' [TEST]' if is_test else ''}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Date:** {entry.get('date')}")
                        st.markdown(f"**Region:** {entry.get('region')}")
                        st.markdown(f"**Type:** {'Test Send' if is_test else 'Scheduled Send'}")
                        st.markdown(f"**Duration:** {entry.get('duration_seconds','?')}s")
                    with col2:
                        st.markdown(f"**Headlines fetched:** {entry.get('headline_count',0)}")
                        st.markdown(f"**Sports fetched:** {entry.get('sports_count',0)}")
                        if delivered:
                            st.markdown(f"**Delivered to:** {delivered}")
                        if failed:
                            st.markdown(f"**Failed:** {failed}")
                        if entry.get("error"):
                            st.markdown(f"**Error:** {entry['error']}")


if __name__ == "__main__":
    main()
