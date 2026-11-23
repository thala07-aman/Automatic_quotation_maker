"""
Image Fetcher for Travel Destinations
Fetches images from Unsplash / Pexels (if API keys are set), then Wikipedia
(free, no key), optionally falling back to OpenAI image generation.
"""

import requests
import io
import hashlib
from PIL import Image, ImageStat
import os
import time
from typing import Optional, Dict, List, Tuple
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Image API configuration
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
UNSPLASH_API_URL = "https://api.unsplash.com/search/photos"

WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
# Wikimedia requires a descriptive User-Agent
WIKIPEDIA_HEADERS = {"User-Agent": "TornadoIndiaQuotationMaker/1.0 (travel quotation PDFs)"}

# OpenAI image generation is a paid fallback, so it is opt-in:
# set OPENAI_IMAGE_FALLBACK=true in .env to enable it.
OPENAI_IMAGE_FALLBACK = os.getenv("OPENAI_IMAGE_FALLBACK", "").lower() in ("1", "true", "yes")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1-mini")

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PEXELS_API_URL = "https://api.pexels.com/v1/search"

# Fallback: Use placeholder images if API key not available
PLACEHOLDER_IMAGE_URL = "https://via.placeholder.com/800x600/4A4A4A/FFFFFF?text="


# ---------------------------------------------------------------------------
# Image quality check + cache
# ---------------------------------------------------------------------------
MIN_IMAGE_WIDTH = 400
MIN_IMAGE_HEIGHT = 250
MIN_IMAGE_CONTRAST = 10.0   # grayscale std-dev; a blank / single-colour image is ~0

FOUND_TTL = 86400           # keep real photos for 24 hours
MISSING_TTL = 900           # retry "not found" after 15 minutes (it may have been a throttled request)

# Only successes live long. st.cache_data used to cache failures (and placeholders) for a whole day.
_IMAGE_CACHE: Dict[tuple, Tuple[float, Optional[bytes]]] = {}


def is_usable_image(data: Optional[bytes]) -> bool:
    """True if `data` is a decodable photo that is big enough and not blank / a flat colour."""
    if not data:
        return False
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return False
    if img.width < MIN_IMAGE_WIDTH or img.height < MIN_IMAGE_HEIGHT:
        return False
    try:
        small = img.convert("L").resize((64, 64))
        return ImageStat.Stat(small).stddev[0] >= MIN_IMAGE_CONTRAST
    except Exception:
        return False


def _search_providers(city: str, landmark: Optional[str]) -> Optional[bytes]:
    """Try each configured image source in turn; return the first usable photo, or None."""
    if landmark:
        query = f"{landmark} {city} travel"
    else:
        query = f"{city} travel destination"

    providers = []
    if UNSPLASH_ACCESS_KEY:
        providers.append(("Unsplash", lambda: fetch_from_unsplash(query)))
    if PEXELS_API_KEY:
        providers.append(("Pexels", lambda: fetch_from_pexels(query)))
    providers.append(("Wikipedia", lambda: fetch_from_wikipedia(landmark, city)))
    if OPENAI_IMAGE_FALLBACK and os.getenv("OPENAI_API_KEY"):
        providers.append(("OpenAI", lambda: fetch_from_openai(landmark, city)))

    for name, fetch in providers:
        try:
            img = fetch()
        except Exception as e:
            print(f"{name} image error for '{query}': {e}")
            continue
        if is_usable_image(img):
            return img
        if img:
            print(f"{name} returned an unusable image for '{query}', trying next source")
    return None


def get_real_image(city: str, landmark: Optional[str] = None) -> Optional[bytes]:
    """
    A real, usable photo for a landmark (or the city if `landmark` is None), or None.
    Never returns a placeholder, so callers can pick a different place instead.
    """
    key = (city.strip().lower(), (landmark or "").strip().lower())
    hit = _IMAGE_CACHE.get(key)
    if hit:
        stamp, data = hit
        if time.time() - stamp < (FOUND_TTL if data else MISSING_TTL):
            return data

    data = _search_providers(city, landmark)
    _IMAGE_CACHE[key] = (time.time(), data)
    return data


