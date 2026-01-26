"""
Missed Opportunity Analyzer

Analyzes fast sales (items that sold in < 5 min) to identify:
1. True missed opportunities (had profit margin, we passed)
2. Patterns in missed deals (keywords, sellers, price ranges)
3. Seller signals (who consistently has fast-selling deals)

This data trains our system to catch similar deals in the future.
"""
import sqlite3
import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Database paths
TRACKING_DB = Path(__file__).parent / "item_tracking.db"
ARBITRAGE_DB = Path(__file__).parent / "arbitrage_data.db"

# Current spot prices (update these or fetch dynamically)
SPOT_PRICES = {
    "gold_oz": 2650,  # Will be updated from spot_prices.py
    "silver_oz": 31,
    "24K": 85.20,
    "22K": 78.10,
    "18K": 63.90,
    "14K": 49.80,
    "10K": 35.60,
    "9K": 32.00,
    "sterling": 0.92 * 31 / 31.1,  # 92.5% pure
}

def load_spot_prices():
    """Try to load current spot prices from the running server."""
    global SPOT_PRICES
    try:
        from spot_prices import get_rates
        rates = get_rates()
        if rates:
            SPOT_PRICES.update(rates)
            print(f"[SPOT] Loaded current prices: Gold=${rates.get('gold_oz', 0):.0f}/oz, Silver=${rates.get('silver_oz', 0):.2f}/oz")
    except Exception as e:
        print(f"[SPOT] Using default prices (couldn't load current: {e})")


def extract_weight(title, description=""):
    """Extract weight in grams from title/description."""
    text = f"{title} {description}".lower()

    # Patterns for weight extraction
    patterns = [
        (r'(\d+\.?\d*)\s*(?:gram|grams|gr)\b', 1.0),
        (r'(\d+\.?\d*)\s*g\b', 1.0),
        (r'(\d+\.?\d*)\s*(?:dwt|DWT)\b', 1.555),
        (r'(\d+\.?\d*)\s*(?:ozt|oz\.t|troy\s*oz)\b', 31.1),
        (r'(\d+\.?\d*)\s*oz\b', 28.35),
    ]

    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            weight = float(match.group(1))
            # Skip years (1900-2030)
            if 1900 <= weight <= 2030:
                continue
            # Skip fineness markings (375, 417, 585, 750, 800, 830, 900, 916, 925, 950, 999)
            if weight in [375, 417, 585, 750, 800, 830, 900, 916, 925, 936, 950, 958, 999]:
                continue
            final_weight = weight * multiplier
            # Sanity check: jewelry rarely weighs more than 500g
            if final_weight > 500:
                continue
            return final_weight

    return None


def extract_karat(title):
    """Extract karat from title."""
    title_lower = title.lower()

    patterns = [
        (r'24\s*k(?:t|arat)?', 24),
        (r'22\s*k(?:t|arat)?', 22),
        (r'18\s*k(?:t|arat)?', 18),
        (r'14\s*k(?:t|arat)?', 14),
        (r'10\s*k(?:t|arat)?', 10),
        (r'9\s*k(?:t|arat)?', 9),
        (r'999', 24),
        (r'916', 22),
        (r'750', 18),
        (r'585', 14),
        (r'417', 10),
        (r'375', 9),
    ]

    for pattern, karat in patterns:
        if re.search(pattern, title_lower):
            return karat
    return None


def calculate_melt_value(weight_grams, karat=None, category="gold"):
    """Calculate melt value based on weight and purity."""
    if not weight_grams or weight_grams <= 0:
        return None

    if category == "gold" and karat:
        rate_key = f"{karat}K"
        rate = SPOT_PRICES.get(rate_key, SPOT_PRICES.get("14K", 50))
        return weight_grams * rate
    elif category == "silver":
        rate = SPOT_PRICES.get("sterling", 0.90)
        return weight_grams * rate

    return None


