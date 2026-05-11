"""
Image Fetcher for Travel Destinations
Fetches royalty-free images from Unsplash API
"""

import requests
import io
from PIL import Image
import os
from typing import Optional, Dict
import streamlit as st

# Unsplash API configuration
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
UNSPLASH_API_URL = "https://api.unsplash.com/search/photos"

# Fallback: Use placeholder images if API key not available
PLACEHOLDER_IMAGE_URL = "https://via.placeholder.com/800x600/4A4A4A/FFFFFF?text="


@st.cache_data(ttl=86400, show_spinner=False)  # Cache for 24 hours
def fetch_destination_image(city: str, landmark: str = None) -> Optional[bytes]:
    """
    Fetch a high-quality image for a destination or landmark.
    
    Args:
        city: City name
        landmark: Optional specific landmark name
        
    Returns:
        Image bytes or None if fetch fails
    """
    
    # Build search query
    if landmark:
        query = f"{landmark} {city} travel"
    else:
        query = f"{city} travel destination"
    
    try:
        # Try Unsplash API if key is available
        if UNSPLASH_ACCESS_KEY:
            return fetch_from_unsplash(query)
        else:
            # Fallback to placeholder
            return fetch_placeholder_image(city, landmark)
            
    except Exception as e:
        print(f"Error fetching image for {query}: {e}")
        return fetch_placeholder_image(city, landmark)


def fetch_from_unsplash(query: str) -> Optional[bytes]:
    """Fetch image from Unsplash API"""
    
    headers = {
        "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"
    }
    
    params = {
        "query": query,
        "per_page": 1,
        "orientation": "landscape",
        "content_filter": "high"
    }
    
    response = requests.get(UNSPLASH_API_URL, headers=headers, params=params, timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        
        if data.get("results") and len(data["results"]) > 0:
            # Get the regular size image URL
            image_url = data["results"][0]["urls"]["regular"]
            
            # Download the image
            img_response = requests.get(image_url, timeout=10)
            
            if img_response.status_code == 200:
                return img_response.content
    
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


def resize_image_for_pdf(image_bytes: bytes, max_width: int = 500, max_height: int = 375) -> bytes:
    """
    Resize image to fit PDF layout while maintaining aspect ratio.
    
    Args:
        image_bytes: Original image bytes
        max_width: Maximum width in pixels
        max_height: Maximum height in pixels
        
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


def setup_unsplash_api():
    """
    Setup instructions for Unsplash API.
    Call this to display setup info in Streamlit.
    """
    st.info("""
    ### 🖼️ Image Feature Setup (Optional)
    
    To enable automatic destination images in PDFs:
    
    1. Get a free Unsplash API key from: https://unsplash.com/developers
    2. Add to your `.env` file:
       ```
       UNSPLASH_ACCESS_KEY=your_access_key_here
       ```
    3. Restart the application
    
    **Note**: Without an API key, placeholder images will be used.
    """)

# Made with Bob
