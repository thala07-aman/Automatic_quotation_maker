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
from typing import Any, Optional, Dict, List, Tuple
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
MIN_IMAGE_WIDTH = 800
MIN_IMAGE_HEIGHT = 500
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


def _search_providers(city: str, landmark: Optional[str], must: bool = False) -> Optional[bytes]:
    """Try each configured image source in turn; return the first usable photo, or None.

    `must=True` (places the client asked for in the notes) adds extra, looser attempts after
    the normal strict ones: Unsplash matching on any keyword, Commons by the landmark name
    alone, then Pexels.
    """
    if landmark:
        query = f"{landmark} {city} travel"
    else:
        query = f"{city} travel destination"

    # Order: Unsplash -> Wikipedia -> Commons -> Pexels -> OpenAI (each only if configured)
    providers = []
    if UNSPLASH_ACCESS_KEY:
        providers.append(("Unsplash", lambda: fetch_from_unsplash(landmark, city)))
    providers.append(("Wikipedia", lambda: fetch_from_wikipedia(landmark, city)))
    providers.append(("Commons", lambda: fetch_from_commons(landmark, city)))
    if must and landmark:
        if UNSPLASH_ACCESS_KEY:
            providers.append(("Unsplash (relaxed)", lambda: fetch_from_unsplash(landmark, city, relaxed=True)))
        providers.append(("Commons (name only)", lambda: fetch_from_commons(landmark, city, name_only=True)))
    if PEXELS_API_KEY:
        providers.append(("Pexels", lambda: fetch_from_pexels(query)))
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


def get_real_image(city: str, landmark: Optional[str] = None, must: bool = False) -> Optional[bytes]:
    """
    A real, usable photo for a landmark (or the city if `landmark` is None), or None.
    Never returns a placeholder, so callers can pick a different place instead.
    `must=True` searches harder (see `_search_providers`).
    """
    key = (city.strip().lower(), (landmark or "").strip().lower(), must)
    hit = _IMAGE_CACHE.get(key)
    if hit:
        stamp, data = hit
        if time.time() - stamp < (FOUND_TTL if data else MISSING_TTL):
            return data

    data = _search_providers(city, landmark, must)
    _IMAGE_CACHE[key] = (time.time(), data)
    return data


def fetch_destination_image(city: str, landmark: str = None) -> bytes:
    """Real photo if one can be found, otherwise a text placeholder (legacy behaviour)."""
    return get_real_image(city, landmark) or fetch_placeholder_image(city, landmark)


def _unsplash_text(photo: dict) -> str:
    """All descriptive text Unsplash has for a photo, lower-cased."""
    parts = [photo.get("description"), photo.get("alt_description"), photo.get("slug")]
    parts += [t.get("title") for t in photo.get("tags") or []]
    location = (photo.get("location") or {})
    parts += [location.get("name"), location.get("city")]
    return " ".join(p for p in parts if p).lower().replace("-", " ")


