"""
Tier 2: Premium Verification

Second-pass verification using premium models.
Only runs for BUY and RESEARCH recommendations from Tier 1.

Goal: Verify Tier 1 decisions with higher accuracy model.
Catches false positives before they become costly mistakes.

Models used:
- GPT-4o (default, good at image analysis)
- Claude Sonnet (alternative, strong reasoning)

Cost: ~$0.03-0.05 per call
Latency: 3-5 seconds
"""

import json
import re
import logging
import time as _time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ============================================================
# TIER 2 CONFIGURATION - Set by main.py at startup
# ============================================================
class Tier2Config:
    """Configuration container for Tier 2 verification"""
    TIER2_ENABLED: bool = True
    TIER2_PROVIDER: str = "openai"  # "openai" or "claude"
    MODEL_FULL: str = "claude-3-5-sonnet-20241022"
    OPENAI_TIER2_MODEL: str = "gpt-4o"
    DISCORD_WEBHOOK_URL: str = ""
    COST_PER_CALL_SONNET: float = 0.03
    COST_PER_CALL_OPENAI: float = 0.02
    COST_PER_CALL_GPT4O: float = 0.05

    # Clients - set at runtime
    anthropic_client = None
    openai_client = None

    # Stats dict reference - set at runtime
    STATS: Dict = {}

    # Image config
    resize_for_tier2: int = 1024

    # Helper functions - set at runtime
    process_image_list = None
    get_agent_prompt = None
    send_discord_alert = None
    log_training_override = None
    get_spot_prices = None
    check_openai_budget = None
    record_openai_cost = None
    validate_and_fix_margin = None


# Global config instance
config = Tier2Config()


def configure_tier2(
    tier2_enabled: bool,
    tier2_provider: str,
    model_full: str,
    openai_tier2_model: str,
    discord_webhook_url: str,
    anthropic_client,
    openai_client,
    stats: Dict,
    cost_per_call_sonnet: float,
    cost_per_call_openai: float,
    cost_per_call_gpt4o: float,
    resize_for_tier2: int,
    process_image_list,
    get_agent_prompt,
    send_discord_alert,
    log_training_override,
    get_spot_prices,
    check_openai_budget,
    record_openai_cost,
    validate_and_fix_margin,
):
    """Configure Tier 2 module with dependencies from main.py"""
    config.TIER2_ENABLED = tier2_enabled
    config.TIER2_PROVIDER = tier2_provider
    config.MODEL_FULL = model_full
    config.OPENAI_TIER2_MODEL = openai_tier2_model
    config.DISCORD_WEBHOOK_URL = discord_webhook_url
    config.anthropic_client = anthropic_client
    config.openai_client = openai_client
    config.STATS = stats
    config.COST_PER_CALL_SONNET = cost_per_call_sonnet
    config.COST_PER_CALL_OPENAI = cost_per_call_openai
    config.COST_PER_CALL_GPT4O = cost_per_call_gpt4o
    config.resize_for_tier2 = resize_for_tier2
    config.process_image_list = process_image_list
    config.get_agent_prompt = get_agent_prompt
    config.send_discord_alert = send_discord_alert
    config.log_training_override = log_training_override
    config.get_spot_prices = get_spot_prices
    config.check_openai_budget = check_openai_budget
    config.record_openai_cost = record_openai_cost
    config.validate_and_fix_margin = validate_and_fix_margin

    logger.info(f"[TIER2] Configured: provider={tier2_provider}, enabled={tier2_enabled}")


