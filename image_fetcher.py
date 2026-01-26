"""
Async Image Fetcher - Parallel image downloading with httpx
Reduces image fetch time from 10-15 seconds (sequential) to 2-3 seconds (parallel)
Includes automatic compression for images exceeding API limits
"""

import asyncio
import base64
import logging
import io
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    print("[IMAGES] httpx not installed. Run: pip install httpx")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[IMAGES] Pillow not installed. Large images won't be compressed. Run: pip install Pillow")

from config import IMAGES

logger = logging.getLogger(__name__)

# Anthropic API limit is 5MB (5,242,880 bytes) for BASE64 encoded data
# Base64 encoding adds ~33% overhead, so raw bytes limit is 5MB / 1.33 ≈ 3.75MB
# We use 3.5MB to be safe
MAX_RAW_BYTES = 3_500_000  # Before base64 encoding
MAX_BASE64_BYTES = 5_000_000  # After base64 encoding (API limit with buffer)

# Default max images when not specified (fallback)
DEFAULT_MAX_IMAGES = 5


@dataclass
class FetchedImage:
    """Container for a fetched image"""
    url: str
    data: str  # base64 encoded
    media_type: str
    success: bool
    error: Optional[str] = None


def compress_image(image_data: bytes, media_type: str, max_bytes: int = MAX_RAW_BYTES) -> Tuple[bytes, str]:
    """
    Compress image if it exceeds max_bytes.
    Returns (compressed_data, media_type)
    """
    if len(image_data) <= max_bytes:
        return image_data, media_type
    
    if not PIL_AVAILABLE:
        logger.warning(f"[IMAGES] Image too large ({len(image_data)/1024/1024:.1f}MB) but PIL not available for compression")
        return image_data, media_type
    
    try:
        original_size = len(image_data)
        img = Image.open(io.BytesIO(image_data))
        
        # Convert RGBA to RGB if necessary (for JPEG)
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Try progressively smaller sizes and quality levels
        for scale in [0.75, 0.6, 0.5, 0.4, 0.3, 0.25, 0.2]:
            for quality in [85, 70, 55, 40, 30]:
                # Resize
                new_width = int(img.width * scale)
                new_height = int(img.height * scale)
                
                # Don't go smaller than 600px on longest side
                if max(new_width, new_height) < 600:
                    continue
                
                resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Compress to JPEG
                buffer = io.BytesIO()
                resized.save(buffer, format='JPEG', quality=quality, optimize=True)
                compressed_data = buffer.getvalue()
                
                if len(compressed_data) <= max_bytes:
                    print(f"[IMAGES] Compressed {original_size/1024/1024:.1f}MB -> {len(compressed_data)/1024/1024:.1f}MB ({new_width}x{new_height}, q={quality})")
                    return compressed_data, 'image/jpeg'
        
        # Last resort: very small and low quality
        min_dim = 600
        if img.width > img.height:
            new_width = min_dim
            new_height = int(min_dim * img.height / img.width)
        else:
            new_height = min_dim
            new_width = int(min_dim * img.width / img.height)
            
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        resized.save(buffer, format='JPEG', quality=25, optimize=True)
        compressed_data = buffer.getvalue()
        print(f"[IMAGES] Compressed {original_size/1024/1024:.1f}MB -> {len(compressed_data)/1024/1024:.1f}MB (last resort {new_width}x{new_height})")
        return compressed_data, 'image/jpeg'
        
    except Exception as e:
        logger.error(f"[IMAGES] Compression failed: {e}")
        return image_data, media_type


async def fetch_single_image(
    client: "httpx.AsyncClient",
    url: str,
    timeout: float = 5.0
) -> FetchedImage:
    """Fetch a single image asynchronously, compressing if too large"""
    try:
        response = await client.get(url, timeout=timeout)
        response.raise_for_status()
        
        # Get content type
        content_type = response.headers.get('content-type', 'image/jpeg')
        if ';' in content_type:
            content_type = content_type.split(';')[0].strip()
        
        # Validate it's actually an image
        if not content_type.startswith('image/'):
            content_type = 'image/jpeg'  # Default fallback
        
        # Get raw image data
        image_data = response.content
        
        # Compress if too large (using lower threshold to account for base64 expansion)
        if len(image_data) > MAX_RAW_BYTES:
            image_data, content_type = compress_image(image_data, content_type)
        
        # Encode to base64
        img_data = base64.b64encode(image_data).decode('utf-8')
        
        # FINAL CHECK: Skip if still too large after base64 encoding
        if len(img_data) > MAX_BASE64_BYTES:
            logger.warning(f"[IMAGES] Image still too large after compression: {len(img_data)/1024/1024:.1f}MB base64, skipping")
            return FetchedImage(
                url=url, data="", media_type="",
                success=False, error="Too large even after compression"
            )
        
        return FetchedImage(
            url=url,
            data=img_data,
            media_type=content_type,
            success=True
        )
        
    except httpx.TimeoutException:
        return FetchedImage(
            url=url, data="", media_type="",
            success=False, error="Timeout"
        )
    except httpx.HTTPStatusError as e:
        return FetchedImage(
            url=url, data="", media_type="",
            success=False, error=f"HTTP {e.response.status_code}"
        )
    except Exception as e:
        return FetchedImage(
            url=url, data="", media_type="",
            success=False, error=str(e)[:50]
        )


