"""
Category Agents for Listing Analysis
Each agent handles a specific category with its own prompt and logic.
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
    platinum_keywords = ["platinum", "pt950", "pt900", "pt850", "plat ", " plat", "iridplat"]
    palladium_keywords = ["palladium", "pd950", "pd500", " pd ", "pall "]

    gold_matches = [kw for kw in gold_keywords if kw in title]
    silver_matches = [kw for kw in silver_keywords if kw in title]
    platinum_matches = [kw for kw in platinum_keywords if kw in title]
    palladium_matches = [kw for kw in palladium_keywords if kw in title]

    # === PRIORITY -1: ALIAS OVERRIDE FOR PRECIOUS METALS ===
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
    if "textbook" in alias:
        return "textbook", [f"Alias contains 'textbook'"]
    elif "platinum" in alias:
        reasons.append(f"Alias contains 'platinum': {data.get('Alias', '')}")
        return "platinum", reasons
    elif "palladium" in alias:
        reasons.append(f"Alias contains 'palladium': {data.get('Alias', '')}")
        return "palladium", reasons
    elif "gold" in alias:
        reasons.append(f"Alias contains 'gold': {data.get('Alias', '')}")
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
    elif "allen bradley" in alias or "industrial" in alias or "plc" in alias:
        return "industrial", [f"Alias contains industrial keywords"]

    # PRIORITY 5: Fall back to title keywords
    videogame_keywords = ["sega", "genesis", "nintendo", "nes", "snes", "n64", "gamecube", "wii", "switch",
                         "playstation", "ps1", "ps2", "ps3", "ps4", "ps5", "psp", "vita",
                         "xbox", "dreamcast", "saturn", "game boy", "gameboy", "gba", "ds", "3ds",
                         "resident evil", "final fantasy", "zelda", "mario", "sonic", "mega man"]
    lego_keywords = ["lego", "sealed set"]
    tcg_keywords = ["pokemon", "booster box", "etb", "elite trainer", "yugioh", "mtg booster", "tcg"]
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
    industrial_keywords = ["allen bradley", "allen-bradley", "controllogix", "compactlogix",
                          "panelview", "powerflex", "siemens plc", "s7-1500", "s7-1200",
                          "sinamics", "1756-", "1769-", "2711p-"]

    videogame_matches = [kw for kw in videogame_keywords if kw in title]
    lego_matches = [kw for kw in lego_keywords if kw in title]
    tcg_matches = [kw for kw in tcg_keywords if kw in title]
    costume_matches = [kw for kw in costume_keywords if kw in title]
    textbook_matches = [kw for kw in textbook_keywords if kw in title]
    knife_matches = [kw for kw in knife_keywords if kw in title]
    pen_matches = [kw for kw in pen_keywords if kw in title]
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
    elif industrial_matches:
        return "industrial", [f"Title contains industrial keywords: {industrial_matches}"]

    reasons.append("No category keywords found, defaulting to silver")
    return "silver", reasons
