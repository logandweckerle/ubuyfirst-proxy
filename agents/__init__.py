"""
Category Agents for Listing Analysis
Each agent handles a specific category with its own prompt and logic.

FIX 2026-01-25: Added silver keyword check before routing gold alias to gold category
"""

from .gold import GoldAgent
from .silver import SilverAgent
from .platinum import PlatinumAgent
from .palladium import PalladiumAgent
from .costume import CostumeAgent
from .videogames import VideoGamesAgent
from .lego import LegoAgent
from .tcg import TCGAgent
from .coral_amber import CoralAmberAgent
from .watch import WatchAgent
from .textbook import TextbookAgent
from .knives import KnivesAgent
from .pens import PensAgent
from .industrial import IndustrialAgent
from .allen_bradley import AllenBradleyAgent

# Agent registry
AGENTS = {
    "gold": GoldAgent,
    "silver": SilverAgent,
    "platinum": PlatinumAgent,
    "palladium": PalladiumAgent,
    "costume": CostumeAgent,
    "videogames": VideoGamesAgent,
    "lego": LegoAgent,
    "tcg": TCGAgent,
    "coral": CoralAmberAgent,
    "watch": WatchAgent,
    "textbook": TextbookAgent,
    "knives": KnivesAgent,
    "pens": PensAgent,
    "industrial": IndustrialAgent,
    "allen_bradley": AllenBradleyAgent,
}

def get_agent(category: str):
    """Get the agent class for a category"""
    return AGENTS.get(category, SilverAgent)

