"""
Learning Engine

Processes fast sales, missed opportunities, and purchase history
to continuously improve category models.

This runs periodically to:
1. Analyze new fast sales
2. Update seller scores
3. Update keyword performance
4. Generate rule recommendations
5. Export keyword suggestions for uBuyFirst
"""

import sqlite3
import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
import logging

from .category_models import get_model, get_all_models, LEARNING_DB, TRACKING_DB

logger = logging.getLogger(__name__)


class LearningEngine:
    """Engine for learning from outcomes and updating models."""

    def __init__(self):
        self.models = get_all_models()

    def process_fast_sales(self, hours_back: int = 24) -> Dict[str, Any]:
        """
        Process recent fast sales to update models.
        Returns summary of what was learned.
        """
        conn = sqlite3.connect(TRACKING_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cutoff = (datetime.now() - timedelta(hours=hours_back)).isoformat()

        cursor.execute("""
            SELECT
                item_id, title, price, category, recommendation,
                time_to_sell_minutes, seller_name, alias,
                original_data_json, analysis_result_json, sold_time
            FROM tracked_items
            WHERE is_fast_sale = 1
            AND sold_time > ?
            AND category IN ('gold', 'silver', 'watch')
        """, (cutoff,))

        fast_sales = [dict(row) for row in cursor.fetchall()]
        conn.close()

        results = {
            "processed": 0,
            "by_category": defaultdict(int),
            "new_seller_signals": [],
            "new_keyword_signals": [],
            "opportunity_patterns": [],
        }

        for sale in fast_sales:
            self._process_single_sale(sale, results)

        # After processing, generate recommendations
        results["recommendations"] = self._generate_recommendations()

        logger.info(f"[LEARNING] Processed {results['processed']} fast sales")
        return results

    def _process_single_sale(self, sale: Dict, results: Dict):
        """Process a single fast sale."""
        title = (sale["title"] or "").replace("+", " ")
        title_lower = title.lower()
        category = sale["category"]
        seller = (sale["seller_name"] or "").replace("+", " ")
        recommendation = sale["recommendation"] or ""
        time_to_sell = sale["time_to_sell_minutes"] or 0

        # Parse price
        price_str = str(sale["price"] or "0").replace("$", "").replace(",", "")
        try:
            price = float(price_str)
        except:
            price = 0

        # Get category model
        model = get_model(category)
        if not model:
            return

        results["processed"] += 1
        results["by_category"][category] += 1

        # Determine if this was a missed opportunity
        was_pass = "PASS" in recommendation.upper()
        was_buy = "BUY" in recommendation.upper()

        # Calculate opportunity score using model
        opp_score, signals = model.calculate_opportunity_score(title, price, seller, sale)

        # Update seller score
        if seller:
            is_missed = was_pass and time_to_sell < 5
            model.update_seller_score(seller, fast_sale=True, margin=0)

            if is_missed and opp_score > 30:
                results["new_seller_signals"].append({
                    "seller": seller,
                    "category": category,
                    "score": opp_score,
                    "signals": signals,
                })

        # Extract and update keyword performance
        keywords_found = self._extract_keywords(title_lower, category)
        for kw in keywords_found:
            model.update_keyword_performance(
                kw,
                fast_sale=True,
                was_buy=was_buy,
                margin=0
            )

        # Track opportunity patterns
        if was_pass and opp_score > 40:
            results["opportunity_patterns"].append({
                "title": title[:60],
                "category": category,
                "price": price,
                "seller": seller,
                "opp_score": opp_score,
                "signals": signals,
                "time_to_sell": time_to_sell,
            })

    def _extract_keywords(self, title_lower: str, category: str) -> List[str]:
        """Extract relevant keywords from title."""
        # Category-specific keyword patterns
        keyword_patterns = {
            "gold": [
                "14k", "18k", "10k", "22k", "24k",
                "scrap", "lot", "grams", "dwt",
                "chain", "bracelet", "ring", "necklace", "pendant",
                "vintage", "antique", "estate",
                "michael anthony", "italy", "italian",
                "class ring", "signet",
            ],
            "silver": [
                "925", "sterling", "coin silver",
                "scrap", "lot", "grams", "troy",
                "flatware", "serving", "ladle", "bowl", "tray",
                "gorham", "towle", "wallace", "reed barton",
                "vintage", "antique", "estate",
                "navajo", "native", "turquoise", "mexican", "taxco",
            ],
            "watch": [
                "pocket watch", "pocket",
                "14k", "18k", "10k", "gold",
                "parts", "repair", "not working", "broken", "as is",
                "vintage", "antique", "estate",
                "waltham", "elgin", "hamilton", "omega",
                "railroad", "coin silver",
                "lot", "watchmaker",
            ],
        }

        found = []
        patterns = keyword_patterns.get(category, [])
        for kw in patterns:
            if kw in title_lower:
                found.append(kw)

        return found

    def _generate_recommendations(self) -> Dict[str, Any]:
        """Generate actionable recommendations based on learned data."""
        recommendations = {
            "keywords_to_add": [],
            "keywords_to_remove": [],
            "sellers_to_watch": [],
            "rules_to_implement": [],
        }

        conn = sqlite3.connect(LEARNING_DB)
        cursor = conn.cursor()

        # Find high-performing keywords
        cursor.execute("""
            SELECT keyword, category, fast_sales, times_seen,
                   CAST(fast_sales AS REAL) / times_seen as hit_rate
            FROM keyword_category_performance
            WHERE times_seen >= 5
            AND fast_sales >= 2
            ORDER BY hit_rate DESC
            LIMIT 20
        """)

        for row in cursor.fetchall():
            keyword, category, fast_sales, times_seen, hit_rate = row
            if hit_rate > 0.1:  # More than 10% fast sale rate
                recommendations["keywords_to_add"].append({
                    "keyword": keyword,
                    "category": category,
                    "reason": f"{fast_sales} fast sales out of {times_seen} ({hit_rate*100:.0f}%)",
                })

        # Find sellers with multiple fast sales
        cursor.execute("""
            SELECT seller_name, category, fast_sales, seller_type, score
            FROM seller_category_scores
            WHERE fast_sales >= 3
            ORDER BY fast_sales DESC
            LIMIT 20
        """)

        for row in cursor.fetchall():
            seller, category, fast_sales, seller_type, score = row
            recommendations["sellers_to_watch"].append({
                "seller": seller,
                "category": category,
                "fast_sales": fast_sales,
                "type": seller_type,
            })

        conn.close()
        return recommendations

    def get_keyword_report(self, category: str = None) -> List[Dict]:
        """Get keyword performance report for uBuyFirst optimization."""
        conn = sqlite3.connect(LEARNING_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if category:
            cursor.execute("""
                SELECT * FROM keyword_category_performance
                WHERE category = ?
                AND times_seen >= 3
                ORDER BY fast_sales DESC, times_seen DESC
            """, (category,))
        else:
            cursor.execute("""
                SELECT * FROM keyword_category_performance
                WHERE times_seen >= 3
                ORDER BY fast_sales DESC, times_seen DESC
            """)

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return results

    def get_seller_report(self, category: str = None) -> List[Dict]:
        """Get seller performance report."""
        conn = sqlite3.connect(LEARNING_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if category:
            cursor.execute("""
                SELECT * FROM seller_category_scores
                WHERE category = ?
                AND fast_sales >= 2
                ORDER BY fast_sales DESC
            """, (category,))
        else:
            cursor.execute("""
                SELECT * FROM seller_category_scores
                WHERE fast_sales >= 2
                ORDER BY fast_sales DESC
            """)

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return results

    def export_ubf_recommendations(self) -> Dict[str, Any]:
        """
        Export recommendations for uBuyFirst in actionable format.

        Returns dict with:
        - keywords_to_add: Keywords to add to searches
        - keywords_to_remove: Keywords causing noise
        - filter_suggestions: Filter rule suggestions
        """
        output = {
            "generated_at": datetime.now().isoformat(),
            "by_category": {},
        }

        for category, model in self.models.items():
            cat_output = {
                "priority_keywords": model.priority_keywords,
                "noise_keywords": model.noise_keywords,
                "reliable_brands": model.reliable_brands,
                "avoid_brands": model.avoid_brands,
                "opportunity_signals": [
                    {
                        "name": sig.name,
                        "description": sig.description,
                        "weight": sig.weight,
                    }
                    for sig in model.opportunity_signals
                ],
            }

            # Add learned keywords
            learned = self.get_keyword_report(category)
            cat_output["learned_keywords"] = [
                {
                    "keyword": k["keyword"],
                    "fast_sales": k["fast_sales"],
                    "times_seen": k["times_seen"],
                    "hit_rate": k["fast_sales"] / k["times_seen"] if k["times_seen"] > 0 else 0,
                }
                for k in learned[:20]
            ]

            # Add hot sellers
            sellers = self.get_seller_report(category)
            cat_output["hot_sellers"] = [
                {
                    "seller": s["seller_name"],
                    "fast_sales": s["fast_sales"],
                    "type": s["seller_type"],
                }
                for s in sellers[:15]
            ]

            output["by_category"][category] = cat_output

        # Save to file
        output_path = Path(__file__).parent.parent / "ubf_recommendations.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)

        logger.info(f"[LEARNING] Exported recommendations to {output_path}")
        return output


def run_learning_cycle():
    """Run a full learning cycle - call this periodically."""
    engine = LearningEngine()

    # Process last 24 hours of fast sales
    results = engine.process_fast_sales(hours_back=24)

    # Export recommendations
    recommendations = engine.export_ubf_recommendations()

    print(f"\n{'='*60}")
    print("LEARNING CYCLE COMPLETE")
    print(f"{'='*60}")
    print(f"Processed: {results['processed']} fast sales")
    print(f"By category: {dict(results['by_category'])}")

    if results["opportunity_patterns"]:
        print(f"\nTop Missed Opportunities:")
        for opp in sorted(results["opportunity_patterns"], key=lambda x: x["opp_score"], reverse=True)[:5]:
            print(f"  {opp['category']} | ${opp['price']:.0f} | Score: {opp['opp_score']:.0f} | {opp['signals']}")
            print(f"    {opp['title']}")

    if results["recommendations"]["sellers_to_watch"]:
        print(f"\nSellers to Watch:")
        for s in results["recommendations"]["sellers_to_watch"][:5]:
            print(f"  {s['seller']} ({s['category']}): {s['fast_sales']} fast sales")

    return results


def learn_from_historical_transactions(csv_path: str = None) -> Dict[str, Any]:
    """
    Learn from historical transaction data (matched_transactions.csv).

    This analyzes actual purchase outcomes (profit/loss) to:
    1. Identify winning patterns
    2. Identify losing patterns
    3. Update keyword performance with real profit data
    4. Update seller scores with real outcomes
    """
    import csv
    from collections import defaultdict

    if csv_path is None:
        csv_path = Path(__file__).parent.parent / "matched_transactions.csv"

    results = {
        "total_transactions": 0,
        "winners": 0,
        "losers": 0,
        "by_category": defaultdict(lambda: {"count": 0, "profit": 0, "winners": 0, "losers": 0}),
        "winning_patterns": [],
        "losing_patterns": [],
        "seller_performance": defaultdict(lambda: {"count": 0, "profit": 0, "win_rate": 0}),
        "keyword_performance": defaultdict(lambda: {"count": 0, "profit": 0, "win_rate": 0}),
    }

    if not Path(csv_path).exists():
        logger.warning(f"[LEARNING] Historical data not found: {csv_path}")
        return results

    # Category mapping
    category_map = {
        'Gold': 'gold',
        'Silver': 'silver',
        'Watch': 'watch',
        'Other': 'costume',
    }

    # Keywords to track
    keywords_to_track = [
        # Gold
        "solid gold", "wedding band", "class ring", "signet", "gold bracelet",
        "14k", "18k", "10k", "michael anthony", "italian", "milor",
        # Silver
        "sterling cuff", "turquoise", "navajo", "taxco", "mexico", "georg jensen",
        "squash blossom", "sterling necklace", "james avery", "dead pawn",
        # Watch
        "for repair", "for parts", "not working", "omega", "rolex", "breitling",
        "cartier", "pocket watch", "lecoultre",
        # Costume
        "jelly belly", "trifari", "crown trifari", "alfred philippe",
    ]

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                cost = float(row['Cost']) if row['Cost'] else 0
                sold = float(row['Sold']) if row['Sold'] else 0
                profit = float(row['Profit']) if row['Profit'] else 0
                roi = float(row['ROI %']) if row['ROI %'] else 0
                seller = row.get('Seller', '').strip().lower()
                title = row.get('Purchase Title', '').lower()
                category_raw = row.get('Category', 'Other')
                category = category_map.get(category_raw, 'other')

                if cost <= 0:
                    continue

                results["total_transactions"] += 1
                is_winner = roi >= 50
                is_loser = roi < 0

                if is_winner:
                    results["winners"] += 1
                if is_loser:
                    results["losers"] += 1

                # Update category stats
                results["by_category"][category]["count"] += 1
                results["by_category"][category]["profit"] += profit
                if is_winner:
                    results["by_category"][category]["winners"] += 1
                if is_loser:
                    results["by_category"][category]["losers"] += 1

                # Update seller performance
                if seller:
                    results["seller_performance"][seller]["count"] += 1
                    results["seller_performance"][seller]["profit"] += profit
                    if is_winner:
                        results["seller_performance"][seller]["win_rate"] += 1

                # Update keyword performance
                for kw in keywords_to_track:
                    if kw in title:
                        results["keyword_performance"][kw]["count"] += 1
                        results["keyword_performance"][kw]["profit"] += profit
                        if is_winner:
                            results["keyword_performance"][kw]["win_rate"] += 1

                # Track winning/losing patterns
                if roi >= 150:  # Big winner
                    results["winning_patterns"].append({
                        "title": title[:60],
                        "category": category,
                        "cost": cost,
                        "profit": profit,
                        "roi": roi,
                    })
                elif roi < -20:  # Significant loss
                    results["losing_patterns"].append({
                        "title": title[:60],
                        "category": category,
                        "cost": cost,
                        "profit": profit,
                        "roi": roi,
                    })

            except (ValueError, KeyError) as e:
                continue

    # Calculate win rates
    for seller, data in results["seller_performance"].items():
        if data["count"] > 0:
            data["win_rate"] = data["win_rate"] / data["count"]

    for kw, data in results["keyword_performance"].items():
        if data["count"] > 0:
            data["win_rate"] = data["win_rate"] / data["count"]

    # Sort patterns by ROI
    results["winning_patterns"].sort(key=lambda x: -x["roi"])
    results["losing_patterns"].sort(key=lambda x: x["roi"])

    logger.info(f"[LEARNING] Processed {results['total_transactions']} historical transactions")
    logger.info(f"[LEARNING] Winners: {results['winners']}, Losers: {results['losers']}")

    return results


def print_historical_learning_report(results: Dict[str, Any]):
    """Print a formatted report of historical learning results."""
    print("\n" + "=" * 70)
    print("HISTORICAL TRANSACTION LEARNING REPORT")
    print("=" * 70)

    print(f"\nTotal Transactions: {results['total_transactions']}")
    print(f"Winners (50%+ ROI): {results['winners']} ({results['winners']/results['total_transactions']*100:.1f}%)")
    print(f"Losers (<0% ROI): {results['losers']} ({results['losers']/results['total_transactions']*100:.1f}%)")

    print("\n--- BY CATEGORY ---")
    for cat, data in sorted(results["by_category"].items(), key=lambda x: -x[1]["profit"]):
        win_rate = data["winners"] / data["count"] * 100 if data["count"] > 0 else 0
        print(f"  {cat}: {data['count']} tx, ${data['profit']:.0f} profit, {win_rate:.0f}% win rate")

    print("\n--- TOP KEYWORDS BY WIN RATE (5+ occurrences) ---")
    keyword_list = [(kw, d) for kw, d in results["keyword_performance"].items() if d["count"] >= 5]
    keyword_list.sort(key=lambda x: -x[1]["win_rate"])
    for kw, data in keyword_list[:15]:
        print(f"  '{kw}': {data['win_rate']*100:.0f}% win rate ({data['count']} tx, ${data['profit']:.0f} profit)")

    print("\n--- TOP SELLERS BY WIN RATE (3+ transactions) ---")
    seller_list = [(s, d) for s, d in results["seller_performance"].items() if d["count"] >= 3]
    seller_list.sort(key=lambda x: -x[1]["win_rate"])
    for seller, data in seller_list[:10]:
        print(f"  {seller}: {data['win_rate']*100:.0f}% win rate ({data['count']} tx, ${data['profit']:.0f} profit)")

    print("\n--- BIGGEST WINNERS ---")
    for pattern in results["winning_patterns"][:10]:
        print(f"  {pattern['roi']:.0f}% ROI | ${pattern['cost']:.0f} -> ${pattern['cost']+pattern['profit']:.0f} | {pattern['title']}")

    print("\n--- BIGGEST LOSERS ---")
    for pattern in results["losing_patterns"][:5]:
        print(f"  {pattern['roi']:.0f}% ROI | ${pattern['cost']:.0f} -> ${pattern['cost']+pattern['profit']:.0f} | {pattern['title']}")


if __name__ == "__main__":
    # Run standard learning cycle
    run_learning_cycle()

    # Also learn from historical transactions if available
    print("\n" + "=" * 70)
    print("LEARNING FROM HISTORICAL TRANSACTIONS")
    print("=" * 70)
    historical_results = learn_from_historical_transactions()
    if historical_results["total_transactions"] > 0:
        print_historical_learning_report(historical_results)