async def fetch_images_parallel(
    urls: List[str],
    max_images: int = None,
    timeout: float = None
) -> List[Dict[str, Any]]:
    """
    Fetch multiple images in parallel
    
    Returns list of Claude-compatible image dicts:
    [{"type": "image", "source": {"type": "base64", "media_type": "...", "data": "..."}}]
    """
    if not HTTPX_AVAILABLE:
        logger.warning("httpx not available, falling back to sync fetch")
        return await _fallback_sync_fetch(urls, max_images or DEFAULT_MAX_IMAGES)
    
    # Use provided max_images, or default to max_images_haiku from config, or fallback
    max_images = max_images or getattr(IMAGES, 'max_images_haiku', DEFAULT_MAX_IMAGES)
    timeout = timeout or getattr(IMAGES, 'timeout', 5.0)
    
    # Filter to valid URLs and limit count
    valid_urls = [
        url for url in urls[:max_images]
        if isinstance(url, str) and url.startswith('http')
    ]
    
    if not valid_urls:
        return []
    
    print(f"[IMAGES] Fetching {len(valid_urls)} images in parallel...")
    start_time = asyncio.get_event_loop().time()
    
    async with httpx.AsyncClient(
        headers={'User-Agent': getattr(IMAGES, 'user_agent', 'Mozilla/5.0')},
        follow_redirects=True,
        limits=httpx.Limits(max_connections=getattr(IMAGES, 'max_concurrent', 5))
    ) as client:
        # Create tasks for all images
        tasks = [
            fetch_single_image(client, url, timeout)
            for url in valid_urls
        ]
        
        # Wait for all with timeout
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    elapsed = asyncio.get_event_loop().time() - start_time
    
    # Convert to Claude format
    images = []
    success_count = 0
    skipped_count = 0
    
    for result in results:
        if isinstance(result, Exception):
            logger.debug(f"[IMAGES] Fetch exception: {result}")
            continue
        
        if result.success and result.data:
            images.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": result.media_type,
                    "data": result.data
                }
            })
            success_count += 1
        else:
            if "Too large" in str(result.error):
                skipped_count += 1
            logger.debug(f"[IMAGES] Failed: {result.url} - {result.error}")
    
    status = f"Fetched {success_count}/{len(valid_urls)} images in {elapsed:.2f}s"
    if skipped_count:
        status += f" ({skipped_count} skipped - too large)"
    logger.info(f"[IMAGES] {status}")
    
    return images


async def _fallback_sync_fetch(urls: List[str], max_images: int) -> List[Dict[str, Any]]:
    """Fallback synchronous fetch if httpx not available"""
    import urllib.request
    
    images = []
    for url in urls[:max_images]:
        if not isinstance(url, str) or not url.startswith('http'):
            continue
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': getattr(IMAGES, 'user_agent', 'Mozilla/5.0')}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                image_data = resp.read()
                content_type = resp.headers.get('Content-Type', 'image/jpeg')
                if ';' in content_type:
                    content_type = content_type.split(';')[0]
                
                # Compress if too large
                if len(image_data) > MAX_RAW_BYTES:
                    image_data, content_type = compress_image(image_data, content_type)
                
                # Encode to base64
                data = base64.b64encode(image_data).decode('utf-8')
                
                # Skip if still too large
                if len(data) > MAX_BASE64_BYTES:
                    logger.warning(f"[IMAGES] Skipping oversized image: {len(data)/1024/1024:.1f}MB")
                    continue
                    
                images.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": content_type,
                        "data": data
                    }
                })
        except Exception as e:
            logger.debug(f"[IMAGES] Sync fetch failed: {url} - {e}")
    
    return images


def parse_data_url(data_url: str) -> Optional[Dict[str, Any]]:
    """Parse a data URL (data:image/jpeg;base64,...) into Claude format"""
    try:
        if not data_url.startswith('data:'):
            return None
            
        header, base64_data = data_url.split(",", 1)
        media_type = header.split(":")[1].split(";")[0]
        
        # Check size
        if len(base64_data) > MAX_BASE64_BYTES:
            logger.warning(f"[IMAGES] Data URL too large: {len(base64_data)/1024/1024:.1f}MB")
            return None
        
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64_data
            }
        }
    except Exception as e:
        logger.warning(f"[IMAGES] Failed to parse data URL: {e}")
        return None


