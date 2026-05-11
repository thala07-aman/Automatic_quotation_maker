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

# Image API configuration
# UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
# UNSPLASH_API_URL = "https://api.unsplash.com/search/photos"

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PEXELS_API_URL = "https://api.pexels.com/v1/search"

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
        # Try Pexels first (better for landmarks), then Unsplash
        if PEXELS_API_KEY:
            img = fetch_from_pexels(query)
            if img:
                return img
        
        
        # Fallback to placeholder
        return fetch_placeholder_image(city, landmark)
            
    except Exception as e:
        print(f"Error fetching image for {query}: {e}")
        return fetch_placeholder_image(city, landmark)


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


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_day_images_from_landmarks(city: str, landmarks: list) -> Dict[str, bytes]:
    """
    Fetch 2 images for specific landmarks mentioned in the day's itinerary.
    
    Args:
        city: City name
        landmarks: List of 2 landmark names from the itinerary
        
    Returns:
        Dictionary with 'image1' and 'image2' keys containing image bytes
    """
    images = {}
    
    # Fetch first landmark image
    if landmarks and len(landmarks) > 0:
        landmark1 = landmarks[0]
        img1 = fetch_destination_image(city, landmark1)
        if img1:
            images['image1'] = resize_image_for_pdf(img1)
            images['landmark1_name'] = landmark1
    
    # Fetch second landmark image
    if landmarks and len(landmarks) > 1:
        landmark2 = landmarks[1]
        img2 = fetch_destination_image(city, landmark2)
        if img2:
            images['image2'] = resize_image_for_pdf(img2)
            images['landmark2_name'] = landmark2
    
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
    - Use both for better coverage (Pexels tried first)
    
    3. Restart the application
    
    **Note**: Without an API key, placeholder images will be used.
    """)

