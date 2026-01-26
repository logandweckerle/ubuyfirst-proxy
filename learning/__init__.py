"""
Learning System for ClaudeProxyV3

This module builds category-specific valuation models from:
1. Fast sales data (items that sold in < 5 min = proven deals)
2. Purchase history (items we bought and their outcomes)
3. Missed opportunities (items we passed that sold fast)

Each category gets its own:
- Valuation rules (concrete, testable)
- Seller signals (who has deals in this category)
- Keyword effectiveness (what to search for)
- Agent prompts (category-specific AI instructions)
"""

from .category_models import CategoryModel, GoldModel, SilverModel, WatchModel
from .learning_engine import LearningEngine
from .keyword_optimizer import KeywordOptimizer

__all__ = [
    'CategoryModel',
    'GoldModel',
    'SilverModel',
    'WatchModel',
    'LearningEngine',
    'KeywordOptimizer',
]