def has_non_metal_value(title):
    """Check if item has significant non-metal value (stones, brand, etc.)."""
    title_lower = title.lower()

    # Stones that add value beyond metal
    stone_keywords = [
        'diamond', 'ruby', 'sapphire', 'emerald', 'opal', 'tanzanite',
        'carat', 'ctw', 'cttw', 'ct tw',
    ]

    # Brands priced above melt
    brand_keywords = [
        'tiffany', 'cartier', 'van cleef', 'david yurman', 'james avery',
        'pandora', 'john hardy', 'roberto coin', 'bulgari', 'chopard',
        'links of london', 'lagos', 'ippolita',
    ]

    for kw in stone_keywords:
        if kw in title_lower:
            return "stone"

    for kw in brand_keywords:
        if kw in title_lower:
            return "brand"

    return None


def analyze_fast_sales():
    """Main analysis function."""
    load_spot_prices()

    conn = sqlite3.connect(TRACKING_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all fast sales with data
    cursor.execute("""
        SELECT
            item_id, title, price, category, recommendation,
            time_to_sell_minutes, seller_name, alias,
            original_data_json, analysis_result_json, sold_time
        FROM tracked_items
        WHERE is_fast_sale = 1
        AND category IN ('gold', 'silver', 'watch')
        ORDER BY sold_time DESC
    """)

    fast_sales = [dict(row) for row in cursor.fetchall()]
    conn.close()

    print(f"\n{'='*70}")
    print(f"MISSED OPPORTUNITY ANALYSIS")
    print(f"{'='*70}")
    print(f"Total fast sales in gold/silver/watch: {len(fast_sales)}")

    # Categorize results
    true_missed = []  # Had margin, we passed
    correctly_passed = []  # No margin or brand/stone value
    correctly_bought = []  # We said BUY, it sold fast
    unclear = []  # Can't determine

    seller_stats = defaultdict(lambda: {"fast_sales": 0, "missed": 0, "categories": set(), "avg_price": 0, "total_price": 0})
    keyword_stats = defaultdict(lambda: {"count": 0, "missed": 0, "total_margin": 0})

    for sale in fast_sales:
        title = (sale["title"] or "").replace("+", " ")
        title_lower = title.lower()
        category = sale["category"]
        recommendation = sale["recommendation"] or ""
        seller = (sale["seller_name"] or "").replace("+", " ")
        time_to_sell = sale["time_to_sell_minutes"] or 0

        # Clean price (remove $ and commas)
        price_str = str(sale["price"] or "0").replace("$", "").replace(",", "")
        try:
            price = float(price_str)
        except:
            price = 0

        # Parse original data if available
        original_data = {}
        if sale["original_data_json"]:
            try:
                original_data = json.loads(sale["original_data_json"])
            except:
                pass

        # Parse analysis result if available
        analysis = {}
        if sale["analysis_result_json"]:
            try:
                analysis = json.loads(sale["analysis_result_json"])
            except:
                pass

        # Extract weight and calculate potential melt value
        description = original_data.get("Description", original_data.get("description", ""))
        weight = extract_weight(title, description)
        karat = extract_karat(title) if category == "gold" else None

        # Check for non-metal value
        non_metal = has_non_metal_value(title)

        # Try to get weight/melt from stored AI analysis
        ai_weight = None
        ai_melt = None
        ai_margin = None
        if analysis:
            # Try various keys the AI might have used
            weight_str = str(analysis.get("weight", analysis.get("goldweight", analysis.get("silverweight", "")))).replace("g", "").strip()
            try:
                if weight_str and weight_str not in ["", "NA", "None", "--", "0", "N/A"]:
                    ai_weight = float(weight_str)
            except:
                pass

            melt_str = str(analysis.get("meltvalue", analysis.get("melt", ""))).replace("$", "").replace(",", "").strip()
            try:
                if melt_str and melt_str not in ["", "NA", "None", "--"]:
                    ai_melt = float(melt_str)
            except:
                pass

            margin_str = str(analysis.get("Profit", analysis.get("Margin", ""))).replace("$", "").replace("+", "").replace(",", "").strip()
            try:
                if margin_str and margin_str not in ["", "NA", "None", "--"]:
                    ai_margin = float(margin_str)
            except:
                pass

        # Use AI values if we couldn't extract ourselves
        if not weight and ai_weight:
            weight = ai_weight
        if not karat and analysis.get("karat"):
            karat_str = str(analysis.get("karat", "")).replace("K", "").replace("k", "").strip()
            try:
                karat = int(karat_str)
            except:
                pass

        # Calculate potential melt value
        melt_value = ai_melt  # Prefer AI calculation
        potential_margin = ai_margin

        if not melt_value and weight:
            melt_value = calculate_melt_value(weight, karat, category)
            if melt_value:
                if category == "gold":
                    max_buy = melt_value * 0.95
                else:
                    max_buy = melt_value * 0.70
                potential_margin = max_buy - price

        # Classify the sale
        result = {
            "title": title[:60],
            "price": price,
            "category": category,
            "recommendation": recommendation,
            "time_to_sell": time_to_sell,
            "seller": seller,
            "weight": weight,
            "karat": karat,
            "melt_value": melt_value,
            "potential_margin": potential_margin,
            "non_metal": non_metal,
        }

        # Track seller stats
        if seller:
            seller_stats[seller]["fast_sales"] += 1
            seller_stats[seller]["categories"].add(category)
            seller_stats[seller]["total_price"] += price

        # Track keyword stats
        keywords_found = []
        keyword_patterns = [
            "vintage", "antique", "estate", "scrap", "lot", "grams", "dwt",
            "broken", "as is", "parts", "repair", "not working",
            "14k", "18k", "10k", "925", "sterling",
            "chain", "bracelet", "ring", "necklace", "pendant", "earring",
            "navajo", "native", "turquoise", "mexican",
            "pocket watch", "waltham", "elgin", "hamilton", "omega",
        ]
        for kw in keyword_patterns:
            if kw in title_lower:
                keywords_found.append(kw)
                keyword_stats[kw]["count"] += 1

        # Classify
        if "BUY" in recommendation.upper():
            correctly_bought.append(result)
        elif "PASS" in recommendation.upper():
            if non_metal:
                # Passed due to brand/stone - check if we were right
                correctly_passed.append(result)
                result["pass_reason"] = non_metal
            elif potential_margin and potential_margin > 20:
                # We passed but there was margin - TRUE MISS
                true_missed.append(result)
                if seller:
                    seller_stats[seller]["missed"] += 1
                for kw in keywords_found:
                    keyword_stats[kw]["missed"] += 1
                    keyword_stats[kw]["total_margin"] += potential_margin
            elif potential_margin and potential_margin > 0:
                # Marginal - could go either way
                unclear.append(result)
            else:
                # No margin found - correctly passed
                correctly_passed.append(result)
        else:
            # No recommendation
            if potential_margin and potential_margin > 20:
                true_missed.append(result)
                if seller:
                    seller_stats[seller]["missed"] += 1
            else:
                unclear.append(result)

    # Print results
    print(f"\n{'='*70}")
    print("CLASSIFICATION RESULTS")
    print(f"{'='*70}")
    print(f"TRUE MISSED OPPORTUNITIES: {len(true_missed)}")
    print(f"Correctly Passed (brand/stone): {len(correctly_passed)}")
    print(f"Correctly Bought: {len(correctly_bought)}")
    print(f"Unclear (no weight/margin data): {len(unclear)}")

    print(f"\n{'='*70}")
    print("TOP 20 TRUE MISSED OPPORTUNITIES")
    print(f"{'='*70}")
    # Sort by margin
    true_missed.sort(key=lambda x: x["potential_margin"] or 0, reverse=True)
    for item in true_missed[:20]:
        print(f"\n${item['price']:.0f} | {item['category']} | {item['time_to_sell']:.1f}min | Margin: ${item['potential_margin']:.0f}")
        print(f"  {item['title']}")
        if item['weight']:
            print(f"  Weight: {item['weight']:.1f}g | Karat: {item['karat'] or 'N/A'} | Melt: ${item['melt_value']:.0f}")
        print(f"  Seller: {item['seller']}")

    print(f"\n{'='*70}")
    print("SELLERS WITH MULTIPLE MISSED OPPORTUNITIES")
    print("(These sellers consistently have deals we're missing)")
    print(f"{'='*70}")
    # Sort sellers by missed count
    hot_sellers = [(s, d) for s, d in seller_stats.items() if d["missed"] >= 2]
    hot_sellers.sort(key=lambda x: x[1]["missed"], reverse=True)
    for seller, data in hot_sellers[:15]:
        avg_price = data["total_price"] / data["fast_sales"] if data["fast_sales"] > 0 else 0
        cats = ", ".join(data["categories"])
        print(f"{seller}: {data['missed']} missed / {data['fast_sales']} fast sales | Avg ${avg_price:.0f} | {cats}")

    print(f"\n{'='*70}")
    print("KEYWORDS IN MISSED OPPORTUNITIES")
    print("(Keywords that appear in items we should have bought)")
    print(f"{'='*70}")
    # Sort keywords by missed count
    hot_keywords = [(k, d) for k, d in keyword_stats.items() if d["missed"] >= 2]
    hot_keywords.sort(key=lambda x: x[1]["missed"], reverse=True)
    for keyword, data in hot_keywords[:20]:
        hit_rate = (data["missed"] / data["count"] * 100) if data["count"] > 0 else 0
        avg_margin = (data["total_margin"] / data["missed"]) if data["missed"] > 0 else 0
        print(f"'{keyword}': {data['missed']} missed / {data['count']} total ({hit_rate:.0f}% miss rate) | Avg margin ${avg_margin:.0f}")

    print(f"\n{'='*70}")
    print("CORRECTLY PASSED (Brand/Stone Items)")
    print("(Fast sales but correctly passed - priced for brand/stone, not metal)")
    print(f"{'='*70}")
    for item in correctly_passed[:10]:
        reason = item.get("pass_reason", "unknown")
        print(f"${item['price']:.0f} | {item['category']} | Reason: {reason} | {item['title'][:50]}")

    print(f"\n{'='*70}")
    print("UNCLEAR ITEMS ANALYSIS")
    print("(Fast sales without weight data - need manual review)")
    print(f"{'='*70}")

    # Analyze unclear items by price range and category
    unclear_by_cat = defaultdict(list)
    for item in unclear:
        unclear_by_cat[item["category"]].append(item)

    for cat, items in unclear_by_cat.items():
        print(f"\n{cat.upper()}: {len(items)} unclear fast sales")
        # Show some samples
        for item in sorted(items, key=lambda x: x["price"], reverse=True)[:5]:
            print(f"  ${item['price']:.0f} | {item['time_to_sell']:.1f}min | {item['seller'][:15]} | {item['title'][:45]}")

    # Analyze sellers in unclear category
    print(f"\n{'='*70}")
    print("SELLERS IN UNCLEAR CATEGORY (worth investigating)")
    print(f"{'='*70}")
    unclear_sellers = defaultdict(lambda: {"count": 0, "total_price": 0, "categories": set()})
    for item in unclear:
        seller = item["seller"]
        if seller:
            unclear_sellers[seller]["count"] += 1
            unclear_sellers[seller]["total_price"] += item["price"]
            unclear_sellers[seller]["categories"].add(item["category"])

    top_unclear_sellers = sorted(unclear_sellers.items(), key=lambda x: x[1]["count"], reverse=True)[:15]
    for seller, data in top_unclear_sellers:
        if data["count"] >= 2:
            avg = data["total_price"] / data["count"]
            cats = ", ".join(data["categories"])
            print(f"{seller}: {data['count']} unclear fast sales | Avg ${avg:.0f} | {cats}")

    # Save detailed results to JSON for further analysis
    output = {
        "analysis_time": datetime.now().isoformat(),
        "summary": {
            "total_fast_sales": len(fast_sales),
            "true_missed": len(true_missed),
            "correctly_passed": len(correctly_passed),
            "correctly_bought": len(correctly_bought),
            "unclear": len(unclear),
        },
        "true_missed": true_missed[:50],
        "hot_sellers": [{"seller": s, **d, "categories": list(d["categories"])} for s, d in hot_sellers[:20]],
        "hot_keywords": [{"keyword": k, **d} for k, d in hot_keywords[:30]],
    }

    output_path = Path(__file__).parent / "missed_opportunity_analysis.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n[SAVED] Full analysis saved to: {output_path}")

    return output


if __name__ == "__main__":
    analyze_fast_sales()
