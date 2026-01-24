"""
Pipeline Module - Tiered Analysis System

This module organizes the analysis pipeline into discrete stages:
- Tier 0: Rule-based fast filtering (no AI cost)
- Tier 1: Cheap AI assessment (GPT-4o-mini, Gemini Flash)
- Tier 2: Premium verification (GPT-4o, Claude Sonnet)
- Orchestrator: Coordinates the full pipeline

Usage:
    from pipeline.orchestrator import run_analysis, configure_orchestrator
"""

from .tier0 import Tier0Filter
from .tier1 import Tier1Analyzer
from .tier2 import (
    configure_tier2,
    background_sonnet_verify,
    tier2_reanalyze,
    tier2_reanalyze_openai,
)
from .orchestrator import configure_orchestrator, run_analysis

__all__ = [
    'Tier0Filter',
    'Tier1Analyzer',
    'configure_tier2',
    'background_sonnet_verify',
    'tier2_reanalyze',
    'tier2_reanalyze_openai',
    'configure_orchestrator',
    'run_analysis',
]
