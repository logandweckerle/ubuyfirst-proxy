"""
Discord Webhook Utilities

Functions for sending Discord alerts with deduplication.
"""

import json
import time as _time
import logging
import subprocess
import urllib.parse
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# ============================================================
# DISCORD ALERT DEDUPLICATION (PERSISTENT)
# ============================================================

DISCORD_ALERTS_FILE = Path("discord_sent_alerts.json")
DISCORD_SENT_ALERTS: Dict[str, float] = {}  # {item_key: timestamp}
DISCORD_DEDUP_WINDOW = 1800  # 30 minutes
_DISCORD_LOCK = asyncio.Lock()  # Lock for thread-safe duplicate checking


def load_discord_alerts() -> Dict[str, float]:
    """Load sent alerts from file to survive restarts"""
    if DISCORD_ALERTS_FILE.exists():
        try:
            with open(DISCORD_ALERTS_FILE, 'r') as f:
                data = json.load(f)
                alerts = data.get('alerts', {})
                # Clean old entries on load
                current_time = _time.time()
                alerts = {k: v for k, v in alerts.items() if current_time - v < DISCORD_DEDUP_WINDOW}
                logger.info(f"[DISCORD] Loaded {len(alerts)} recent alerts from file")
                return alerts
        except Exception as e:
            logger.error(f"[DISCORD] Error loading alerts file: {e}")
    return {}


def save_discord_alerts():
    """Save sent alerts to file"""
    try:
        with open(DISCORD_ALERTS_FILE, 'w') as f:
            json.dump({
                'alerts': DISCORD_SENT_ALERTS,
                'updated': datetime.now().isoformat(),
                'count': len(DISCORD_SENT_ALERTS)
            }, f, indent=2)
    except Exception as e:
        logger.error(f"[DISCORD] Error saving alerts file: {e}")


def is_duplicate_alert(title: str, price: float) -> bool:
    """Check if this alert was recently sent"""
    global DISCORD_SENT_ALERTS

    item_key = f"{title[:50].lower().strip()}_{price:.2f}"
    current_time = _time.time()

    # Clean old entries
    expired_keys = [k for k, t in DISCORD_SENT_ALERTS.items() if current_time - t > DISCORD_DEDUP_WINDOW]
    for k in expired_keys:
        del DISCORD_SENT_ALERTS[k]

    return item_key in DISCORD_SENT_ALERTS


def mark_alert_sent(title: str, price: float):
    """Mark an alert as sent"""
    global DISCORD_SENT_ALERTS

    item_key = f"{title[:50].lower().strip()}_{price:.2f}"
    DISCORD_SENT_ALERTS[item_key] = _time.time()
    save_discord_alerts()


def get_alert_count() -> int:
    """Get number of alerts in dedup cache"""
    return len(DISCORD_SENT_ALERTS)


def clear_old_alerts():
    """Clean up expired alerts"""
    global DISCORD_SENT_ALERTS

    current_time = _time.time()
    expired_keys = [k for k, t in DISCORD_SENT_ALERTS.items() if current_time - t > DISCORD_DEDUP_WINDOW]
    for k in expired_keys:
        del DISCORD_SENT_ALERTS[k]

    if expired_keys:
        save_discord_alerts()
        logger.info(f"[DISCORD] Cleaned up {len(expired_keys)} expired alerts")


# Load alerts on module init
DISCORD_SENT_ALERTS = load_discord_alerts()


# ============================================================
# DISCORD WEBHOOK SENDING
# ============================================================

