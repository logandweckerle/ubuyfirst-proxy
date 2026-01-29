"""
RAG Context System for Arbitrage Analysis

Uses LanceDB + sentence-transformers to find similar past purchases
and provide relevant context for weight estimation and pricing decisions.
"""

import os
import re
import sqlite3
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import lancedb
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).parent.parent
PURCHASE_DB = BASE_DIR / "purchase_history.db"
LANCE_DB_PATH = BASE_DIR / "rag_vectors"

# Global instances (lazy loaded)
_model: Optional[SentenceTransformer] = None
_db: Optional[lancedb.DBConnection] = None
_table = None


@dataclass
class SimilarPurchase:
    """A similar past purchase with extracted data."""
    title: str
    price: float
    category: str
    weight_grams: Optional[float]
    karat: Optional[str]
    similarity: float

    def to_context_string(self) -> str:
        """Format for injection into AI prompt."""
        import math
        # Handle None and NaN
        has_weight = self.weight_grams is not None and not (isinstance(self.weight_grams, float) and math.isnan(self.weight_grams))
        weight_str = f"{self.weight_grams:.1f}g" if has_weight else "weight unknown"
        karat_str = f" {self.karat}" if self.karat else ""
        return f"- BOUGHT: {self.title[:80]} | ${self.price:.0f} | {weight_str}{karat_str}"


def extract_weight_from_title(title: str) -> Optional[float]:
    """
    Extract weight in grams from a title string.
    Handles: grams, g, dwt, oz, pennyweight
    """
    title_lower = title.lower()

    # Grams patterns: "14 grams", "14g", "14.5 grams"
    gram_patterns = [
        r'(\d+\.?\d*)\s*(?:gram|grams|gr|g)(?:\s|$|[,.])',
        r'(\d+\.?\d*)\s*g(?:ram)?s?\b',
    ]
    for pattern in gram_patterns:
        match = re.search(pattern, title_lower)
        if match:
            return float(match.group(1))

    # DWT (pennyweight) - 1 dwt = 1.555g
    dwt_patterns = [
        r'(\d+\.?\d*)\s*(?:dwt|pennyweight)',
    ]
    for pattern in dwt_patterns:
        match = re.search(pattern, title_lower)
        if match:
            return float(match.group(1)) * 1.555

    # Troy ounces - 1 ozt = 31.1g
    oz_patterns = [
        r'(\d+\.?\d*)\s*(?:troy\s*)?(?:oz|ounce)',
    ]
    for pattern in oz_patterns:
        match = re.search(pattern, title_lower)
        if match:
            return float(match.group(1)) * 31.1

    return None


def extract_karat_from_title(title: str) -> Optional[str]:
    """Extract karat marking from title."""
    title_lower = title.lower()

    # Gold karats
    karat_patterns = [
        r'\b(24k|24kt|24 karat)\b',
        r'\b(22k|22kt|22 karat)\b',
        r'\b(18k|18kt|18 karat)\b',
        r'\b(14k|14kt|14 karat)\b',
        r'\b(10k|10kt|10 karat)\b',
        r'\b(9k|9kt|9 karat)\b',
    ]
    for pattern in karat_patterns:
        if re.search(pattern, title_lower):
            match = re.search(r'(\d+)k', title_lower)
            if match:
                return f"{match.group(1)}K"

    # Sterling silver
    if any(x in title_lower for x in ['sterling', '925', '.925']):
        return '925'

    # Other silver
    if '800' in title_lower:
        return '800'
    if '833' in title_lower:
        return '833'

    return None


def extract_item_type(title: str) -> str:
    """Extract the type of item from title."""
    title_lower = title.lower()

    item_types = [
        ('chain', ['chain', 'necklace', 'rope', 'figaro', 'cuban', 'byzantine', 'box chain', 'snake chain']),
        ('bracelet', ['bracelet', 'bangle', 'tennis bracelet']),
        ('ring', ['ring', 'band', 'signet']),
        ('earrings', ['earring', 'stud', 'hoop earring']),
        ('pendant', ['pendant', 'charm', 'locket']),
        ('brooch', ['brooch', 'pin', 'cameo']),
        ('flatware', ['fork', 'spoon', 'knife', 'flatware', 'serving']),
        ('watch', ['watch', 'timepiece']),
        ('scrap', ['scrap', 'lot', 'mixed']),
    ]

    for item_type, keywords in item_types:
        if any(kw in title_lower for kw in keywords):
            return item_type

    return 'jewelry'