def detect_category(data: dict) -> tuple:
    """Detect listing category from data fields, return (category, reasoning)"""
    alias = data.get("Alias", "").lower()
    # Normalize title - handle URL encoding (+ for spaces)
    title = data.get("Title", "").lower().replace('+', ' ')
    reasons = []

    # Define keywords
    # Include numeric purity marks: 750=18K, 585=14K, 417=10K, 375=9K
    # Also include variations with space before "k" (e.g., "14 k" from URL encoding)
    gold_keywords = ["10k", "14k", "18k", "22k", "24k", "10 k", "14 k", "18 k", "22 k", "24 k", "karat", "750", "585", "417", "375"]
    silver_keywords = ["sterling", "925", ".925", "800", ".800"]
    platinum_keywords = ["platinum", "pt950", "pt900", "pt850", "plat ", " plat", "iridplat"]
    palladium_keywords = ["palladium", "pd950", "pd500", " pd ", "pall "]

    gold_matches = [kw for kw in gold_keywords if kw in title]
    silver_matches = [kw for kw in silver_keywords if kw in title]
    platinum_matches = [kw for kw in platinum_keywords if kw in title]
    palladium_matches = [kw for kw in palladium_keywords if kw in title]

    # === PRIORITY -1: MIXED METAL CHECK (BEFORE alias routing) ===
    # Items with BOTH silver (925/.925/sterling) AND gold karat = ALWAYS SILVER
    # The gold is just accent/plating, the bulk is sterling silver
    has_silver_word = ' silver ' in f' {title} ' or title.startswith('silver ') or title.endswith(' silver')
    has_silver_word = has_silver_word or 'silver &' in title or '& silver' in title or 'silver 14k' in title or 'silver 10k' in title or 'silver 18k' in title

    if (silver_matches or has_silver_word) and gold_matches:
        reasons.append(f"MIXED METAL: Has both {silver_matches or 'silver'} AND {gold_matches} - routing to SILVER (gold is accent)")
        return "silver", reasons

    # === PRIORITY 0: ALIAS OVERRIDE FOR PRECIOUS METALS ===
    # If user explicitly searched for a metal, trust that intent even if title has watch brands
    # This fixes the "omega necklace" being classified as watch when alias is "Gold Jewelry Search"
    if "gold" in alias and gold_matches:
        reasons.append(f"Alias explicitly contains 'gold' AND title has gold karat - routing to GOLD agent")
        return "gold", reasons
    if ("silver" in alias or "sterling" in alias) and silver_matches:
        reasons.append(f"Alias explicitly contains silver/sterling AND title has silver marks - routing to SILVER agent")
        return "silver", reasons
    if "platinum" in alias and platinum_matches:
        reasons.append(f"Alias explicitly contains 'platinum' AND title has platinum marks - routing to PLATINUM agent")
        return "platinum", reasons
    if "palladium" in alias and palladium_matches:
        reasons.append(f"Alias explicitly contains 'palladium' AND title has palladium marks - routing to PALLADIUM agent")
        return "palladium", reasons

    # === PRIORITY 0: WATCH DETECTION (before gold!) ===
    # Watches should be handled by watch agent UNLESS they have solid gold content
    watch_keywords = ["watch", "wristwatch", "timepiece", "chronograph", "pocket watch"]
    watch_brands = [
        "rolex", "omega", "patek", "cartier", "breitling", "tag heuer", "tudor",
        "longines", "hamilton", "tissot", "seiko", "bulova", "movado", "citizen",
        "wittnauer", "gruen", "elgin", "waltham", "benrus", "zodiac", "oris",
        "mido", "rado", "heuer", "iwc", "panerai", "audemars", "vacheron"
    ]

    has_watch_keyword = any(kw in title for kw in watch_keywords)
    has_watch_brand = any(brand in title for brand in watch_brands)

    # IMPORTANT: "Omega" is ALSO a jewelry chain style (omega chain/necklace)
    # If title has jewelry context + precious metal, it's NOT a watch!
    jewelry_context = ["necklace", "chain", "bracelet", "pendant", "earring", "ring ", " ring", "anklet", "choker"]
    precious_metal_context = ["sterling", "925", ".925", "14k", "18k", "10k", "gold", "silver", "platinum"]
    has_jewelry_context = any(jw in title for jw in jewelry_context)
    has_precious_metal = any(pm in title for pm in precious_metal_context)

    # If "omega" appears with jewelry + metal context, it's an omega chain, not Omega watch
    if has_watch_brand and has_jewelry_context and has_precious_metal and not has_watch_keyword:
        # This is jewelry (like "omega sterling silver necklace"), not a watch
        has_watch_brand = False  # Override - treat as jewelry, not watch

    # Check if watch has SOLID gold content (not gold-filled, plated, or tone)
    # These should go to gold agent for melt value evaluation
    solid_gold_indicators = ["14k gold case", "18k gold case", "10k gold case", "14 k gold case",
                            "18 k gold case", "10 k gold case", "solid gold", "solid 14k", "solid 18k",
                            "14kt gold case", "18kt gold case", "14k case", "18k case"]
    not_solid_gold = ["gold filled", "gold plated", "gold tone", "gf ", " gf", "rolled gold", "rgp"]

    has_solid_gold_case = any(indicator in title for indicator in solid_gold_indicators)
    has_fake_gold = any(fake in title for fake in not_solid_gold)

    # If watch has solid gold case (and not gold-filled), route to GOLD agent for melt evaluation
    if (has_watch_keyword or has_watch_brand) and has_solid_gold_case and not has_fake_gold:
        reasons.append(f"Watch with SOLID GOLD CASE detected - routing to GOLD agent for melt value")
        return "gold", reasons

    # If title has watch keyword OR watch brand (without solid gold), it's a regular watch
    if has_watch_keyword or has_watch_brand:
        if has_watch_keyword and has_watch_brand:
            reasons.append(f"Watch keyword AND brand detected - routing to WATCH agent")
        elif has_watch_keyword:
            reasons.append(f"Watch keyword detected - routing to WATCH agent")
        else:
            reasons.append(f"Watch brand detected - routing to WATCH agent")
        return "watch", reasons

    # Also check alias for watch intent
    if "watch" in alias:
        reasons.append(f"Alias contains 'watch' - routing to WATCH agent")
        return "watch", reasons

    # PRIORITY 1: Known mixed-metal brands = ALWAYS SILVER
    mixed_metal_brands = ['john hardy', 'david yurman', 'lagos', 'konstantino', 'andrea candela']
    for brand in mixed_metal_brands:
        if brand in title:
            reasons.append(f"Known mixed-metal brand '{brand}' detected - primarily SILVER")
            return "silver", reasons

    # PRIORITY 2: Sterling/Silver + Gold combo = ALWAYS SILVER
    has_silver_word = ' silver ' in f' {title} ' or title.startswith('silver ') or title.endswith(' silver')
    has_silver_word = has_silver_word or 'silver &' in title or '& silver' in title

    if (silver_matches or has_silver_word) and gold_matches:
        reasons.append(f"Title has BOTH silver AND gold - mixed metal = treating as SILVER")
        return "silver", reasons

    # PRIORITY 4: Check Alias (user's search intent)
    # IMPORTANT: If alias says "gold" but title has SILVER keywords, route to SILVER!
    # This handles items showing up in gold category searches that are actually silver
    if "textbook" in alias:
        return "textbook", [f"Alias contains 'textbook'"]
    elif "platinum" in alias:
        reasons.append(f"Alias contains 'platinum': {data.get('Alias', '')}")
        return "platinum", reasons
    elif "palladium" in alias:
        reasons.append(f"Alias contains 'palladium': {data.get('Alias', '')}")
        return "palladium", reasons
    elif "gold" in alias:
        # CRITICAL FIX: Check if title actually has SILVER keywords before routing to gold
        # Items can appear in "Gold" category searches but actually be sterling silver
        if silver_matches or has_silver_word:
            reasons.append(f"Alias says gold BUT title has silver ({silver_matches}) - routing to SILVER")
            return "silver", reasons
        elif gold_matches or "gold" in title:
            reasons.append(f"Alias contains 'gold' AND title has gold indicators: {data.get('Alias', '')}")
            return "gold", reasons
        else:
            # Alias says gold but no metal keywords in title - default to gold but log warning
            reasons.append(f"WARNING: Alias says 'gold' but no gold keywords in title - defaulting to gold")
            return "gold", reasons
    elif "silver" in alias or "sterling" in alias or "bulk lot" in alias:
        reasons.append(f"Alias contains silver/sterling/bulk: {data.get('Alias', '')}")
        return "silver", reasons
    elif "lego" in alias:
        return "lego", [f"Alias contains 'lego'"]
    elif "tcg" in alias or "pokemon" in alias or "sealed" in alias or "psa" in alias or "bgs" in alias or "cgc" in alias or "graded" in alias:
        return "tcg", [f"Alias contains TCG/graded keywords"]
    elif "coral" in alias or "amber" in alias:
        return "coral", [f"Alias contains coral/amber"]
    elif "costume" in alias or "jewelry lot" in alias or "vintage lot" in alias:
        return "costume", [f"Alias contains costume keywords"]
    elif "videogame" in alias or "video game" in alias or "game" in alias:
        return "videogames", [f"Alias contains video game keywords"]
    elif "knife" in alias or "knives" in alias:
        return "knives", [f"Alias contains knife keywords"]
    elif "pen" in alias or "fountain" in alias:
        return "pens", [f"Alias contains pen keywords"]
    elif "allen bradley" in alias or "allen-bradley" in alias or "rockwell" in alias:
        return "allen_bradley", [f"Alias contains Allen Bradley keywords"]
    elif "industrial" in alias or "plc" in alias:
        return "industrial", [f"Alias contains industrial keywords"]

    # PRIORITY 5: Fall back to title keywords
    videogame_keywords = ["sega", "genesis", "nintendo", "nes", "snes", "n64", "gamecube", "wii", "switch",
                         "playstation", "ps1", "ps2", "ps3", "ps4", "ps5", "psp", "vita",
                         "xbox", "dreamcast", "saturn", "game boy", "gameboy", "gba", "ds", "3ds",
                         "resident evil", "final fantasy", "zelda", "mario", "sonic", "mega man"]
    lego_keywords = ["lego", "sealed set"]
    tcg_keywords = ["pokemon", "booster box", "etb", "elite trainer", "yugioh", "mtg booster", "tcg",
                   "psa 10", "psa 9", "psa 8", "psa 7", "bgs 10", "bgs 9.5", "bgs 9", "cgc 10", "cgc 9",
                   "psa graded", "bgs graded", "cgc graded", "graded card", "1st edition", "shadowless"]
    costume_keywords = ["costume jewelry", "vintage jewelry lot", "jewelry lot", "trifari", "coro", "eisenberg"]
    textbook_keywords = [
        # General
        "textbook", "college textbook", "university textbook",
        # Publishers
        "pearson", "mcgraw hill", "mcgraw-hill", "cengage", "wiley textbook",
        "elsevier", "springer", "oxford university press", "cambridge university press",
        "norton", "sage publications", "routledge", "houghton mifflin", "bedford",
        "worth publishers", "jones bartlett", "lippincott", "mosby", "saunders",
        # Edition patterns
        "10th edition", "11th edition", "12th edition", "13th edition", "14th edition",
        "15th edition", "16th edition", "17th edition", "18th edition",
        "edition hardcover", "latest edition", "instructor edition", "solutions manual",
        # Course patterns
        "intro to psychology", "intro to sociology", "intro to biology",
        "principles of economics", "principles of accounting", "principles of marketing",
        "fundamentals of nursing", "fundamentals of physics",
        "organic chemistry", "calculus early transcendentals", "anatomy physiology",
        "macroeconomics", "microeconomics", "financial accounting", "managerial accounting",
        # Subject indicators (catches listings without 'textbook' in title)
        "calculus", "chemistry textbook", "biology textbook", "physics textbook",
        "psychology textbook", "statistics textbook", "economics textbook",
        "accounting textbook", "engineering textbook", "nursing textbook",
        "medical textbook", "pharmacology", "pathophysiology",
        "computer science textbook", "business law", "corporate finance",
    ]

    # Knife keywords for title fallback
    knife_keywords = ["chris reeve", "strider knife", "microtech", "benchmade", "spyderco",
                     "zero tolerance", "hinderer", "protech", "case xx", "randall knife",
                     "william henry knife", "custom knife", "pocket knife lot", "knife collection"]
    # Pen keywords for title fallback
    pen_keywords = ["montblanc", "mont blanc", "pelikan", "visconti", "aurora pen",
                   "fountain pen", "waterman pen", "parker duofold", "sheaffer", "sailor pen",
                   "namiki", "pilot custom", "vintage fountain"]
    # Industrial keywords for title fallback
    # Allen Bradley specific - route to allen_bradley agent
    allen_bradley_keywords = ["allen bradley", "allen-bradley", "rockwell automation",
                             "controllogix", "compactlogix", "micrologix", "guardlogix",
                             "panelview", "powerflex", "kinetix", "stratix",
                             "1756-", "1769-", "1761-", "1762-", "1763-", "1764-",
                             "1734-", "1794-", "2711p-", "2711-", "2198-", "2094-",
                             "20f-", "22f-", "25b-", "1747-", "1785-"]
    # Other industrial brands - route to generic industrial agent
    industrial_keywords = ["siemens plc", "s7-1500", "s7-1200", "s7-300", "s7-400",
                          "sinamics", "simatic", "mitsubishi plc", "melsec",
                          "omron plc", "fanuc", "yaskawa", "abb drive"]

    videogame_matches = [kw for kw in videogame_keywords if kw in title]
    lego_matches = [kw for kw in lego_keywords if kw in title]
    tcg_matches = [kw for kw in tcg_keywords if kw in title]
    costume_matches = [kw for kw in costume_keywords if kw in title]
    textbook_matches = [kw for kw in textbook_keywords if kw in title]
    knife_matches = [kw for kw in knife_keywords if kw in title]
    pen_matches = [kw for kw in pen_keywords if kw in title]
    allen_bradley_matches = [kw for kw in allen_bradley_keywords if kw in title]
    industrial_matches = [kw for kw in industrial_keywords if kw in title]

    if textbook_matches:
        return "textbook", [f"Title contains textbook keywords: {textbook_matches}"]
    elif videogame_matches:
        return "videogames", [f"Title contains video game keywords: {videogame_matches}"]
    elif lego_matches:
        return "lego", [f"Title contains LEGO keywords"]
    elif tcg_matches:
        return "tcg", [f"Title contains TCG keywords"]
    elif platinum_matches:
        return "platinum", [f"Title contains platinum keywords: {platinum_matches}"]
    elif palladium_matches:
        return "palladium", [f"Title contains palladium keywords: {palladium_matches}"]
    elif gold_matches:
        return "gold", [f"Title contains gold keywords: {gold_matches}"]
    elif silver_matches:
        return "silver", [f"Title contains silver keywords: {silver_matches}"]
    elif costume_matches:
        return "costume", [f"Title contains costume keywords"]
    elif knife_matches:
        return "knives", [f"Title contains knife keywords: {knife_matches}"]
    elif pen_matches:
        return "pens", [f"Title contains pen keywords: {pen_matches}"]
    elif allen_bradley_matches:
        return "allen_bradley", [f"Title contains Allen Bradley keywords: {allen_bradley_matches}"]
    elif industrial_matches:
        return "industrial", [f"Title contains industrial keywords: {industrial_matches}"]

    reasons.append("No category keywords found, defaulting to silver")
    return "silver", reasons
