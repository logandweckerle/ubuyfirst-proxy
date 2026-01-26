"""
Keyword Optimizer

Analyzes fast sales and missed opportunities to generate
actionable keyword recommendations for uBuyFirst.

Outputs:
1. Keywords to ADD (high opportunity rate)
2. Keywords to REMOVE (noise generators)
3. Filter suggestions (title keyword filters)
4. Category coverage gaps
"""

import sqlite3
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any
import logging

from .category_models import LEARNING_DB, TRACKING_DB, get_all_models

logger = logging.getLogger(__name__)


class KeywordOptimizer:
    """Optimizes keywords for uBuyFirst based on learning data."""

    def __init__(self):
        self.models = get_all_models()

    def analyze_all_keywords(self) -> Dict[str, Any]:
        """
        Comprehensive keyword analysis across all data sources.

        Analyzes:
        1. Fast sales - what keywords appear in items that sell quickly
        2. BUY signals - what keywords lead to profitable buys
        3. PASS signals - what keywords lead to correct passes
        4. Missed opportunities - keywords we should have caught
        """
        results = {
            "generated_at": datetime.now().isoformat(),
            "by_category": {},
            "global_recommendations": {
                "add_keywords": [],
                "remove_keywords": [],
                "filter_rules": [],
            }
        }

        # Analyze each category
        for category in ["gold", "silver", "watch"]:
            results["by_category"][category] = self._analyze_category(category)

        # Generate global recommendations
        self._generate_global_recommendations(results)

        return results

    def _analyze_category(self, category: str) -> Dict[str, Any]:
        """Analyze keywords for a specific category."""

        conn = sqlite3.connect(TRACKING_DB)
        cursor = conn.cursor()

        cat_results = {
            "fast_sale_keywords": [],
            "missed_opportunity_keywords": [],
            "noise_keywords": [],
            "recommended_additions": [],
            "recommended_removals": [],
        }

        # Get all fast sales in this category
        cursor.execute("""
            SELECT title, price, recommendation, time_to_sell_minutes, seller_name
            FROM tracked_items
            WHERE is_fast_sale = 1
            AND category = ?
        """, (category,))

        fast_sales = cursor.fetchall()

        # Keyword frequency in fast sales
        keyword_freq = defaultdict(lambda: {"total": 0, "passed": 0, "bought": 0, "prices": []})

        # Category-specific keywords to look for
        keyword_patterns = self._get_keyword_patterns(category)

        for sale in fast_sales:
            title = (sale[0] or "").lower().replace("+", " ")
            price_str = str(sale[1] or "0").replace("$", "").replace(",", "")
            try:
                price = float(price_str)
            except:
                price = 0
            recommendation = (sale[2] or "").upper()
            seller = (sale[4] or "").lower()

            for kw in keyword_patterns:
                if kw in title:
                    keyword_freq[kw]["total"] += 1
                    keyword_freq[kw]["prices"].append(price)

                    if "PASS" in recommendation:
                        keyword_freq[kw]["passed"] += 1
                    elif "BUY" in recommendation:
                        keyword_freq[kw]["bought"] += 1

        conn.close()

        # Analyze keyword performance
        for kw, data in keyword_freq.items():
            if data["total"] < 2:
                continue

            avg_price = sum(data["prices"]) / len(data["prices"]) if data["prices"] else 0
            miss_rate = data["passed"] / data["total"] if data["total"] > 0 else 0

            kw_info = {
                "keyword": kw,
                "total_fast_sales": data["total"],
                "passed_count": data["passed"],
                "bought_count": data["bought"],
                "miss_rate": miss_rate,
                "avg_price": avg_price,
            }

            cat_results["fast_sale_keywords"].append(kw_info)

            # High miss rate = we're passing on good deals
            if miss_rate > 0.5 and data["passed"] >= 2:
                cat_results["missed_opportunity_keywords"].append(kw_info)
                cat_results["recommended_additions"].append({
                    "keyword": kw,
                    "reason": f"Missing {data['passed']} deals (miss rate {miss_rate*100:.0f}%)",
                    "priority": "high" if miss_rate > 0.7 else "medium",
                })

        # Sort by total fast sales
        cat_results["fast_sale_keywords"].sort(key=lambda x: x["total_fast_sales"], reverse=True)

        # Add model's priority keywords that aren't being searched
        model = self.models.get(category)
        if model:
            searched_keywords = set(kw["keyword"] for kw in cat_results["fast_sale_keywords"])
            for priority_kw in model.priority_keywords:
                if priority_kw not in searched_keywords:
                    cat_results["recommended_additions"].append({
                        "keyword": priority_kw,
                        "reason": "Model priority keyword - not yet seeing in searches",
                        "priority": "medium",
                    })

        return cat_results

    def _get_keyword_patterns(self, category: str) -> List[str]:
        """Get keywords to track for a category."""
        patterns = {
            "gold": [
                # Karats
                "24k", "22k", "18k", "14k", "10k", "9k",
                "999", "916", "750", "585", "417", "375",
                # Terms
                "scrap", "lot", "grams", "gram", "dwt", "troy",
                "broken", "as is", "for parts", "melt",
                "chain", "bracelet", "ring", "necklace", "pendant", "earring",
                "estate", "vintage", "antique", "vtg",
                # Brands
                "michael anthony", "italy", "italian", "milor",
                "class ring", "signet", "nugget",
                "dental", "tooth", "teeth",
            ],
            "silver": [
                # Purity
                "925", "sterling", "800", "900", "950", "coin silver",
                # Terms
                "scrap", "lot", "grams", "troy", "melt",
                "flatware", "serving", "ladle", "fork", "spoon", "knife",
                "bowl", "tray", "compote", "pitcher", "tea set",
                "estate", "vintage", "antique",
                # Makers
                "gorham", "towle", "wallace", "reed barton", "kirk", "international",
                # Origins
                "mexican", "mexico", "taxco", "navajo", "native",
                # Types
                "bracelet", "necklace", "ring", "earring", "brooch",
            ],
            "watch": [
                # Case material
                "14k", "18k", "10k", "gold", "solid gold",
                "coin silver", "silver", "platinum",
                # Condition
                "parts", "repair", "not working", "broken", "as is", "project",
                "lot", "watchmaker", "horologist",
                # Types
                "pocket", "pocket watch", "wrist", "vintage", "antique",
                # Brands
                "waltham", "elgin", "hamilton", "howard", "illinois", "ball",
                "omega", "longines", "bulova", "gruen", "wittnauer",
                "rolex", "tudor", "breitling",
                # Special
                "railroad", "railway", "hunter", "open face",
            ],
        }

        return patterns.get(category, [])

    def _generate_global_recommendations(self, results: Dict):
        """Generate global recommendations across all categories."""

        all_additions = []
        all_removals = []

        for category, data in results["by_category"].items():
            for rec in data.get("recommended_additions", []):
                rec["category"] = category
                all_additions.append(rec)

            for rec in data.get("recommended_removals", []):
                rec["category"] = category
                all_removals.append(rec)

        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        all_additions.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))

        results["global_recommendations"]["add_keywords"] = all_additions[:30]
        results["global_recommendations"]["remove_keywords"] = all_removals[:20]

    def generate_ubf_export(self) -> str:
        """
        Generate a formatted export for uBuyFirst configuration.

        Returns a text report that can be copy/pasted into uBuyFirst settings.
        """
        analysis = self.analyze_all_keywords()

        lines = []
        lines.append("=" * 60)
        lines.append("KEYWORD RECOMMENDATIONS FOR UBUYFIRST")
        lines.append(f"Generated: {analysis['generated_at']}")
        lines.append("=" * 60)

        for category, data in analysis["by_category"].items():
            lines.append(f"\n{'='*40}")
            lines.append(f"{category.upper()} CATEGORY")
            lines.append("=" * 40)

            lines.append("\n--- TOP FAST-SELLING KEYWORDS ---")
            for kw in data["fast_sale_keywords"][:15]:
                miss = kw["miss_rate"] * 100
                lines.append(f"  '{kw['keyword']}': {kw['total_fast_sales']} fast sales | "
                            f"Miss rate: {miss:.0f}% | Avg: ${kw['avg_price']:.0f}")

            if data["missed_opportunity_keywords"]:
                lines.append("\n--- MISSED OPPORTUNITY KEYWORDS (add these!) ---")
                for kw in data["missed_opportunity_keywords"][:10]:
                    lines.append(f"  '{kw['keyword']}': {kw['passed_count']} deals missed | "
                                f"Miss rate: {kw['miss_rate']*100:.0f}%")

            if data["recommended_additions"]:
                lines.append("\n--- RECOMMENDED ADDITIONS ---")
                for rec in data["recommended_additions"][:10]:
                    lines.append(f"  [{rec['priority'].upper()}] {rec['keyword']}")
                    lines.append(f"       Reason: {rec['reason']}")

        lines.append("\n" + "=" * 60)
        lines.append("GLOBAL RECOMMENDATIONS")
        lines.append("=" * 60)

        if analysis["global_recommendations"]["add_keywords"]:
            lines.append("\n--- HIGH PRIORITY ADDITIONS ---")
            for rec in analysis["global_recommendations"]["add_keywords"][:15]:
                if rec.get("priority") == "high":
                    lines.append(f"  {rec['category']}: '{rec['keyword']}' - {rec['reason']}")

        report = "\n".join(lines)

        # Save to file
        output_path = Path(__file__).parent.parent / "keyword_recommendations.txt"
        with open(output_path, "w") as f:
            f.write(report)

        logger.info(f"[KEYWORDS] Recommendations saved to {output_path}")
        return report

    def get_instant_pass_suggestions(self) -> List[Dict]:
        """
        Get suggestions for new instant PASS rules based on noise patterns.

        Looks for keywords that:
        1. Appear frequently
        2. Almost never lead to BUY
        3. Generate PASS consistently
        """
        conn = sqlite3.connect(TRACKING_DB)
        cursor = conn.cursor()

        # Find keywords that are all PASS
        cursor.execute("""
            SELECT title, category, recommendation
            FROM tracked_items
            WHERE recommendation IS NOT NULL
            AND category IN ('gold', 'silver', 'watch')
            ORDER BY first_seen DESC
            LIMIT 5000
        """)

        # Track keywords and their pass rates
        keyword_outcomes = defaultdict(lambda: {"pass": 0, "buy": 0, "total": 0})

        noise_patterns = [
            "gold tone", "gold plated", "silver tone", "silver plated",
            "costume", "fashion", "stainless", "brass", "pewter",
            "replated", "electroplate", "epns", "wm rogers",
            "seed bead", "wooden bead", "shell", "bone",
            "smartwatch", "fitbit", "apple watch",
            "michael kors", "fossil", "guess", "invicta",
            "pandora", "james avery", "tiffany style",
        ]

        for row in cursor.fetchall():
            title = (row[0] or "").lower().replace("+", " ")
            rec = (row[2] or "").upper()

            for pattern in noise_patterns:
                if pattern in title:
                    keyword_outcomes[pattern]["total"] += 1
                    if "PASS" in rec:
                        keyword_outcomes[pattern]["pass"] += 1
                    elif "BUY" in rec:
                        keyword_outcomes[pattern]["buy"] += 1

        conn.close()

        # Find patterns with high PASS rate
        suggestions = []
        for kw, data in keyword_outcomes.items():
            if data["total"] >= 5:
                pass_rate = data["pass"] / data["total"] if data["total"] > 0 else 0
                if pass_rate > 0.9:
                    suggestions.append({
                        "keyword": kw,
                        "pass_rate": pass_rate,
                        "total_seen": data["total"],
                        "suggestion": f"Add to instant PASS filter ({pass_rate*100:.0f}% pass rate)",
                    })

        suggestions.sort(key=lambda x: x["total_seen"], reverse=True)
        return suggestions


def run_keyword_optimization():
    """Run keyword optimization and print report."""
    optimizer = KeywordOptimizer()
    report = optimizer.generate_ubf_export()
    print(report)

    print("\n" + "=" * 60)
    print("INSTANT PASS SUGGESTIONS")
    print("=" * 60)
    suggestions = optimizer.get_instant_pass_suggestions()
    for s in suggestions[:15]:
        print(f"  '{s['keyword']}': {s['pass_rate']*100:.0f}% pass rate ({s['total_seen']} seen)")

    return report


if __name__ == "__main__":
    run_keyword_optimization()
