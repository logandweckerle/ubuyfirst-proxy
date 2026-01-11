"""
Category Agents for Listing Analysis
Each agent handles a specific category with its own prompt and logic.
"""

from .gold import GoldAgent
from .silver import SilverAgent
from .costume import CostumeAgent
from .videogames import VideoGamesAgent
from .lego import LegoAgent
from .tcg import TCGAgent
from .coral_amber import CoralAmberAgent
from .watch import WatchAgent

# Agent registry
AGENTS = {
    "gold": GoldAgent,
    "silver": SilverAgent,
    "costume": CostumeAgent,
    "videogames": VideoGamesAgent,
    "lego": LegoAgent,
    "tcg": TCGAgent,
    "coral": CoralAmberAgent,
    "watch": WatchAgent,
}

def get_agent(category: str):
    """Get the agent class for a category"""
    return AGENTS.get(category, SilverAgent)

def detect_category(data: dict) -> tuple:
    """Detect listing category from data fields, return (category, reasoning)"""
    alias = data.get("Alias", "").lower()
    title = data.get("Title", "").lower()
    reasons = []

    # Define keywords
    # Include numeric purity marks: 750=18K, 585=14K, 417=10K, 375=9K
    gold_keywords = ["10k", "14k", "18k", "22k", "24k", "karat", "750", "585", "417", "375"]
    silver_keywords = ["sterling", "925", ".925", "800", ".800"]

    gold_matches = [kw for kw in gold_keywords if kw in title]
    silver_matches = [kw for kw in silver_keywords if kw in title]

    # === PRIORITY 0: WATCH DETECTION (before gold!) ===
    # Watches should be handled by watch agent even if they have gold content
    watch_keywords = ["watch", "wristwatch", "timepiece", "chronograph", "pocket watch"]
    watch_brands = [
        "rolex", "omega", "patek", "cartier", "breitling", "tag heuer", "tudor",
        "longines", "hamilton", "tissot", "seiko", "bulova", "movado", "citizen",
        "wittnauer", "gruen", "elgin", "waltham", "benrus", "zodiac", "oris",
        "mido", "rado", "heuer", "iwc", "panerai", "audemars", "vacheron"
    ]

    has_watch_keyword = any(kw in title for kw in watch_keywords)
    has_watch_brand = any(brand in title for brand in watch_brands)

    # If title has watch keyword OR watch brand, it's a watch (not gold scrap)
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
    if "gold" in alias:
        reasons.append(f"Alias contains 'gold': {data.get('Alias', '')}")
        return "gold", reasons
    elif "silver" in alias or "sterling" in alias or "bulk lot" in alias:
        reasons.append(f"Alias contains silver/sterling/bulk: {data.get('Alias', '')}")
        return "silver", reasons
    elif "lego" in alias:
        return "lego", [f"Alias contains 'lego'"]
    elif "tcg" in alias or "pokemon" in alias or "sealed" in alias:
        return "tcg", [f"Alias contains TCG keywords"]
    elif "coral" in alias or "amber" in alias:
        return "coral", [f"Alias contains coral/amber"]
    elif "costume" in alias or "jewelry lot" in alias or "vintage lot" in alias:
        return "costume", [f"Alias contains costume keywords"]
    elif "videogame" in alias or "video game" in alias or "game" in alias:
        return "videogames", [f"Alias contains video game keywords"]

    # PRIORITY 5: Fall back to title keywords
    videogame_keywords = ["sega", "genesis", "nintendo", "nes", "snes", "n64", "gamecube", "wii", "switch",
                         "playstation", "ps1", "ps2", "ps3", "ps4", "ps5", "psp", "vita",
                         "xbox", "dreamcast", "saturn", "game boy", "gameboy", "gba", "ds", "3ds",
                         "resident evil", "final fantasy", "zelda", "mario", "sonic", "mega man"]
    lego_keywords = ["lego", "sealed set"]
    tcg_keywords = ["pokemon", "booster box", "etb", "elite trainer", "yugioh", "mtg booster", "tcg"]
    costume_keywords = ["costume jewelry", "vintage jewelry lot", "jewelry lot", "trifari", "coro", "eisenberg"]

    videogame_matches = [kw for kw in videogame_keywords if kw in title]
    lego_matches = [kw for kw in lego_keywords if kw in title]
    tcg_matches = [kw for kw in tcg_keywords if kw in title]
    costume_matches = [kw for kw in costume_keywords if kw in title]

    if videogame_matches:
        return "videogames", [f"Title contains video game keywords: {videogame_matches}"]
    elif lego_matches:
        return "lego", [f"Title contains LEGO keywords"]
    elif tcg_matches:
        return "tcg", [f"Title contains TCG keywords"]
    elif gold_matches:
        return "gold", [f"Title contains gold keywords: {gold_matches}"]
    elif silver_matches:
        return "silver", [f"Title contains silver keywords: {silver_matches}"]
    elif costume_matches:
        return "costume", [f"Title contains costume keywords"]

    reasons.append("No category keywords found, defaulting to silver")
    return "silver", reasons
