"""
Continuous Keepa Deal Monitor
Checks for 40%+ drops every 5 minutes, sends to Discord
"""
import asyncio
import aiohttp
import sys
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

KEEPA_API_KEY = os.getenv("KEEPA_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# Configuration
CHECK_INTERVAL_MINUTES = 5
MIN_DROP_PERCENT = 40
MIN_MONTHLY_SOLD = 50      # Lowered from 100
ALERT_COOLDOWN_HOURS = 24  # Don't re-alert same ASIN within this window

# Track alerted ASINs to avoid duplicates
ALERTED_FILE = "alerted_asins.json"

def load_alerted_asins():
    """Load previously alerted ASINs"""
    if os.path.exists(ALERTED_FILE):
        try:
            with open(ALERTED_FILE, 'r') as f:
                data = json.load(f)
                # Clean up old entries
                cutoff = datetime.now() - timedelta(hours=ALERT_COOLDOWN_HOURS)
                return {k: v for k, v in data.items()
                        if datetime.fromisoformat(v) > cutoff}
        except:
            return {}
    return {}

def save_alerted_asins(alerted):
    """Save alerted ASINs"""
    with open(ALERTED_FILE, 'w') as f:
        json.dump(alerted, f)

def was_recently_alerted(asin, alerted):
    """Check if ASIN was alerted recently"""
    if asin in alerted:
        alert_time = datetime.fromisoformat(alerted[asin])
        if datetime.now() - alert_time < timedelta(hours=ALERT_COOLDOWN_HOURS):
            return True
    return False

async def get_deals():
    """Fetch deals from Keepa"""
    url = "https://api.keepa.com/deal"

    selection = {
        "page": 0,
        "domainId": 1,
        "priceTypes": [0, 10, 18],  # Amazon, FBA, Buy Box
        "deltaPercentRange": [MIN_DROP_PERCENT, 95],
        "deltaLastRange": [0, 7200],  # Last 5 days
        "currentRange": [1500, 30000],  # $15-$300
        "salesRankRange": [1, 300000],  # Expanded from 150k
        "sortType": 3,  # Sales rank
        "isRangeEnabled": True,
        "singleVariation": True,
        "filterErotic": True,
        "excludeCategories": [
            7141123011, 7141124011, 7147440011,  # Apparel
            283155, 4, 2350149011,  # Books, Kindle, Audible
            173507, 2625373011,  # Music
            979455011, 11091801,  # Software, Gift Cards
        ],
    }

    params = {
        "key": KEEPA_API_KEY,
        "domain": 1,
        "selection": str(selection).replace("'", '"').replace("True", "true").replace("False", "false")
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

async def get_product_details(asin):
    """Get product details"""
    url = "https://api.keepa.com/product"
    params = {"key": KEEPA_API_KEY, "domain": 1, "asin": asin, "stats": 90}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("products"):
                    return data["products"][0]
            return None

async def get_graph_image(asin):
    """Get Keepa graph image"""
    url = "https://api.keepa.com/graphimage"
    params = {
        "key": KEEPA_API_KEY, "domain": 1, "asin": asin,
        "amazon": 1, "new": 1, "salesrank": 1, "bb": 1,
        "range": 90, "width": 600, "height": 300
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.read()
            return None

async def send_discord_alert(deal, product, graph_image, drop_pct, monthly_sold):
    """Send deal to Discord"""
    asin = deal.get("asin", "Unknown")
    title = deal.get("title", "Unknown")[:80]

    current = deal.get("current", [])
    amazon_price = current[0] if current else -1

    # Get 90-day average
    avg = deal.get("avg", [])
    avg_90 = avg[3][0] if avg and len(avg) > 3 and avg[3] else 0

    # Get sales rank
    sales_rank = "N/A"
    if product:
        stats = product.get("stats", {})
        curr = stats.get("current", [])
        if curr and len(curr) > 3 and curr[3] and curr[3] > 0:
            sales_rank = f"{curr[3]:,}"

    # Product image
    product_img = None
    if deal.get("image"):
        img_name = "".join(chr(c) for c in deal["image"])
        product_img = f"https://images-na.ssl-images-amazon.com/images/I/{img_name}"

    embed = {
        "title": f"🎯 {drop_pct}% DROP: {title}",
        "url": f"https://www.amazon.com/dp/{asin}",
        "color": 0xFF6600 if drop_pct >= 50 else 0x00FF00,
        "fields": [
            {"name": "ASIN", "value": asin, "inline": True},
            {"name": "Price", "value": f"${amazon_price/100:.2f}" if amazon_price > 0 else "N/A", "inline": True},
            {"name": "Was", "value": f"${avg_90/100:.2f}" if avg_90 > 0 else "N/A", "inline": True},
            {"name": "Drop", "value": f"**{drop_pct}%**", "inline": True},
            {"name": "Sales Rank", "value": sales_rank, "inline": True},
            {"name": "Monthly Sales", "value": f"{monthly_sold}+" if monthly_sold else "N/A", "inline": True},
        ],
        "footer": {"text": f"KeepaTracker | {datetime.now().strftime('%I:%M %p')}"}
    }

    if product_img:
        embed["thumbnail"] = {"url": product_img}
    if graph_image:
        embed["image"] = {"url": "attachment://keepa_graph.png"}

    payload = {"embeds": [embed]}

    async with aiohttp.ClientSession() as session:
        if graph_image:
            form = aiohttp.FormData()
            form.add_field('payload_json', str(payload).replace("'", '"').replace("True", "true").replace("False", "false"))
            form.add_field('file', graph_image, filename='keepa_graph.png', content_type='image/png')
            async with session.post(DISCORD_WEBHOOK_URL, data=form) as resp:
                return resp.status in [200, 204]
        else:
            async with session.post(DISCORD_WEBHOOK_URL, json=payload) as resp:
                return resp.status in [200, 204]

def passes_filters(deal):
    """Check if deal passes all filters"""
    title = deal.get("title", "").lower()

    # Skip keywords - only books/audiobooks
    skip_keywords = [
        "book", "paperback", "hardcover", "kindle", "audiobook", "audible",
        "novel", "edition", "volume", "series", "trilogy", "saga",
        "standalone", "unabridged", "abridged", "narrator", "narrated",
        "mystery", "romance", "thriller", "fantasy", "fiction",
        "memoir", "biography", "autobiography", "nonfiction",
        "self-help", "motivational", "inspirational", "mindset",
        "success", "leadership", "business skills", "personal development",
        "how to", "guide to", "secrets of", "power of", "art of",
        "mastery", "principles", "habits", "mindfulness",
    ]

    if any(kw in title for kw in skip_keywords):
        return False

    # Check root category
    root_cat = deal.get("rootCat", 0)
    bad_cats = [283155, 2350149011, 4, 173507]
    if root_cat in bad_cats:
        return False

    return True

def calculate_drop(deal):
    """Calculate drop percentage from 90-day average"""
    current = deal.get("current", [])
    amazon_price = current[0] if current else -1

    if amazon_price <= 0:
        return 0

    avg = deal.get("avg", [])
    avg_90 = 0
    if avg and len(avg) > 3 and avg[3] and len(avg[3]) > 0:
        avg_90 = avg[3][0]

    if avg_90 and avg_90 > 0:
        return round(((avg_90 - amazon_price) / avg_90) * 100)

    return 0

async def check_for_deals():
    """Main deal checking function"""
    alerted = load_alerted_asins()

    result = await get_deals()
    if not result:
        return 0

    deals = result.get("deals", {}).get("dr", [])
    tokens_left = result.get("tokensLeft", "?")

    new_alerts = 0

    for deal in deals:
        asin = deal.get("asin")

        # Skip if recently alerted
        if was_recently_alerted(asin, alerted):
            continue

        # Check filters
        if not passes_filters(deal):
            continue

        # Calculate drop
        drop_pct = calculate_drop(deal)
        if drop_pct < MIN_DROP_PERCENT:
            continue

        # Get product details for sales check
        product = await get_product_details(asin)

        # Check sales velocity
        monthly_sold = product.get("monthlySold") if product else None
        if monthly_sold is None:
            stats = product.get("stats", {}) if product else {}
            rank_drops = stats.get("salesRankDrops30", 0)
            if not rank_drops or rank_drops < MIN_MONTHLY_SOLD:
                continue
            monthly_sold = rank_drops
        elif monthly_sold < MIN_MONTHLY_SOLD:
            continue

        # Get graph and send alert
        graph = await get_graph_image(asin)
        success = await send_discord_alert(deal, product, graph, drop_pct, monthly_sold)

        if success:
            alerted[asin] = datetime.now().isoformat()
            new_alerts += 1
            print(f"  ✓ ALERT: {deal.get('title', '')[:50]}... ({drop_pct}% drop, {monthly_sold}+ sales/mo)")

        await asyncio.sleep(1)  # Rate limit

    save_alerted_asins(alerted)
    return new_alerts, tokens_left

async def main():
    print("=" * 60)
    print("KEEPA DEAL MONITOR - CONTINUOUS")
    print("=" * 60)
    print(f"\nSettings:")
    print(f"  Check interval: {CHECK_INTERVAL_MINUTES} minutes")
    print(f"  Min drop: {MIN_DROP_PERCENT}%")
    print(f"  Min sales: {MIN_MONTHLY_SOLD}/month")
    print(f"  Alert cooldown: {ALERT_COOLDOWN_HOURS} hours")
    print(f"\nMonitoring started at {datetime.now().strftime('%I:%M %p')}")
    print("Press Ctrl+C to stop\n")

    check_count = 0

    while True:
        check_count += 1
        timestamp = datetime.now().strftime('%I:%M %p')

        print(f"[{timestamp}] Check #{check_count}...", end=" ")

        try:
            new_alerts, tokens = await check_for_deals()
            print(f"Found {new_alerts} new deal(s) | Tokens: {tokens}")
        except Exception as e:
            print(f"Error: {e}")

        # Wait for next check
        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nMonitor stopped.")