def get_model() -> SentenceTransformer:
    """Get or initialize the embedding model."""
    global _model
    if _model is None:
        logger.info("[RAG] Loading embedding model (all-MiniLM-L6-v2)...")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("[RAG] Embedding model loaded")
    return _model


def get_db():
    """Get or initialize the LanceDB connection."""
    global _db, _table
    if _db is None:
        logger.info(f"[RAG] Connecting to LanceDB at {LANCE_DB_PATH}")
        _db = lancedb.connect(str(LANCE_DB_PATH))

        # Check if table exists
        try:
            _table = _db.open_table("purchases")
            logger.info(f"[RAG] Opened existing purchases table")
        except Exception:
            _table = None
            logger.info("[RAG] No existing table found - will create on first index")

    return _db, _table


def index_purchases(force_rebuild: bool = False) -> int:
    """
    Index all purchases from purchase_history.db into the vector store.
    Returns the number of items indexed.
    """
    global _table

    db, table = get_db()
    model = get_model()

    # Check if we need to rebuild
    if table is not None and not force_rebuild:
        count = table.count_rows()
        logger.info(f"[RAG] Table already has {count} rows, skipping rebuild")
        return count

    logger.info("[RAG] Building purchase index...")

    # Load purchases from SQLite
    conn = sqlite3.connect(PURCHASE_DB)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, title, price, category, keywords
        FROM purchases
        WHERE category IN ('gold', 'silver', 'watches')
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        logger.warning("[RAG] No purchases found to index")
        return 0

    logger.info(f"[RAG] Processing {len(rows)} purchases...")

    # Build data for indexing
    data = []
    titles = []

    for row in rows:
        id_, title, price, category, keywords = row
        weight = extract_weight_from_title(title)
        karat = extract_karat_from_title(title)
        item_type = extract_item_type(title)

        titles.append(title)
        data.append({
            "id": id_,
            "title": title,
            "price": float(price) if price else 0.0,
            "category": category or "unknown",
            "weight_grams": weight,
            "karat": karat,
            "item_type": item_type,
            "keywords": keywords or "",
        })

    # Generate embeddings in batch
    logger.info("[RAG] Generating embeddings...")
    embeddings = model.encode(titles, show_progress_bar=True)

    # Add embeddings to data
    for i, embedding in enumerate(embeddings):
        data[i]["vector"] = embedding.tolist()

    # Create/replace table
    logger.info("[RAG] Writing to LanceDB...")
    _table = db.create_table("purchases", data, mode="overwrite")

    logger.info(f"[RAG] Indexed {len(data)} purchases")
    return len(data)


def find_similar_purchases(
    title: str,
    category: Optional[str] = None,
    limit: int = 5,
    min_similarity: float = 0.3
) -> List[SimilarPurchase]:
    """
    Find similar past purchases based on title similarity.

    Args:
        title: The listing title to search for
        category: Optional category filter ('gold', 'silver', 'watches')
        limit: Maximum number of results
        min_similarity: Minimum similarity score (0-1)

    Returns:
        List of SimilarPurchase objects sorted by similarity
    """
    db, table = get_db()

    if table is None:
        logger.warning("[RAG] No index available - run index_purchases() first")
        return []

    model = get_model()

    # Generate embedding for query
    query_embedding = model.encode([title])[0]

    # Search with optional category filter
    try:
        if category:
            results = table.search(query_embedding).where(f"category = '{category}'").limit(limit).to_pandas()
        else:
            results = table.search(query_embedding).limit(limit).to_pandas()
    except Exception as e:
        logger.error(f"[RAG] Search error: {e}")
        return []

    # Convert to SimilarPurchase objects
    purchases = []
    for _, row in results.iterrows():
        # LanceDB returns distance, convert to similarity (1 - normalized_distance)
        # For cosine distance, similarity = 1 - distance/2
        distance = row.get('_distance', 0)
        similarity = max(0, 1 - distance / 2)

        if similarity >= min_similarity:
            purchases.append(SimilarPurchase(
                title=row['title'],
                price=row['price'],
                category=row['category'],
                weight_grams=row.get('weight_grams'),
                karat=row.get('karat'),
                similarity=similarity
            ))

    return purchases