def resize_image(image_data: bytes, media_type: str, max_dimension: int = 512) -> Tuple[bytes, str]:
    """
    Resize image to max_dimension on longest side.
    This significantly reduces API latency and costs.
    
    Args:
        image_data: Raw image bytes
        media_type: MIME type (e.g., 'image/jpeg')
        max_dimension: Max pixels on longest side (default 512)
    
    Returns:
        (resized_data, media_type) - JPEG output for consistency
    """
    if not PIL_AVAILABLE:
        return image_data, media_type
    
    try:
        img = Image.open(io.BytesIO(image_data))
        
        # Check if resize needed
        if img.width <= max_dimension and img.height <= max_dimension:
            return image_data, media_type
        
        # Calculate new dimensions maintaining aspect ratio
        if img.width > img.height:
            new_width = max_dimension
            new_height = int(img.height * (max_dimension / img.width))
        else:
            new_height = max_dimension
            new_width = int(img.width * (max_dimension / img.height))
        
        # Convert to RGB if necessary (for JPEG output)
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Resize with high-quality resampling
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Save to JPEG with good quality
        output = io.BytesIO()
        resized.save(output, format='JPEG', quality=85, optimize=True)
        resized_data = output.getvalue()
        
        original_kb = len(image_data) / 1024
        new_kb = len(resized_data) / 1024
        logger.debug(f"[IMAGES] Resized {img.width}x{img.height} -> {new_width}x{new_height} ({original_kb:.0f}KB -> {new_kb:.0f}KB)")
        
        return resized_data, 'image/jpeg'
        
    except Exception as e:
        logger.warning(f"[IMAGES] Resize failed: {e}")
        return image_data, media_type


async def process_image_list(raw_images: List[Any], max_size: int = None, max_count: int = None, selection: str = "first") -> List[Dict[str, Any]]:
    """
    Process a mixed list of image URLs and data URLs
    Returns Claude-compatible image list
    
    Args:
        raw_images: List of HTTP URLs or data URLs
        max_size: Max dimension for resizing (None = no resize)
                  Use 512 for Haiku, 768 for Tier 2 Sonnet
        max_count: Max number of images to return (None = all)
        selection: Strategy for selecting images:
                   "first" - Take first N images (default)
                   "first_last" - Take first 3 + last 3 (good for eBay - scale photos often at end)
    """
    if not raw_images:
        return []
    
    http_urls = []
    data_images = []
    
    for img in raw_images:
        if isinstance(img, str):
            if img.startswith('http'):
                http_urls.append(img)
            elif img.startswith('data:'):
                parsed = parse_data_url(img)
                if parsed:
                    data_images.append(parsed)
    
    # Apply selection strategy to URLs before fetching
    original_count = len(http_urls)

    if selection == "first_last" and len(http_urls) > 6:
        # SMART IMAGE SELECTION for gold/silver
        # Scale photos are almost always at the END of eBay listings
        # Overview photo is first, detail shots in middle, scale at end

        if len(http_urls) >= 30:
            # Large listing (30+ images) - be more aggressive
            # Take first 2 (overview) + last 4 (likely scale photos)
            first_urls = http_urls[:2]
            last_urls = http_urls[-4:]
            http_urls = first_urls + last_urls
            logger.info(f"[IMAGES] Smart selection (large listing {original_count}): first 2 + last 4 = {len(http_urls)} images")
        elif len(http_urls) >= 15:
            # Medium listing (15-29 images) - prioritize last images more
            # Take first 2 (overview) + last 4 (likely scale photos)
            first_urls = http_urls[:2]
            last_urls = http_urls[-4:]
            http_urls = first_urls + last_urls
            logger.info(f"[IMAGES] Smart selection (medium listing {original_count}): first 2 + last 4 = {len(http_urls)} images")
        else:
            # Standard listing (7-14 images) - use original first_last
            first_urls = http_urls[:3]
            last_urls = http_urls[-3:]
            http_urls = first_urls + last_urls
            logger.info(f"[IMAGES] Using first_last strategy: {len(first_urls)} + {len(last_urls)} = {len(http_urls)} images")
    elif max_count and len(http_urls) > max_count:
        http_urls = http_urls[:max_count]
    
    # Fetch HTTP URLs in parallel
    fetched = await fetch_images_parallel(http_urls, max_images=len(http_urls))
    
    # Combine data URLs and fetched images
    all_images = data_images + fetched
    
    # Apply max_count to final result (if specified and not using first_last)
    if max_count and selection != "first_last" and len(all_images) > max_count:
        all_images = all_images[:max_count]
    
    # Resize images if max_size specified
    if max_size and PIL_AVAILABLE:
        resized_images = []
        for img in all_images:
            try:
                if img.get('source', {}).get('type') == 'base64':
                    # Decode, resize, re-encode
                    raw_data = base64.b64decode(img['source']['data'])
                    media_type = img['source'].get('media_type', 'image/jpeg')
                    
                    resized_data, new_media_type = resize_image(raw_data, media_type, max_size)
                    
                    resized_images.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": new_media_type,
                            "data": base64.b64encode(resized_data).decode('utf-8')
                        }
                    })
            except Exception as e:
                logger.warning(f"[IMAGES] Resize failed, keeping original: {e}")
                resized_images.append(img)
        
        return resized_images
    
    return all_images


# Synchronous wrapper for non-async contexts
def fetch_images_sync(urls: List[str], max_images: int = None) -> List[Dict[str, Any]]:
    """Synchronous wrapper for async image fetching"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(fetch_images_parallel(urls, max_images))
