"""
Run Learning System

Master script to:
1. Process fast sales data
2. Update category models
3. Generate keyword recommendations
4. Export actionable insights for uBuyFirst
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from learning.learning_engine import LearningEngine, run_learning_cycle
from learning.keyword_optimizer import KeywordOptimizer, run_keyword_optimization
from learning.category_models import get_all_models


def main():
    print("=" * 70)
    print("CLAUDE PROXY LEARNING SYSTEM")
    print("=" * 70)

    # 1. Run learning cycle - process fast sales
    print("\n[1/4] Processing Fast Sales...")
    engine = LearningEngine()
    learning_results = engine.process_fast_sales(hours_back=168)  # Last week

    print(f"   Processed: {learning_results['processed']} fast sales")
    print(f"   By category: {dict(learning_results['by_category'])}")

    # 2. Generate keyword recommendations
    print("\n[2/4] Analyzing Keywords...")
    optimizer = KeywordOptimizer()
    keyword_analysis = optimizer.analyze_all_keywords()

    for category, data in keyword_analysis["by_category"].items():
        print(f"\n   {category.upper()}:")
        print(f"   - Fast-selling keywords: {len(data['fast_sale_keywords'])}")
        print(f"   - Missed opportunity keywords: {len(data['missed_opportunity_keywords'])}")
        if data['missed_opportunity_keywords']:
            top = data['missed_opportunity_keywords'][0]
            print(f"   - Top missed: '{top['keyword']}' ({top['passed_count']} deals missed)")

    # 3. Export recommendations
    print("\n[3/4] Exporting Recommendations...")
    report = optimizer.generate_ubf_export()
    print("   Saved to: keyword_recommendations.txt")

    ubf_recs = engine.export_ubf_recommendations()
    print("   Saved to: ubf_recommendations.json")

    # 4. Show instant PASS suggestions
    print("\n[4/4] Checking Noise Patterns...")
    pass_suggestions = optimizer.get_instant_pass_suggestions()
    if pass_suggestions:
        print("   Keywords that should be instant PASS:")
        for s in pass_suggestions[:10]:
            print(f"   - '{s['keyword']}': {s['pass_rate']*100:.0f}% pass rate")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY - ACTIONABLE ITEMS")
    print("=" * 70)

    # Top missed opportunity patterns
    if learning_results.get("opportunity_patterns"):
        print("\n[MISSED OPPORTUNITIES] - Items we passed that sold fast:")
        for opp in sorted(learning_results["opportunity_patterns"],
                          key=lambda x: x.get("opp_score", 0), reverse=True)[:5]:
            print(f"   ${opp['price']:.0f} | {opp['category']} | Score: {opp['opp_score']:.0f}")
            print(f"   Signals: {opp['signals']}")
            print(f"   {opp['title']}")

    # Sellers to watch
    if learning_results.get("recommendations", {}).get("sellers_to_watch"):
        print("\n[SELLERS TO WATCH] - Multiple fast sales:")
        for s in learning_results["recommendations"]["sellers_to_watch"][:5]:
            print(f"   {s['seller']} ({s['category']}): {s['fast_sales']} fast sales")

    # High priority keyword additions
    high_priority = [rec for rec in keyword_analysis["global_recommendations"]["add_keywords"]
                     if rec.get("priority") == "high"]
    if high_priority:
        print("\n[HIGH PRIORITY KEYWORD ADDITIONS]:")
        for rec in high_priority[:5]:
            print(f"   {rec['category']}: '{rec['keyword']}'")
            print(f"      Reason: {rec['reason']}")

    print("\n" + "=" * 70)
    print("CATEGORY MODEL SIGNALS")
    print("=" * 70)

    models = get_all_models()
    for category, model in models.items():
        print(f"\n{category.upper()} - Opportunity Signals:")
        for signal in model.opportunity_signals[:3]:
            print(f"   [{signal.weight:.0%}] {signal.name}")
            print(f"         {signal.description}")

    print("\n" + "=" * 70)
    print("FILES GENERATED:")
    print("=" * 70)
    print("   keyword_recommendations.txt - Human readable keyword report")
    print("   ubf_recommendations.json    - Machine readable recommendations")
    print("   learning_data.db            - Learned patterns and scores")
    print("\nReview these files and update uBuyFirst accordingly!")


if __name__ == "__main__":
    main()