def get_weight_reference(
    title: str,
    category: str = None
) -> Dict[str, Any]:
    """
    Get weight estimation context for a listing.
    Returns similar purchases and suggested weight range.

    Args:
        title: The listing title
        category: 'gold' or 'silver'

    Returns:
        Dict with:
        - similar_purchases: List of similar items bought
        - suggested_weight_range: (min, max) in grams
        - confidence: 'high', 'medium', 'low'
        - context_string: Formatted string for AI prompt
    """
    similar = find_similar_purchases(title, category=category, limit=8)

    if not similar:
        return {
            "similar_purchases": [],
            "suggested_weight_range": None,
            "confidence": "low",
            "context_string": "No similar past purchases found."
        }

    # Filter to only those with known weights (handle None and NaN)
    import math
    def has_valid_weight(p):
        w = p.weight_grams
        return w is not None and not (isinstance(w, float) and math.isnan(w))
    with_weights = [p for p in similar if has_valid_weight(p)]

    if not with_weights:
        context_lines = [p.to_context_string() for p in similar[:5]]
        return {
            "similar_purchases": similar[:5],
            "suggested_weight_range": None,
            "confidence": "low",
            "context_string": "Similar purchases (weights unknown):\n" + "\n".join(context_lines)
        }

    # Calculate weight range from similar items
    weights = [p.weight_grams for p in with_weights]
    min_weight = min(weights)
    max_weight = max(weights)
    avg_weight = sum(weights) / len(weights)

    # Determine confidence based on similarity and sample size
    avg_similarity = sum(p.similarity for p in with_weights) / len(with_weights)
    if len(with_weights) >= 3 and avg_similarity > 0.6:
        confidence = "high"
    elif len(with_weights) >= 2 and avg_similarity > 0.4:
        confidence = "medium"
    else:
        confidence = "low"

    # Build context string
    context_lines = [
        f"Based on {len(with_weights)} similar past purchases:",
    ]
    context_lines.extend([p.to_context_string() for p in with_weights[:5]])
    context_lines.append(f"Suggested weight range: {min_weight:.1f}g - {max_weight:.1f}g (avg: {avg_weight:.1f}g)")

    return {
        "similar_purchases": with_weights[:5],
        "suggested_weight_range": (min_weight, max_weight),
        "avg_weight": avg_weight,
        "confidence": confidence,
        "context_string": "\n".join(context_lines)
    }


def build_rag_context(
    title: str,
    price: float,
    category: str,
    description: str = ""
) -> str:
    """
    Build complete RAG context string for injection into AI prompt.

    This is the main function to call from the pipeline.
    """
    # Get weight reference from similar purchases
    weight_ref = get_weight_reference(title, category)

    # Extract what we can from the current listing
    stated_weight = extract_weight_from_title(title)
    karat = extract_karat_from_title(title)
    item_type = extract_item_type(title)

    lines = [
        "=== HISTORICAL PURCHASE CONTEXT ===",
        f"Item type: {item_type}",
    ]

    if stated_weight:
        lines.append(f"Stated weight: {stated_weight}g")

    if karat:
        lines.append(f"Purity: {karat}")

    lines.append("")
    lines.append(weight_ref["context_string"])

    if weight_ref["suggested_weight_range"]:
        min_w, max_w = weight_ref["suggested_weight_range"]
        lines.append(f"\nWeight estimation confidence: {weight_ref['confidence'].upper()}")

        if not stated_weight:
            lines.append(f"USE ESTIMATED WEIGHT: {weight_ref['avg_weight']:.1f}g for calculations")

    lines.append("=== END HISTORICAL CONTEXT ===")

    return "\n".join(lines)


# CLI for testing/rebuilding index
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        print("Rebuilding purchase index...")
        count = index_purchases(force_rebuild=True)
        print(f"Indexed {count} purchases")
    else:
        # Test search
        test_titles = [
            "14K Gold Byzantine Bracelet 7 inch",
            "Sterling Silver Flatware Lot",
            "Omega Seamaster Watch Vintage",
        ]

        # Ensure index exists
        index_purchases()

        for title in test_titles:
            print(f"\n=== Searching: {title} ===")
            context = build_rag_context(title, 200, "gold")
            print(context)