async def send_discord_alert(
    webhook_url: str,
    title: str,
    price: float,
    recommendation: str,
    category: str,
    profit: float = None,
    margin: str = None,
    reasoning: str = None,
    ebay_url: str = None,
    image_url: str = None,
    confidence: str = None,
    extra_data: dict = None,
    enable_tts: bool = True,
    server_port: int = 8000,
    seller_info: dict = None,  # {seller_id, feedback_score, feedback_percent, seller_type}
    listing_info: dict = None  # {item_id, condition, description, item_specifics, posted_time}
) -> bool:
    """
    Send a Discord webhook alert for BUY/RESEARCH recommendations.
    Includes duplicate detection to prevent spamming the same item.

    Returns True if alert was sent, False if skipped (duplicate) or failed.
    """
    logger.info(f"[DISCORD] send_discord_alert called: {recommendation} - {title[:40]}...")

    if not webhook_url:
        logger.warning("[DISCORD] No webhook URL configured, skipping alert")
        return False

    # DUPLICATE DETECTION (with lock to prevent race conditions)
    async with _DISCORD_LOCK:
        if is_duplicate_alert(title, price):
            logger.info(f"[DISCORD] Duplicate alert suppressed: {title[:40]}...")
            return False

        # Mark as sent immediately (inside lock to prevent race)
        mark_alert_sent(title, price)

    try:
        # Color based on recommendation
        colors = {
            "BUY": 0x00FF00,      # Green
            "RESEARCH": 0xFFFF00, # Yellow
            "PASS": 0xFF0000      # Red (shouldn't happen but just in case)
        }
        color = colors.get(recommendation, 0x808080)

        # Build embed with enhanced fields
        profit_str = f"+${profit:.0f}" if profit and profit > 0 else (str(margin) if margin else "N/A")

        embed = {
            "title": f"{recommendation}: {title[:80]}",
            "color": color,
            "fields": [
                {"name": "Price", "value": f"${price:.2f}", "inline": True},
                {"name": "PROFIT", "value": profit_str, "inline": True},
                {"name": "Category", "value": category.upper(), "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "ShadowSnipe Stealth Arbitrage"}
        }

        # Add confidence if available
        if confidence:
            embed["fields"].append({"name": "Conf", "value": str(confidence), "inline": True})

        # Add extra category-specific data
        if extra_data:
            for key, label in [('karat', 'Karat'), ('weight', 'Weight'), ('melt', 'Melt'), ('market_price', 'Market')]:
                if extra_data.get(key):
                    val = f"${extra_data[key]}" if key in ['melt', 'market_price'] else str(extra_data[key])
                    embed["fields"].append({"name": label, "value": val, "inline": True})

        # Add reasoning (truncated)
        if reasoning:
            embed["fields"].append({
                "name": "Analysis",
                "value": reasoning[:500] + "..." if len(reasoning) > 500 else reasoning,
                "inline": False
            })

        # Add eBay link
        if ebay_url:
            embed["fields"].append({
                "name": "eBay Link",
                "value": f"[View Listing]({ebay_url})",
                "inline": True
            })

        # Add log purchase link (opens local endpoint)
        purchase_data = {
            "title": title[:100],
            "price": price,
            "category": category,
            "profit": profit or 0,
            "confidence": confidence or "",
            "recommendation": recommendation
        }
        # Add seller info if available
        if seller_info:
            purchase_data["seller_id"] = seller_info.get("seller_id", "")
            purchase_data["feedback_score"] = seller_info.get("feedback_score", "")
            purchase_data["feedback_percent"] = seller_info.get("feedback_percent", "")
            purchase_data["seller_type"] = seller_info.get("seller_type", "")
        # Add listing info if available
        if listing_info:
            purchase_data["item_id"] = listing_info.get("item_id", "")
            purchase_data["condition"] = listing_info.get("condition", "")
            purchase_data["posted_time"] = listing_info.get("posted_time", "")
        # Add extra data (weight, melt, karat)
        if extra_data:
            for key in ['weight', 'melt', 'karat', 'market_price']:
                if extra_data.get(key):
                    purchase_data[key] = extra_data[key]

        purchase_params = urllib.parse.urlencode(purchase_data)
        log_url = f"http://localhost:{server_port}/log-purchase-quick?{purchase_params}"
        embed["fields"].append({
            "name": "Log Purchase",
            "value": f"[I Bought This]({log_url})",
            "inline": True
        })

        # Add thumbnail if we have an image
        if image_url:
            embed["thumbnail"] = {"url": image_url}

        # Build payload
        payload = {
            "username": "ShadowSnipe",
            "embeds": [embed]
        }

        # Add content message for BUY
        if recommendation == "BUY":
            payload["content"] = f"**SNIPE ALERT** - {category.upper()} - ${price:.2f} - Profit: {profit_str}"

        # Send webhook
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.post(webhook_url, json=payload)

            if response.status_code in (200, 204):
                logger.info(f"[DISCORD] Alert sent for {recommendation}: {title[:40]}...")

                # TTS notification for BUY alerts (Windows only)
                if enable_tts and recommendation == "BUY":
                    try:
                        # Clean title for TTS - remove special chars that break PowerShell
                        tts_title = title.replace('+', ' ').replace('%20', ' ').replace('"', '').replace("'", "")[:80]
                        tts_text = f"Buy alert. {tts_title}. Price ${price:.0f}. Profit {profit_str}"
                        # Escape any remaining problematic characters
                        tts_text = tts_text.replace('"', '').replace("'", "").replace('`', '')
                        ps_cmd = f'Add-Type -AssemblyName System.Speech; $speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; $speak.Rate = 2; $speak.Speak("{tts_text}")'
                        subprocess.Popen(["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                                       creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
                        logger.warning(f"[TTS] Speaking: {tts_title[:40]}...")
                    except Exception as tts_err:
                        logger.warning(f"[TTS] Error: {tts_err}")

                return True
            else:
                logger.warning(f"[DISCORD] Webhook returned {response.status_code}: {response.text}")
                return False

    except Exception as e:
        logger.error(f"[DISCORD] Error sending alert: {e}")
        return False


async def send_simple_discord_message(webhook_url: str, message: str, username: str = "ShadowSnipe") -> bool:
    """Send a simple text message to Discord"""
    if not webhook_url:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.post(
                webhook_url,
                json={"username": username, "content": message}
            )
            return response.status_code in (200, 204)
    except Exception as e:
        logger.error(f"[DISCORD] Error sending message: {e}")
        return False