def fetch_destination_image(city: str, landmark: str = None) -> bytes:
    """Real photo if one can be found, otherwise a text placeholder (legacy behaviour)."""
    return get_real_image(city, landmark) or fetch_placeholder_image(city, landmark)


def fetch_from_unsplash(query: str) -> Optional[bytes]:
    """Fetch image from Unsplash API"""
    
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    params = {"query": query, "per_page": 1, "orientation": "landscape"}
    
    try:
        response = requests.get(UNSPLASH_API_URL, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            results = response.json().get("results")
            if results:
                # 'regular' is ~1080px wide, plenty for the PDF
                img_response = requests.get(results[0]["urls"]["regular"], timeout=10)
                if img_response.status_code == 200:
                    return img_response.content
        else:
            print(f"Unsplash API returned {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"Unsplash API error: {e}")
    
    return None


_last_wikimedia_call = 0.0
WIKIMEDIA_MIN_INTERVAL = 1.0  # seconds between requests; Wikimedia returns 429 on bursts


def _wikimedia_get(url: str, params: dict = None, attempts: int = 4) -> Optional[requests.Response]:
    """GET from Wikimedia, spaced out and retried with backoff when throttled (429) or on 5xx."""
    global _last_wikimedia_call
    for attempt in range(attempts):
        wait_for = WIKIMEDIA_MIN_INTERVAL - (time.time() - _last_wikimedia_call)
        if wait_for > 0:
            time.sleep(wait_for)
        _last_wikimedia_call = time.time()
        try:
            response = requests.get(url, params=params, headers=WIKIPEDIA_HEADERS, timeout=10)
        except Exception as e:
            print(f"Wikimedia request error: {e}")
            response = None
        if response is not None and response.status_code == 200:
            return response
        if response is not None and response.status_code not in (429, 500, 502, 503, 504):
            print(f"Wikimedia returned {response.status_code} for {url[:80]}")
            return None
        if attempt < attempts - 1:
            wait = float(response.headers.get("Retry-After", 0)) if response is not None else 0
            time.sleep(min(max(wait, 1.5 * (attempt + 1)), 5))
    print(f"Wikimedia request failed after {attempts} attempts: {url[:80]}")
    return None


def fetch_from_wikipedia(landmark: Optional[str], city: str) -> Optional[bytes]:
    """Fetch the lead image of the best-matching Wikipedia article (free, no API key).
    
    For a landmark, the article title must share a word with the landmark name
    (so "Banana Boat" doesn't return an unrelated festival), and low-resolution
    thumbnails are skipped. Returns None if nothing suitable is found, so the
    next fallback can run.
    """
    
    if landmark:
        searches = [f"{landmark} {city}", landmark]
        city_words = {w.lower() for w in city.split()}
        keywords = {w.lower().strip(".,'") for w in landmark.split() if len(w) > 2} - city_words
    else:
        searches = [city]
        keywords = set()
    
    for term in searches:
        try:
            params = {
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": term, "gsrlimit": 5,
                "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 1000,
            }
            response = _wikimedia_get(WIKIPEDIA_API_URL, params)
            if response is None:
                continue
            
            pages = response.json().get("query", {}).get("pages", {})
            # Best search matches first; skip pages without a photo
            for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
                thumbnail = page.get("thumbnail", {})
                thumb = thumbnail.get("source")
                if not thumb or thumb.lower().endswith(".svg") or thumbnail.get("width", 0) < 500:
                    continue
                title_words = [w.lower().strip(".,'()") for w in page["title"].split()]
                # exact word, or same 5-letter prefix for long words (spelling variants)
                if keywords and not any(
                    k == t or (len(k) >= 6 and len(t) >= 6 and k[:5] == t[:5])
                    for k in keywords for t in title_words
                ):
                    continue
                img_response = _wikimedia_get(thumb)
                if img_response is not None:
                    return img_response.content
        except Exception as e:
            print(f"Wikipedia API error for '{term}': {e}")
    
    return None


def fetch_from_openai(landmark: Optional[str], city: str) -> Optional[bytes]:
    """Generate a travel photo with the OpenAI Images API (paid, slow)."""
    import base64
    from openai import OpenAI
    
    subject = f"{landmark}, {city}" if landmark else city
    prompt = (
        f"A realistic, high-quality travel photograph of {subject}. "
        "Natural lighting, landscape orientation, no text, no watermarks, no people close-up."
    )
    
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        result = client.images.generate(
            model=OPENAI_IMAGE_MODEL, prompt=prompt, n=1, size="1536x1024"
        )
        item = result.data[0]
        # Depending on the model the API returns base64 data or a temporary URL
        if getattr(item, "b64_json", None):
            return base64.b64decode(item.b64_json)
        if getattr(item, "url", None):
            resp = requests.get(item.url, timeout=30)
            if resp.status_code == 200:
                return resp.content
    except Exception as e:
        print(f"OpenAI image error: {e}")
    
    return None


def fetch_from_pexels(query: str) -> Optional[bytes]:
    """Fetch image from Pexels API"""
    
    headers = {
        "Authorization": PEXELS_API_KEY
    }
    
    params = {
        "query": query,
        "per_page": 1,
        "orientation": "landscape"
    }
    
    try:
        response = requests.get(PEXELS_API_URL, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get("photos") and len(data["photos"]) > 0:
                # Get the large size image URL
                image_url = data["photos"][0]["src"]["large"]
                
                # Download the image
                img_response = requests.get(image_url, timeout=10)
                
                if img_response.status_code == 200:
                    return img_response.content
    except Exception as e:
        print(f"Pexels API error: {e}")
    
    return None


def fetch_placeholder_image(city: str, landmark: str = None) -> bytes:
    """
    Generate a simple placeholder image with text.
    This is a fallback when API is not available.
    """
    from PIL import Image, ImageDraw, ImageFont
    
    # Create image
    width, height = 800, 600
    img = Image.new('RGB', (width, height), color=(74, 74, 74))
    draw = ImageDraw.Draw(img)
    
    # Add text
    text = landmark if landmark else city
    
    # Try to use a nice font, fallback to default
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 60)
    except:
        font = ImageFont.load_default()
    
    # Center text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    position = ((width - text_width) // 2, (height - text_height) // 2)
    draw.text(position, text, fill=(255, 255, 255), font=font)
    
    # Convert to bytes
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=85)
    return buffer.getvalue()


def resize_image_for_pdf(image_bytes: bytes, max_width: int = 344, max_height: int = 224) -> bytes:
    """
    Resize image to fit PDF layout (9.1 cm width × 5.93 cm height).
    
    Args:
        image_bytes: Original image bytes
        max_width: Maximum width in pixels (344px = 9.1cm)
        max_height: Maximum height in pixels (224px = 5.93cm)
        
    Returns:
        Resized image bytes
    """
    try:
        # Open image
        img = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # Calculate new size maintaining aspect ratio
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        
        # Save to bytes
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        return buffer.getvalue()
        
    except Exception as e:
        print(f"Error resizing image: {e}")
        return image_bytes


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_city_images(city: str, num_images: int = 2) -> Dict[str, bytes]:
    """
    Fetch multiple images for a city (overview and landmarks).
    
    Args:
        city: City name
        num_images: Number of images to fetch
        
    Returns:
        Dictionary with image types as keys and image bytes as values
    """
    images = {}
    
    # Fetch city overview image
    overview_img = fetch_destination_image(city)
    if overview_img:
        images['overview'] = resize_image_for_pdf(overview_img)
    
    # Fetch landmark image if requested
    if num_images > 1:
        landmark_img = fetch_destination_image(city, f"{city} landmark")
        if landmark_img:
            images['landmark'] = resize_image_for_pdf(landmark_img)
    
    return images


def new_image_tracker() -> Dict[str, set]:
    """Tracks which places / photos were already used in one PDF, so substitutes aren't repeated."""
    return {"names": set(), "hashes": set()}


def pick_day_images(city: str, preferred: List[str], alternates: Optional[List[str]] = None,
                    used: Optional[Dict[str, set]] = None, count: int = 2,
                    max_attempts: int = 8) -> List[Tuple[str, bytes]]:
    """
    Choose up to `count` photos for one itinerary day.

    1. The day's own landmarks (`preferred`) are tried first.
    2. If one has no usable photo, other places from the city (`alternates`) are tried, skipping
       places and photos already used elsewhere in the PDF.
    3. As a last resort the city's overview photo is used.

    Returns [(place_name, jpeg_bytes), ...], possibly fewer than `count`. Never contains placeholders.
    """
    used = used if used is not None else new_image_tracker()

    candidates = [(n, n, True) for n in preferred if n]
    candidates += [(n, n, False) for n in (alternates or []) if n]
    candidates.append((city, None, False))      # city overview photo

    chosen: List[Tuple[str, bytes]] = []
    day_names, day_hashes = set(), set()
    attempts = 0

    for name, landmark, is_preferred in candidates:
        if len(chosen) >= count or attempts >= max_attempts:
            break
        name_key = name.strip().lower()
        if name_key in day_names:
            continue
        if not is_preferred and name_key in used["names"]:
            continue

        attempts += 1
        raw = get_real_image(city, landmark)
        if not raw:
            print(f"No usable image for '{name}' ({city}), trying another place")
            continue

        digest = hashlib.md5(raw).hexdigest()
        if digest in day_hashes or (not is_preferred and digest in used["hashes"]):
            continue

        chosen.append((name, resize_image_for_pdf(raw)))
        day_names.add(name_key)
        day_hashes.add(digest)
        used["names"].add(name_key)
        used["hashes"].add(digest)

    if preferred and chosen and [n for n, _ in chosen] != list(preferred)[:len(chosen)]:
        print(f"Image substitution in {city}: wanted {list(preferred)}, using {[n for n, _ in chosen]}")
    return chosen


def fetch_day_images_from_landmarks(city: str, landmarks: list, alternates: Optional[list] = None,
                                    used: Optional[Dict[str, set]] = None) -> dict:
    """
    Fetch up to 2 images for a day. If a landmark has no usable photo, another place from
    `alternates` (or the city overview) is used instead.

    Returns {'image1', 'landmark1_name', 'image2', 'landmark2_name'}; keys are missing for any
    slot that could not be filled.
    """
    images = {}
    for i, (name, data) in enumerate(pick_day_images(city, landmarks, alternates, used), start=1):
        images[f'image{i}'] = data
        images[f'landmark{i}_name'] = name
    return images


def setup_unsplash_api():
    """
    Setup instructions for Image APIs.
    Call this to display setup info in Streamlit.
    """
    st.info("""
    ### 🖼️ Image Feature Setup (Optional)
    
    To enable automatic destination images in PDFs, choose one or both:
    
    **Option 1: Pexels (Recommended for landmarks)**
    1. Get a free API key from: https://www.pexels.com/api/
    2. Add to your `.env` file:
       ```
       PEXELS_API_KEY=your_api_key_here
       ```
    
    **Option 2: Unsplash**
    1. Get a free API key from: https://unsplash.com/developers
    2. Add to your `.env` file:
       ```
       UNSPLASH_ACCESS_KEY=your_access_key_here
       ```
    
    **Benefits:**
    - Pexels: Excellent landmark and travel photos, easier setup
    - Unsplash: High-quality artistic photos
    - Use both for better coverage (Unsplash tried first, then Pexels)
    
    3. Restart the application
    
    **Note**: Without an API key, placeholder images will be used.
    """)