def fetch_from_unsplash(landmark: Optional[str], city: str, relaxed: bool = False) -> Optional[bytes]:
    """Fetch a photo from Unsplash that is actually of the place.

    Unsplash search is fuzzy, so the top results are checked: a photo is only accepted if its
    description/tags mention every word of the landmark name (or the city name for the city
    overview). Otherwise None is returned and the next source (Wikipedia) is tried.
    `relaxed=True` accepts a photo that mentions any one distinctive word of the name.
    """
    if landmark:
        query = f"{landmark} {city}"
        city_words = {w.lower() for w in city.split()}
        required = {w.lower().strip(".,'()") for w in landmark.split() if len(w) > 2} - city_words
        required = required or {w.lower().strip(".,'()") for w in landmark.split() if len(w) > 2}
    else:
        query = city
        required = {w.lower().strip(".,'()") for w in city.split() if len(w) > 2}

    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    params = {"query": query, "per_page": 10, "orientation": "landscape"}

    try:
        response = requests.get(UNSPLASH_API_URL, headers=headers, params=params, timeout=10)
        if response.status_code != 200:
            print(f"Unsplash API returned {response.status_code}: {response.text[:200]}")
            return None

        for photo in response.json().get("results") or []:
            text = _unsplash_text(photo)
            matches = any if relaxed else all
            if required and not matches(k in text for k in required):
                continue
            # 'raw' + w=1600 gives a sharp image that still prints well at 3.6 in wide
            img_response = requests.get(f"{photo['urls']['raw']}&w=1600&q=85&fit=max", timeout=15)
            if img_response.status_code == 200:
                return img_response.content
        print(f"Unsplash has no matching photo for '{query}', falling back")
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
                "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 1600,
            }
            response = _wikimedia_get(WIKIPEDIA_API_URL, params)
            if response is None:
                continue
            
            pages = response.json().get("query", {}).get("pages", {})
            # Best search matches first; skip pages without a photo
            for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
                thumbnail = page.get("thumbnail", {})
                thumb = thumbnail.get("source")
                if not thumb or thumb.lower().endswith(".svg") or thumbnail.get("width", 0) < MIN_IMAGE_WIDTH:
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


_COMMONS_SKIP_WORDS = ("map", "logo", "flag", "coat of arms", "diagram", "plan", "locator", "seal", "poster")


def fetch_from_commons(landmark: Optional[str], city: str, name_only: bool = False) -> Optional[bytes]:
    """Search Wikimedia Commons (free, no key) for a large landscape photo of the place.

    Covers places whose Wikipedia article has no (or only a tiny) lead image. Only JPEGs at
    least 1600px wide, landscape, whose file name mentions the place are accepted.
    `name_only=True` searches the landmark name without the city (for places filed under a
    different city / region name on Commons).
    """
    subject = landmark or city
    city_words = {w.lower() for w in city.split()}
    keywords = {w.lower().strip(".,'()") for w in subject.split() if len(w) > 2} - (city_words if landmark else set())
    if not keywords:
        keywords = {w.lower() for w in subject.split() if len(w) > 2}

    term = f"{landmark} {city}" if landmark and not name_only else subject
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{term} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 12,
        "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": 1600,
    }
    response = _wikimedia_get("https://commons.wikimedia.org/w/api.php", params)
    if response is None:
        return None

    pages = response.json().get("query", {}).get("pages", {})
    for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        info = (page.get("imageinfo") or [{}])[0]
        title = page.get("title", "").lower()
        width, height = info.get("width", 0), info.get("height", 0)
        if info.get("mime") != "image/jpeg" or width < 1600 or width < height * 1.2:
            continue
        if any(bad in title for bad in _COMMONS_SKIP_WORDS):
            continue
        if not any(k in title for k in keywords):
            continue
        img_response = _wikimedia_get(info.get("thumburl") or info["url"])
        if img_response is not None:
            return img_response.content
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
                image_url = data["photos"][0]["src"]["large2x"]
                
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