# ============================================================
# BACKGROUND SONNET VERIFY
# ============================================================
async def background_sonnet_verify(
    title: str,
    price: float,
    category: str,
    haiku_result: dict,
    raw_image_urls: list,
    data: dict,
    fast_result=None
):
    """
    Run Sonnet verification in background.
    If Sonnet disagrees with Haiku's BUY recommendation, send Discord alert.
    """
    try:
        haiku_rec = haiku_result.get('Recommendation', 'RESEARCH')
        logger.info(f"[PARALLEL] Background Sonnet starting for: {title[:50]}...")
        logger.info(f"[PARALLEL] Tier1 said: {haiku_rec}")

        _start = _time.time()

        # Fetch images for Sonnet
        images = []
        if raw_image_urls and config.process_image_list:
            images = await config.process_image_list(
                raw_image_urls,
                max_size=config.resize_for_tier2,
                selection="first_last"
            )
            logger.info(f"[PARALLEL] Fetched {len(images)} images for Sonnet")

        # Run Sonnet analysis
        if config.TIER2_PROVIDER == "openai" and config.openai_client:
            sonnet_result = await tier2_reanalyze_openai(
                title=title,
                price=price,
                category=category,
                tier1_result=haiku_result.copy(),
                images=images,
                data=data,
                system_prompt=config.get_agent_prompt(category) if config.get_agent_prompt else ""
            )
        else:
            sonnet_result = await tier2_reanalyze(
                title=title,
                price=price,
                category=category,
                tier1_result=haiku_result.copy(),
                images=images,
                data=data,
                system_prompt=config.get_agent_prompt(category) if config.get_agent_prompt else ""
            )

        sonnet_rec = sonnet_result.get('Recommendation', 'RESEARCH')
        _elapsed = _time.time() - _start
        logger.info(f"[PARALLEL] Sonnet completed in {_elapsed:.1f}s: {sonnet_rec}")

        # Determine if we should alert
        should_alert = False
        alert_reason = ""

        # SIMPLE RULE: If Sonnet says BUY, send alert
        if sonnet_rec == 'BUY':
            should_alert = True
            if haiku_rec == 'BUY':
                alert_reason = "CONFIRMED BUY"
                logger.info(f"[PARALLEL] Sonnet CONFIRMS Tier1's BUY!")
            else:
                alert_reason = "SONNET FOUND BUY"
                logger.info(f"[PARALLEL] Sonnet upgraded {haiku_rec} to BUY!")

        # Also alert if Tier1 said BUY but Sonnet disagrees (warning)
        elif haiku_rec == 'BUY' and sonnet_rec == 'PASS':
            should_alert = True
            alert_reason = "SONNET OVERRIDE: PASS"
            logger.warning(f"[PARALLEL] Sonnet says PASS - Tier1 was wrong!")

        # Log but don't alert for RESEARCH outcomes
        elif sonnet_rec == 'RESEARCH':
            logger.info(f"[PARALLEL] Sonnet says RESEARCH - no Discord alert (verify manually in UI)")

        # Send Discord alert if warranted
        if should_alert and config.DISCORD_WEBHOOK_URL and config.send_discord_alert:
            # Get profit from Sonnet result
            profit = None
            try:
                profit_str = sonnet_result.get('Profit', sonnet_result.get('Margin', '0'))
                profit = float(str(profit_str).replace('$', '').replace('+', '').replace(',', ''))
            except:
                pass

            # Get first image URL for thumbnail
            first_image = None
            if raw_image_urls:
                first_img = raw_image_urls[0]
                if isinstance(first_img, str) and first_img.startswith('http'):
                    first_image = first_img

            # Build eBay URL
            ebay_url = data.get('ViewUrl', data.get('CheckoutUrl', ''))
            if not ebay_url:
                item_id = data.get('ItemId', data.get('itemId', ''))
                if item_id:
                    ebay_url = f"https://www.ebay.com/itm/{item_id}"

            # Extra data for the alert
            extra = {
                'karat': sonnet_result.get('karat'),
                'weight': sonnet_result.get('goldweight', sonnet_result.get('silverweight', sonnet_result.get('weight'))),
                'melt': sonnet_result.get('meltvalue'),
            }

            # Add alert reason to reasoning
            reasoning = f"{alert_reason}\n\nTier1: {haiku_rec} -> Sonnet: {sonnet_rec}\n\n{sonnet_result.get('reasoning', '')}"

            await config.send_discord_alert(
                title=title,
                price=price,
                recommendation=sonnet_rec,
                category=category,
                profit=profit,
                reasoning=reasoning[:800],
                ebay_url=ebay_url,
                image_url=first_image,
                confidence=str(sonnet_result.get('confidence', 'N/A')),
                extra_data=extra
            )

    except Exception as e:
        logger.error(f"[PARALLEL] Background Sonnet error: {e}")
        import traceback
        traceback.print_exc()


