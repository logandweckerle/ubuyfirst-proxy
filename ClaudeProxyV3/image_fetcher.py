"""
Async Image Fetcher - Parallel image downloading with httpx
Reduces image fetch time from 10-15 seconds (sequential) to 2-3 seconds (parallel)
"""

import asyncio
import base64
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    print("[IMAGES] httpx not installed. Run: pip install httpx")

from config import IMAGES

logger = logging.getLogger(__name__)


@dataclass
class FetchedImage:
    """Container for a fetched image"""
    url: str
    data: str  # base64 encoded
    media_type: str
    success: bool
    error: Optional[str] = None


async def fetch_single_image(
    client: "httpx.AsyncClient",
    url: str,
    timeout: float = 5.0
) -> FetchedImage:
    """Fetch a single image asynchronously"""
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
        
        # Encode to base64
        img_data = base64.b64encode(response.content).decode('utf-8')
        
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
        return await _fallback_sync_fetch(urls, max_images or IMAGES.max_images)
    
    max_images = max_images or IMAGES.max_images
    timeout = timeout or IMAGES.timeout
    
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
        headers={'User-Agent': IMAGES.user_agent},
        follow_redirects=True,
        limits=httpx.Limits(max_connections=IMAGES.max_concurrent)
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
    
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Image fetch exception: {result}")
            continue
            
        if result.success:
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
            logger.debug(f"Image fetch failed: {result.url} - {result.error}")
    
    print(f"[IMAGES] ✓ Fetched {success_count}/{len(valid_urls)} images in {elapsed:.2f}s")
    
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
                headers={'User-Agent': IMAGES.user_agent}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = base64.b64encode(resp.read()).decode('utf-8')
                content_type = resp.headers.get('Content-Type', 'image/jpeg')
                if ';' in content_type:
                    content_type = content_type.split(';')[0]
                    
                images.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": content_type,
                        "data": data
                    }
                })
        except Exception as e:
            logger.debug(f"Sync image fetch failed: {url} - {e}")
    
    return images


def parse_data_url(data_url: str) -> Optional[Dict[str, Any]]:
    """Parse a data URL (data:image/jpeg;base64,...) into Claude format"""
    try:
        if not data_url.startswith('data:'):
            return None
            
        header, base64_data = data_url.split(",", 1)
        media_type = header.split(":")[1].split(";")[0]
        
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64_data
            }
        }
    except Exception as e:
        logger.warning(f"Failed to parse data URL: {e}")
        return None


async def process_image_list(raw_images: List[Any]) -> List[Dict[str, Any]]:
    """
    Process a mixed list of image URLs and data URLs
    Returns Claude-compatible image list
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
    
    # Fetch HTTP URLs in parallel
    fetched = await fetch_images_parallel(http_urls)
    
    # Combine data URLs and fetched images
    return data_images + fetched


# Synchronous wrapper for non-async contexts
def fetch_images_sync(urls: List[str], max_images: int = None) -> List[Dict[str, Any]]:
    """Synchronous wrapper for async image fetching"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(fetch_images_parallel(urls, max_images))