def resize_image_for_pdf(image_bytes: bytes, max_width: int = 1100, max_height: int = 716) -> bytes:
    """
    Resize image to fit PDF layout (9.1 cm width × 5.93 cm height) at ~300 DPI.
    
    Args:
        image_bytes: Original image bytes
        max_width: Maximum width in pixels (1100px = 9.1cm at ~300 DPI)
        max_height: Maximum height in pixels (716px = 5.93cm at ~300 DPI)
        
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
        img.save(buffer, format='JPEG', quality=90)
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


DUPLICATE_HASH_DISTANCE = 5     # differing bits (of 64) at or below which two photos count as the same picture


def _dhash(data: bytes) -> Optional[int]:
    """64-bit perceptual hash: equal for the same picture even if resized / re-compressed / re-cropped a little."""
    try:
        img = Image.open(io.BytesIO(data)).convert("L").resize((9, 8))
    except Exception:
        return None
    px = list(img.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def _is_duplicate(digest: str, phash: Optional[int], seen_hashes: set, seen_phashes: list) -> bool:
    if digest in seen_hashes:
        return True
    return phash is not None and any(bin(phash ^ p).count("1") <= DUPLICATE_HASH_DISTANCE for p in seen_phashes)


def new_image_tracker() -> Dict[str, Any]:
    """Tracks which places / photos were already used in one PDF, so nothing is shown twice."""
    return {"names": set(), "hashes": set(), "phashes": []}


def pick_day_images(city: str, preferred: List[str], alternates: Optional[List[str]] = None,
                    used: Optional[Dict[str, Any]] = None, count: int = 2,
                    max_attempts: int = 10, must: Optional[List[str]] = None) -> List[Tuple[str, bytes]]:
    """
    Choose up to `count` photos for one itinerary day.

    0. `must` places (requested by the client in the notes) are searched with every source,
       including the looser ones, and are always tried first.
    1. The day's own landmarks (`preferred`) are tried first.
    2. If one has no usable photo, other places from the city (`alternates`) are tried.
    3. As a last resort the city's overview photo is used.

    A place or a picture that was already used anywhere in the PDF (`used`) is never used again,
    even under a different name or at a different size. Fewer than `count` photos is fine.

    Returns [(place_name, jpeg_bytes), ...]. Never contains placeholders.
    """
    used = used if used is not None else new_image_tracker()
    must_keys = {m.strip().lower() for m in (must or [])}
    # places the client asked for come first; only the extra tries for them don't count as attempts
    preferred = sorted([p for p in preferred if p], key=lambda p: p.strip().lower() not in must_keys)
    max_attempts += sum(1 for p in preferred if p.strip().lower() in must_keys)

    candidates = [(n, n, True) for n in preferred if n]
    candidates += [(n, n, False) for n in (alternates or []) if n]
    candidates.append((city, None, False))      # city overview photo

    chosen: List[Tuple[str, bytes]] = []
    day_names = set()
    attempts = 0

    for name, landmark, is_preferred in candidates:
        if len(chosen) >= count or attempts >= max_attempts:
            break
        name_key = name.strip().lower()
        used_key = f"{city.strip().lower()}|{name_key}"     # "City Palace" exists in many cities
        if name_key in day_names or used_key in used["names"]:
            continue

        attempts += 1
        raw = get_real_image(city, landmark, must=name_key in must_keys)
        if not raw:
            print(f"No usable image for '{name}' ({city}), trying another place")
            continue

        digest = hashlib.md5(raw).hexdigest()
        phash = _dhash(raw)
        if _is_duplicate(digest, phash, used["hashes"], used["phashes"]):
            print(f"Photo for '{name}' ({city}) was already used in this PDF, trying another place")
            continue

        chosen.append((name, resize_image_for_pdf(raw)))
        day_names.add(name_key)
        used["names"].add(used_key)
        used["hashes"].add(digest)
        if phash is not None:
            used["phashes"].append(phash)

    if preferred and chosen and [n for n, _ in chosen] != list(preferred)[:len(chosen)]:
        print(f"Image substitution in {city}: wanted {list(preferred)}, using {[n for n, _ in chosen]}")
    return chosen


def fetch_day_images_from_landmarks(city: str, landmarks: list, alternates: Optional[list] = None,
                                    used: Optional[Dict[str, Any]] = None,
                                    must: Optional[list] = None) -> dict:
    """
    Fetch up to 2 images for a day. `must` places (from the client's notes) take the slots first.
    If a landmark has no usable photo, another place from `alternates` (or the city overview)
    is used instead.

    Returns {'image1', 'landmark1_name', 'image2', 'landmark2_name'}; keys are missing for any
    slot that could not be filled.
    """
    images = {}
    for i, (name, data) in enumerate(pick_day_images(city, landmarks, alternates, used, must=must), start=1):
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