# ============================================================
# TIER 2 RE-ANALYSIS (Sonnet for BUY/RESEARCH)
# ============================================================
async def tier2_reanalyze(
    title: str,
    price: float,
    category: str,
    tier1_result: Dict,
    images: List,
    data: Dict,
    system_prompt: str
) -> Dict:
    """
    Re-analyze a BUY/RESEARCH listing with Sonnet for higher accuracy.
    Returns updated result dict with tier2 fields.

    KEY RULE: ALL potential BUYs must be verified by Sonnet before being shown to user.
    """
    if not config.TIER2_ENABLED:
        return tier1_result

    tier1_rec = tier1_result.get('Recommendation', 'RESEARCH')
    tier1_margin = 0

    # Extract margin from tier1 result
    try:
        margin_val = tier1_result.get('Profit', tier1_result.get('margin', tier1_result.get('Margin', '0')))
        if isinstance(margin_val, str):
            margin_val = margin_val.replace('$', '').replace(',', '').replace('%', '').replace('+', '')
        tier1_margin = float(margin_val) if margin_val else 0
    except:
        tier1_margin = 0

    # === ALWAYS RUN TIER 2 FOR BUY AND RESEARCH RECOMMENDATIONS ===
    if tier1_rec == 'BUY':
        logger.info(f"[TIER2] BUY detected - MANDATORY Sonnet verification")

    logger.info(f"[TIER2] Re-analyzing with Sonnet: {title[:50]}...")
    logger.info(f"[TIER2] Tier1 result: {tier1_rec} with ${tier1_margin:.2f} margin")

    try:
        # Build messages for Sonnet
        messages_content = []

        # Add images if available
        if images:
            for img in images[:5]:  # Max 5 images
                if isinstance(img, dict) and 'source' in img:
                    messages_content.append(img)
                elif isinstance(img, dict) and 'data' in img:
                    messages_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img.get('media_type', 'image/jpeg'),
                            "data": img['data']
                        }
                    })

        # Add tier1 context to the prompt
        # Build category-specific field requirements
        if category == 'gold':
            field_requirements = """
Return JSON with these EXACT fields:
- Recommendation: "BUY", "PASS", or "RESEARCH"
- Profit: number (maxBuy minus listingPrice, e.g., 15 or -20)
- confidence: number 0-100
- reasoning: your analysis
- karat: "10K", "14K", "18K", etc.
- goldweight: number (grams of gold after deductions)
- meltvalue: number (gold value in dollars)
- maxBuy: number (90% of melt - our ceiling)
- sellPrice: number (96% of melt - what refiner pays)
- tier2_override: true/false
- tier2_reason: why you agreed/disagreed"""
        elif category == 'silver':
            field_requirements = """
=== CRITICAL: TRUST STATED WEIGHT ===
If the TITLE contains a weight (e.g., "218 GRAMS", "500g", "1 lb"), USE THAT EXACT WEIGHT.
The seller has weighed this lot - do NOT reduce it based on guessing from photos.

OVERRIDE STATED WEIGHT ONLY IF:
- Title says "plated" or "EPNS" (not sterling at all)
- Photos clearly show it is NOT what title describes (wrong item)

DO NOT REDUCE WEIGHT FOR:
- "Souvenir spoons" - these are SOLID STERLING when marked sterling
- "Flatware lot" - solid pieces unless knives are included
- Multiple pieces in a lot - seller weighed them all together

=== STONE DEDUCTION (only if NO stated weight) ===
Only estimate and deduct stones if there is NO weight in the title:
- Small accent stones: 0.5-1g each
- Medium cabochons: 1-3g each
- Large stones: 3-6g each

=== YOUR JOB ===
Verify Tier 1's analysis:
1. Is this actually sterling (not plated)?
2. Did Tier 1 use the correct weight from title?
3. Is the math correct (weight x rate x 0.70)?

If Tier 1 used the stated weight correctly and item is sterling = CONFIRM THE BUY.

Return JSON with these EXACT fields:
- Recommendation: "BUY", "PASS", or "RESEARCH"
- Profit: number (maxBuy minus listingPrice, e.g., 15 or -20)
- confidence: number 0-100
- reasoning: State what weight you used and why
- itemtype: type of silver item
- weight: number (total weight in grams - USE STATED WEIGHT)
- stoneDeduction: number (0 if weight was stated in title)
- silverweight: number (silver weight after any deductions)
- meltvalue: number (silver value in dollars)
- maxBuy: number (75% of melt - our ceiling)
- sellPrice: number (82% of melt - what refiner pays)
- tier2_override: true/false
- tier2_reason: why you agreed/disagreed"""
        elif category == 'videogames':
            # Get PC data from tier1 result
            pc_match = tier1_result.get('pcMatch', 'No')
            pc_market = tier1_result.get('marketprice', 'Unknown')
            pc_product = tier1_result.get('pcProduct', 'Unknown')

            if pc_match == 'Yes' and pc_market and pc_market != 'Unknown' and pc_market != '0':
                try:
                    pc_market_float = float(str(pc_market).replace('$','').replace(',',''))
                    pc_maxbuy = pc_market_float * 0.70  # 70% for TCG/LEGO
                    pc_profit = pc_maxbuy - price
                except:
                    pc_market_float = 0
                    pc_maxbuy = 0
                    pc_profit = 0

                field_requirements = f"""
VERIFIED MARKET DATA (from PriceCharting - DO NOT CHANGE THESE):
- Product: {pc_product}
- Market Price: ${pc_market_float:.0f}
- Max Buy (70%): ${pc_maxbuy:.0f}
- Listing Price: ${price:.0f}
- Calculated Profit: ${pc_profit:.0f}

Your job is ONLY to verify:
1. Is this the correct game identification?
2. Is the condition assessment accurate (CIB/Loose/New)?
3. Are there any red flags in the images?

DO NOT change the market price or profit calculations - they come from verified sales data.

Return JSON with these EXACT fields:
- Recommendation: "{'BUY' if pc_profit > 0 else 'PASS'}" (based on verified profit of ${pc_profit:.0f})
- Profit: {pc_profit:.0f} (DO NOT CHANGE - from PriceCharting)
- marketprice: {pc_market_float:.0f} (DO NOT CHANGE - from PriceCharting)
- maxBuy: {pc_maxbuy:.0f} (DO NOT CHANGE - from PriceCharting)
- confidence: number 0-100 (your confidence in the ITEM IDENTIFICATION, not price)
- reasoning: your verification of item ID and condition
- condition: "CIB", "Loose", "New", etc.
- tier2_override: false (only true if you found a red flag)
- tier2_reason: "Verified item identification and condition" """
            else:
                field_requirements = """
WARNING: No verified market data available from PriceCharting.

Without verified pricing, you can ONLY recommend RESEARCH (not BUY).
Your job is to verify the item identification and condition, not guess market values.

Return JSON with these EXACT fields:
- Recommendation: "RESEARCH" (cannot be BUY without verified pricing)
- Profit: 0
- confidence: number 0-100
- reasoning: explain what you verified and why manual price research is needed
- marketprice: 0 (unknown - needs research)
- maxBuy: 0
- condition: "CIB", "Loose", "New", etc.
- tier2_override: true
- tier2_reason: "No verified market data - requires manual price research" """

        elif category in ['tcg', 'lego']:
            # Get PC data from tier1 result
            pc_match = tier1_result.get('pcMatch', 'No')
            pc_market = tier1_result.get('marketprice', 'Unknown')
            pc_product = tier1_result.get('pcProduct', 'Unknown')

            if pc_match == 'Yes' and pc_market and pc_market != 'Unknown' and pc_market != '0':
                try:
                    pc_market_float = float(str(pc_market).replace('$','').replace(',',''))
                    pc_maxbuy = pc_market_float * 0.70  # 70% for TCG/LEGO
                    pc_profit = pc_maxbuy - price
                except:
                    pc_market_float = 0
                    pc_maxbuy = 0
                    pc_profit = 0

                field_requirements = f"""
VERIFIED MARKET DATA (from PriceCharting - DO NOT CHANGE THESE):
- Product: {pc_product}
- Market Price: ${pc_market_float:.0f}
- Max Buy (70%): ${pc_maxbuy:.0f}
- Listing Price: ${price:.0f}
- Calculated Profit: ${pc_profit:.0f}

Your job is ONLY to verify:
1. Is this the correct product identification?
2. Is the condition/sealed status accurate?
3. Are there any red flags in the images?

DO NOT change the market price or profit calculations - they come from verified sales data.

Return JSON with these EXACT fields:
- Recommendation: "{'BUY' if pc_profit > 0 else 'PASS'}" (based on verified profit of ${pc_profit:.0f})
- Profit: {pc_profit:.0f} (DO NOT CHANGE - from PriceCharting)
- marketprice: {pc_market_float:.0f} (DO NOT CHANGE - from PriceCharting)
- maxBuy: {pc_maxbuy:.0f} (DO NOT CHANGE - from PriceCharting)
- confidence: number 0-100 (your confidence in the ITEM IDENTIFICATION, not price)
- reasoning: your verification of item ID and condition
- tier2_override: false (only true if you found a red flag)
- tier2_reason: "Verified item identification and condition" """
            else:
                field_requirements = """
WARNING: No verified market data available from PriceCharting.

Without verified pricing, you can ONLY recommend RESEARCH (not BUY).
Your job is to verify the item identification and condition, not guess market values.

Return JSON with these EXACT fields:
- Recommendation: "RESEARCH" (cannot be BUY without verified pricing)
- Profit: 0
- confidence: number 0-100
- reasoning: explain what you verified and why manual price research is needed
- marketprice: 0 (unknown - needs research)
- maxBuy: 0
- tier2_override: true
- tier2_reason: "No verified market data - requires manual price research" """
        else:
            field_requirements = """
Return JSON with these EXACT fields:
- Recommendation: "BUY", "PASS", or "RESEARCH"
- Profit: number (e.g., 15 or -20)
- confidence: number 0-100
- reasoning: your analysis
- tier2_override: true/false
- tier2_reason: why you agreed/disagreed"""

        tier2_prompt = f"""TIER 2 VERIFICATION - You are the FINAL decision maker. Your values will be displayed.

TIER 1 RESULT (to verify):
- Recommendation: {tier1_rec}
- Estimated Profit: ${tier1_margin:.2f}
- Reasoning: {tier1_result.get('reasoning', 'N/A')[:500]}

LISTING:
Title: {title}
Price: ${price:.2f}
Category: {category}

Verify the Tier 1 analysis:
1. Is the weight/quantity estimate accurate based on images?
2. Is the item identification correct?
3. Is the profit calculation reasonable?
4. Are there any red flags missed?

{field_requirements}

CRITICAL: Your Profit and other numeric fields will be displayed directly. Calculate them yourself - do not copy Tier 1's values."""

        messages_content.append({"type": "text", "text": tier2_prompt})

        # Call Sonnet
        response = await config.anthropic_client.messages.create(
            model=config.MODEL_FULL,
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": messages_content}]
        )

        # Track cost
        config.STATS["session_cost"] += config.COST_PER_CALL_SONNET
        config.STATS["api_calls"] += 1

        # Parse response
        raw_response = response.content[0].text
        logger.info(f"[TIER2] Sonnet response: {raw_response[:200]}...")

        # Extract JSON
        tier2_result = None
        try:
            if '```json' in raw_response:
                json_str = raw_response.split('```json')[1].split('```')[0].strip()
            elif '```' in raw_response:
                json_str = raw_response.split('```')[1].split('```')[0].strip()
            elif '{' in raw_response:
                start = raw_response.find('{')
                end = raw_response.rfind('}') + 1
                json_str = raw_response[start:end]
            else:
                json_str = raw_response

            tier2_result = json.loads(json_str)
        except:
            logger.warning(f"[TIER2] Failed to parse JSON, using Tier 1 result")
            tier1_result['tier2'] = 'parse_error'
            return tier1_result

        # Get Tier 2 recommendation
        tier2_rec = tier2_result.get('Recommendation', tier1_rec)
        tier2_override = tier2_result.get('tier2_override', False)

        # === TIER 2 REASONING SANITY CHECK ===
        tier2_reasoning = str(tier2_result.get('reasoning', '')).lower()

        negative_indicators = [
            'loss', 'negative margin', 'overpriced', 'too high', 'not worth',
            'fatal flaw', 'should pass', 'recommend pass', 'losing money',
            'overestimated', 'not profitable', 'no profit', 'bad deal',
            'major error', 'pearl trap', 'mabe pearl', 'can only pay',
            'value appears to be in the', 'not the gold', 'only 1', 'only 2',
            'leaving only', 'trap', 'classic trap', 'break-even or loss',
            'collectible value', 'shell value', 'carved shell', 'bail only',
            'clasp only', 'just the clasp', 'not gold content', '8x over scrap',
            '10x over scrap', '5x over scrap', 'over scrap value',
            # Red flag language
            'red flag', 'major red flag', 'fabricated', 'impossible',
            'unknown weight', 'no weight', 'cannot verify', 'cannot calculate',
            'uncertain', 'too risky', 'high risk', 'avoid', 'do not buy',
            'pass on this', 'skip this', 'not recommended', 'would not buy',
            'insufficient information', 'insufficient data', 'need more info',
            'could easily exceed', 'likely under', 'appears to be'
        ]

        if tier2_rec == 'BUY':
            for indicator in negative_indicators:
                if indicator in tier2_reasoning:
                    logger.warning(f"[TIER2] SANITY CHECK FAILED: Reasoning says '{indicator}' but recommendation is BUY")
                    logger.warning(f"[TIER2] Forcing PASS due to contradictory reasoning")
                    tier2_rec = 'PASS'
                    tier2_result['Recommendation'] = 'PASS'
                    tier2_result['tier2_sanity_override'] = f"Forced PASS: reasoning contained '{indicator}'"
                    break

        # === ADDITIONAL SANITY CHECKS ===
        if tier2_rec == 'BUY' and category in ['gold', 'silver']:
            weight_source = str(tier1_result.get('weightSource', 'estimate')).lower()
            tier2_profit = 0
            try:
                profit_str = str(tier2_result.get('Profit', tier1_result.get('Profit', '0')))
                tier2_profit = float(profit_str.replace('$', '').replace('+', '').replace(',', ''))
            except:
                tier2_profit = 0

            # If weight was estimated and profit is > $200, be skeptical
            if weight_source == 'estimate' and tier2_profit > 200:
                logger.warning(f"[TIER2] SANITY: Estimated weight + ${tier2_profit:.0f} profit = unreliable")
                tier2_rec = 'RESEARCH'
                tier2_result['Recommendation'] = 'RESEARCH'
                tier2_result['tier2_sanity_override'] = f"Downgraded to RESEARCH: Weight estimated, high profit (${tier2_profit:.0f}) unreliable"

        # === CRITICAL: No BUY without verified PriceCharting data for video games/TCG/LEGO ===
        if tier2_rec == 'BUY' and category in ['videogames', 'tcg', 'lego']:
            pc_match = tier1_result.get('pcMatch', 'No')
            if pc_match != 'Yes':
                logger.warning(f"[TIER2] BLOCKING BUY: No PriceCharting verification for {category}")
                tier2_rec = 'RESEARCH'
                tier2_result['Recommendation'] = 'RESEARCH'
                tier2_result['tier2_sanity_override'] = f"Forced RESEARCH: Cannot BUY {category} without verified market data"
                tier2_result['Profit'] = 0
                tier2_result['marketprice'] = 0
                tier2_result['reasoning'] = tier2_result.get('reasoning', '') + " [SERVER: BUY blocked - no verified pricing data. Manual research required.]"

        if tier2_override or tier2_rec != tier1_rec:
            logger.info(f"[TIER2] OVERRIDE: {tier1_rec} -> {tier2_rec}")
            logger.info(f"[TIER2] Reason: {tier2_result.get('tier2_reason', 'N/A')[:100]}")

            # === LOG TRAINING DATA FOR OVERRIDES ===
            if config.log_training_override:
                override_type = f"{tier1_rec}_TO_{tier2_rec}"
                config.log_training_override(
                    title=title,
                    price=price,
                    category=category,
                    tier1_result=tier1_result,
                    tier2_result=tier2_result,
                    override_type=override_type,
                    listing_data=data
                )
        else:
            logger.info(f"[TIER2] Confirmed: {tier2_rec}")

        # Merge results - Tier 2 takes precedence for ALL fields it provides
        merged = tier1_result.copy()
        merged['Recommendation'] = tier2_rec
        merged['tier2'] = 'verified' if not tier2_override else 'overridden'
        merged['tier2_reason'] = tier2_result.get('tier2_reason', '')
        merged['tier1_rec'] = tier1_rec

        # === CRITICAL: Sonnet's values override Haiku's for ALL display fields ===
        display_fields = [
            'Profit', 'confidence', 'reasoning',
            # Gold/Silver fields
            'karat', 'goldweight', 'weight', 'silverweight',
            'meltvalue', 'maxBuy', 'sellPrice', 'melt',
            'itemtype', 'stoneDeduction', 'weightSource',
            # Video games/TCG/LEGO fields
            'marketprice', 'condition',
            # General
            'Margin'
        ]

        for field in display_fields:
            if field in tier2_result and tier2_result[field] is not None:
                merged[field] = tier2_result[field]

        # Ensure Margin matches Profit for backwards compatibility
        if 'Profit' in tier2_result:
            merged['Margin'] = tier2_result['Profit']

        logger.info(f"[TIER2] Merged fields from Sonnet: {[f for f in display_fields if f in tier2_result]}")

        # === TIER 2 GOLD WEIGHT CORRECTION ===
        if category in ['gold', 'silver'] and config.get_spot_prices:
            tier2_reasoning_lower = tier2_reasoning.lower() if tier2_reasoning else ""

            # Look for corrected gold weight in Tier 2 reasoning
            weight_patterns = [
                r'only\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*g',  # "only 1.6-3.6g" - use lower
                r'leaving\s*(?:only\s*)?(\d+(?:\.\d+)?)\s*g',  # "leaving only 2g"
                r'actual\s*(?:gold)?[:\s]*(\d+(?:\.\d+)?)\s*g',  # "actual gold: 2g"
                r'(\d+(?:\.\d+)?)\s*g\s*(?:of\s+)?(?:actual\s+)?gold',  # "2g of gold"
                r'can\s*only\s*pay\s*\$(\d+)',  # "can only pay $117" - extract max buy
            ]

            corrected_weight = None
            corrected_max_buy = None

            for pattern in weight_patterns:
                match = re.search(pattern, tier2_reasoning_lower)
                if match:
                    if 'can only pay' in pattern:
                        corrected_max_buy = float(match.group(1))
                        logger.info(f"[TIER2] Extracted max buy from reasoning: ${corrected_max_buy}")
                    elif len(match.groups()) == 2:
                        corrected_weight = float(match.group(1))
                        logger.info(f"[TIER2] Extracted weight range: {match.group(1)}-{match.group(2)}g, using {corrected_weight}g")
                    else:
                        corrected_weight = float(match.group(1))
                        logger.info(f"[TIER2] Extracted corrected weight: {corrected_weight}g")
                    break

            # Recalculate if we found a corrected weight
            if corrected_weight and corrected_weight < 5:
                spots = config.get_spot_prices()
                karat_str = str(merged.get('karat', '14K')).upper().replace('K', '').replace('KT', '')
                try:
                    karat_num = int(karat_str) if karat_str.isdigit() else 14
                except:
                    karat_num = 14

                karat_purity = {9: 0.375, 10: 0.417, 14: 0.583, 18: 0.75, 22: 0.916, 24: 1.0}.get(karat_num, 0.583)
                gold_price_per_gram = spots.get('gold_oz', 2650) / 31.1035

                new_melt = corrected_weight * gold_price_per_gram * karat_purity
                new_max_buy = new_melt * 0.90
                new_sell = new_melt * 0.96
                new_profit = new_max_buy - price

                logger.warning(f"[TIER2] RECALCULATING: {corrected_weight}g {karat_num}K = ${new_melt:.0f} melt, ${new_max_buy:.0f} max buy")
                logger.warning(f"[TIER2] New profit: ${new_profit:.0f} (was ${tier1_margin:.0f})")

                merged['goldweight'] = f"{corrected_weight}"
                merged['melt'] = f"${new_melt:.0f}"
                merged['maxBuy'] = f"${new_max_buy:.0f}"
                merged['sell96'] = f"${new_sell:.0f}"
                merged['Profit'] = f"{new_profit:+.0f}"
                merged['Margin'] = f"{new_profit:+.0f}"
                merged['tier2_weight_correction'] = f"Tier1: {tier1_result.get('goldweight', '?')}g -> Tier2: {corrected_weight}g"

                # Force PASS if recalculated profit is negative
                if new_profit < 0:
                    merged['Recommendation'] = 'PASS'
                    logger.warning(f"[TIER2] Forcing PASS: recalculated profit ${new_profit:.0f} is negative")

            # Or if we found a max buy value directly
            elif corrected_max_buy:
                new_profit = corrected_max_buy - price
                merged['maxBuy'] = f"${corrected_max_buy:.0f}"
                merged['Profit'] = f"{new_profit:+.0f}"
                merged['Margin'] = f"{new_profit:+.0f}"

                if new_profit < 0:
                    merged['Recommendation'] = 'PASS'
                    logger.warning(f"[TIER2] Forcing PASS: max buy ${corrected_max_buy:.0f} < price ${price:.0f}")

        logger.info(f"[TIER2] Final merged Profit: {merged.get('Profit')}")
        return merged

    except Exception as e:
        logger.error(f"[TIER2] Error: {e}")
        tier1_result['tier2'] = f'error: {str(e)[:50]}'
        return tier1_result


# ============================================================
# TIER 2 RE-ANALYSIS (OpenAI GPT-4o)
# ============================================================
async def tier2_reanalyze_openai(
    title: str,
    price: float,
    category: str,
    tier1_result: Dict,
    images: List,
    data: Dict,
    system_prompt: str
) -> Dict:
    """
    Re-analyze a BUY/RESEARCH listing with OpenAI GPT-4o-mini for FAST verification.
    This is an alternative to Claude Sonnet - much faster but slightly less accurate.
    """
    if not config.openai_client:
        logger.warning("[TIER2-OPENAI] No OpenAI client, falling back to Claude")
        return await tier2_reanalyze(title, price, category, tier1_result, images, data, system_prompt)

    # Check hourly budget before Tier 2 call (GPT-4o is expensive)
    if config.check_openai_budget and not config.check_openai_budget(config.COST_PER_CALL_GPT4O):
        logger.warning(f"[TIER2-OPENAI] SKIPPED due to budget limit - keeping Tier1 result")
        tier1_result['tier2'] = 'budget_skip'
        tier1_result['tier2_reason'] = 'Hourly OpenAI budget exceeded'
        return tier1_result

    tier1_rec = tier1_result.get('Recommendation', 'RESEARCH')
    tier1_margin = 0

    try:
        margin_val = tier1_result.get('Profit', tier1_result.get('margin', tier1_result.get('Margin', '0')))
        if isinstance(margin_val, str):
            margin_val = margin_val.replace('$', '').replace(',', '').replace('%', '').replace('+', '')
        tier1_margin = float(margin_val) if margin_val else 0
    except:
        tier1_margin = 0

    logger.info(f"[TIER2-OPENAI] Fast verification with {config.OPENAI_TIER2_MODEL}: {title[:50]}...")

    try:
        # Build messages for OpenAI
        messages_content = []

        # Add images if available (OpenAI format is different from Claude)
        image_content = []
        if images:
            for img in images[:6]:  # Max 6 images for speed
                if isinstance(img, dict) and 'source' in img:
                    source = img['source']
                    if source.get('type') == 'base64':
                        media_type = source.get('media_type', 'image/jpeg')
                        data_b64 = source.get('data', '')
                        image_content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{data_b64}",
                                "detail": "low"  # Use low detail for speed
                            }
                        })

        # Build the prompt (simplified for speed)
        if category == 'gold':
            field_spec = "karat, goldweight (grams), meltvalue, maxBuy (90% of melt), Profit (maxBuy - listing price)"
            category_rules = ""
        elif category == 'silver':
            field_spec = "weight (grams), silverweight, meltvalue, maxBuy (75% of melt), Profit (maxBuy - listing price)"
            category_rules = """
SILVER RULES:
- If title states weight (e.g., '218 GRAMS'), USE THAT EXACT WEIGHT - seller weighed it
- 'Souvenir spoons' marked STERLING are solid sterling - do not question
- Flatware lots are solid unless knives included
- Only override if item is clearly PLATED (EPNS, Rogers, etc.)"""
        else:
            field_spec = "marketprice, maxBuy (65% of market), Profit"
            category_rules = ""

        verification_prompt = f"""QUICK VERIFICATION - Verify or reject Tier 1's BUY recommendation.

TIER 1 SAYS: {tier1_rec} with ${tier1_margin:.0f} profit
Title: {title}
Price: ${price:.2f}
Category: {category}
{category_rules}

CHECK:
1. Did Tier 1 use the STATED weight from title? If yes, trust it.
2. Any red flags (fake, plated, damaged, wrong identification)?
3. Is the math correct?

IMPORTANT: If weight is stated in title, USE IT. Do not reduce weight based on photo guessing.

Return JSON ONLY (no markdown):
{{"Recommendation": "BUY" or "PASS", "Profit": number, "confidence": 0-100, "reasoning": "brief explanation", {field_spec}, "tier2_override": true/false, "tier2_reason": "why"}}"""

        # Build the message content
        user_content = []
        if image_content:
            user_content.extend(image_content)
        user_content.append({"type": "text", "text": verification_prompt})

        # Call OpenAI
        response = await config.openai_client.chat.completions.create(
            model=config.OPENAI_TIER2_MODEL,
            max_tokens=500,
            messages=[
                {"role": "system", "content": f"You are an arbitrage expert specializing in {category}. Respond with JSON only, no markdown."},
                {"role": "user", "content": user_content}
            ]
        )

        # Track cost
        config.STATS["session_cost"] += config.COST_PER_CALL_OPENAI
        config.STATS["api_calls"] += 1
        if config.record_openai_cost:
            config.record_openai_cost(config.COST_PER_CALL_OPENAI)

        # Parse response
        raw_response = response.choices[0].message.content
        logger.info(f"[TIER2-OPENAI] Response: {raw_response[:200]}...")

        # Extract JSON
        tier2_result = None
        try:
            clean_response = raw_response.strip()
            if clean_response.startswith('```'):
                clean_response = clean_response.split('```')[1]
                if clean_response.startswith('json'):
                    clean_response = clean_response[4:]
                clean_response = clean_response.strip()

            if '{' in clean_response:
                start = clean_response.find('{')
                end = clean_response.rfind('}') + 1
                clean_response = clean_response[start:end]

            tier2_result = json.loads(clean_response)
        except Exception as e:
            logger.warning(f"[TIER2-OPENAI] JSON parse failed: {e}")
            tier1_result['tier2'] = 'openai_parse_error'
            return tier1_result

        # Get recommendation
        tier2_rec = tier2_result.get('Recommendation', tier1_rec)

        # Same sanity checks as Claude tier2
        tier2_reasoning = str(tier2_result.get('reasoning', '')).lower()

        # Only check for DEFINITE negative indicators
        negative_phrases = [
            'at a loss', 'negative profit', 'overpriced', 'not worth', 'would not recommend',
            'is fake', 'is plated', 'likely fake', 'likely plated', 'appears fake',
            'probably fake', 'this is plated'
        ]
        negation_prefixes = ['no ', 'not ', 'isn\'t ', 'aren\'t ', 'without ', 'zero ', 'none ']

        if tier2_rec == 'BUY':
            for phrase in negative_phrases:
                if phrase in tier2_reasoning:
                    phrase_pos = tier2_reasoning.find(phrase)
                    context_start = max(0, phrase_pos - 20)
                    context = tier2_reasoning[context_start:phrase_pos]
                    is_negated = any(neg in context for neg in negation_prefixes)

                    if not is_negated:
                        logger.warning(f"[TIER2-OPENAI] Sanity check: reasoning says '{phrase}' but rec is BUY, forcing PASS")
                        tier2_rec = 'PASS'
                        tier2_result['Recommendation'] = 'PASS'
                        break

        # CRITICAL SANITY CHECK: Negative profit MUST be PASS
        try:
            profit_val = tier2_result.get('Profit', 0)
            if isinstance(profit_val, str):
                profit_val = float(profit_val.replace('$', '').replace(',', '').replace('+', ''))
            if profit_val < 0 and tier2_rec == 'BUY':
                logger.warning(f"[TIER2-OPENAI] CRITICAL: Profit ${profit_val:.2f} is NEGATIVE but rec is BUY - forcing PASS!")
                tier2_rec = 'PASS'
                tier2_result['Recommendation'] = 'PASS'
                tier2_result['tier2_sanity_override'] = f"Forced PASS: negative profit ${profit_val:.2f}"
        except Exception as e:
            logger.debug(f"[TIER2-OPENAI] Profit check error: {e}")

        # TCG FAKE DETECTION OVERRIDE
        if category == 'tcg' and tier2_rec == 'PASS':
            fake_indicators = ['fake', 'unofficial', 'counterfeit', 'bootleg', 'not recognized', 'unknown set']
            has_fake_concern = any(ind in tier2_reasoning for ind in fake_indicators)

            try:
                recalc_profit = tier2_result.get('Profit', 0)
                if isinstance(recalc_profit, str):
                    recalc_profit = float(recalc_profit.replace('$', '').replace(',', '').replace('+', ''))

                if has_fake_concern and recalc_profit > 100:
                    logger.warning(f"[TIER2-OPENAI] TCG fake concern but profit ${recalc_profit:.0f} - may be new 2025 set, upgrading to RESEARCH")
                    tier2_rec = 'RESEARCH'
                    tier2_result['Recommendation'] = 'RESEARCH'
                    tier2_result['reasoning'] = tier2_result.get('reasoning', '') + f" | SERVER: High profit ${recalc_profit:.0f} despite fake concern - may be new set, needs manual verification"
            except:
                pass

        # Log override
        if tier2_rec != tier1_rec and config.log_training_override:
            logger.info(f"[TIER2-OPENAI] OVERRIDE: {tier1_rec} -> {tier2_rec}")
            config.log_training_override(title, price, category, tier1_result, tier2_result, f"{tier1_rec}_TO_{tier2_rec}")

        # Merge results
        merged = tier1_result.copy()
        for key in ['Recommendation', 'Profit', 'confidence', 'reasoning', 'tier2_override', 'tier2_reason',
                    'karat', 'goldweight', 'meltvalue', 'maxBuy', 'sellPrice', 'weight', 'silverweight', 'marketprice']:
            if key in tier2_result and tier2_result[key] is not None:
                merged[key] = tier2_result[key]

        merged['tier2'] = 'openai_verified'
        merged['tier2_model'] = config.OPENAI_TIER2_MODEL

        # CRITICAL: Run server-side validation on OpenAI results
        if category in ['gold', 'silver'] and config.validate_and_fix_margin:
            logger.info(f"[TIER2-OPENAI] Running server-side math validation...")
            merged = config.validate_and_fix_margin(merged, price, category, title, {})

        # For LEGO/TCG: Use server's PriceCharting values
        elif category in ['lego', 'tcg', 'videogames']:
            tier1_max_buy = tier1_result.get('maxBuy', '0')
            tier1_market = tier1_result.get('marketprice', '0')
            pc_confidence = tier1_result.get('pcConfidence', 'Low')

            # Safe conversion - handle 'NA', 'Unknown', etc.
            if isinstance(tier1_max_buy, str):
                try:
                    tier1_max_buy = float(tier1_max_buy.replace('$', '').replace(',', ''))
                except (ValueError, AttributeError):
                    tier1_max_buy = 0
            if isinstance(tier1_market, str):
                try:
                    tier1_market = float(tier1_market.replace('$', '').replace(',', ''))
                except (ValueError, AttributeError):
                    tier1_market = 0

            server_profit = tier1_max_buy - price
            merged['Profit'] = int(server_profit)
            merged['Margin'] = f"+{int(server_profit)}" if server_profit >= 0 else str(int(server_profit))

            # Preserve server's verified market values
            merged['marketprice'] = int(tier1_market)
            merged['maxBuy'] = tier1_max_buy

            logger.info(f"[TIER2-OPENAI] Recalculated profit for {category}: maxBuy ${tier1_max_buy:.0f} - list ${price:.0f} = ${server_profit:.0f}")

            # Server override logic for PriceCharting matches
            pc_match = tier1_result.get('pcMatch', 'No')
            has_verified_match = pc_match == 'Yes'
            is_expensive = price >= 500

            # SAFEGUARD: Check for graded cards with low grades
            # Low PSA grades (< 9) have high variance and often bad matches
            import re
            grade_match = re.search(r'PSA\s*(\d+)', title, re.IGNORECASE)
            psa_grade = int(grade_match.group(1)) if grade_match else None

            # SAFEGUARD: Suspiciously high profit usually means wrong match
            profit_too_high = server_profit > 1000  # Over $1000 profit is suspicious

            if pc_confidence == 'High' and server_profit >= 30 and merged.get('Recommendation') == 'PASS':
                # Don't override for low PSA grades (< 9) - too much variance
                if psa_grade is not None and psa_grade < 9:
                    logger.warning(f"[TIER2-OPENAI] KEEPING PASS: PSA {psa_grade} is low grade - too much variance, trusting Tier2")
                # Don't override for suspiciously high profits
                elif profit_too_high:
                    logger.warning(f"[TIER2-OPENAI] KEEPING PASS: ${server_profit:.0f} profit is suspiciously high - likely wrong PC match")
                elif has_verified_match and not is_expensive:
                    logger.warning(f"[TIER2-OPENAI] OVERRIDE: Tier2 said PASS but server has verified +${server_profit:.0f} profit with High confidence PC match")
                    merged['Recommendation'] = 'BUY'
                    merged['tier2_override'] = False
                    merged['tier2_reason'] = f"Server override: PriceCharting verified +${server_profit:.0f} profit"
                elif is_expensive:
                    logger.warning(f"[TIER2-OPENAI] KEEPING PASS: Expensive item (${price:.0f}) - trusting Tier2's judgment over server calculation")
                elif not has_verified_match:
                    logger.warning(f"[TIER2-OPENAI] KEEPING PASS: No verified PriceCharting match - can't trust AI-provided market values")

            # Force PASS for zero/negative profit
            if server_profit <= 0 and merged.get('Recommendation') == 'BUY':
                logger.warning(f"[TIER2-OPENAI] OVERRIDE: BUY->PASS - Server calculated zero/negative profit ${server_profit:.0f}")
                merged['Recommendation'] = 'PASS'
                merged['tier2_override'] = True
                merged['tier2_reason'] = f"Server override: zero/negative profit ${server_profit:.0f}"

        # FINAL SANITY CHECK
        ai_profit = merged.get('Profit', 0)
        if isinstance(ai_profit, str):
            try:
                ai_profit = float(str(ai_profit).replace('$', '').replace('+', '').replace(',', ''))
            except:
                ai_profit = 0
        if ai_profit <= 0 and merged.get('Recommendation') == 'BUY':
            logger.warning(f"[TIER2-OPENAI] SANITY: BUY with profit ${ai_profit} - forcing PASS")
            merged['Recommendation'] = 'PASS'
            merged['tier2_override'] = True
            merged['tier2_reason'] = f"Sanity check: BUY with zero/negative profit"

        logger.info(f"[TIER2-OPENAI] Final: {merged.get('Recommendation')} with profit {merged.get('Profit')}")
        return merged

    except Exception as e:
        logger.error(f"[TIER2-OPENAI] Error: {e}")
        tier1_result['tier2'] = f'openai_error: {str(e)[:50]}'
        return tier1_result
