"""
Professional PDF Generator for Travel Quotations
Supports custom branding, images, and styled layouts
"""

import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image as RLImage, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io
from image_fetcher import fetch_city_images, new_image_tracker


PAGE_W, PAGE_H = letter  # 612 x 792 pt, same as the reference PDF
ORANGE = colors.HexColor('#F79646')   # title / tagline / watermark
RED = colors.HexColor('#C0504D')      # contact line

# Header geometry (pt from top of page), measured from the reference PDF
BORDER_INSET = 24          # black page border, 1pt, 24pt from every edge
TITLE_SIZE = 48            # Georgia Bold
TITLE_BASELINE_Y = 118
TAGLINE_RIGHT_X = 530
TAGLINE_BASELINE_Y = 143.5
TAGLINE_WIDTH = 135        # width of the tagline text in the reference
CONTACT_X = 36
CONTACT_BASELINE_Y = 158
CONTACT_WIDTH = 356        # width of the contact line in the reference
RULE_Y = 167               # thick rule under the header
FIRST_PAGE_BODY_Y = 180    # where "Dear ..." starts on page 1
TOP_MARGIN = 70


def _register_fonts():
    """Register Georgia Bold / Trebuchet if installed, else fall back to built-ins."""
    dirs = [
        '/System/Library/Fonts/Supplemental',
        '/Library/Fonts',
        'C:/Windows/Fonts',
        '/usr/share/fonts/truetype/msttcorefonts',
    ]
    wanted = {
        'Georgia-Bold': ('Georgia Bold.ttf', 'georgiab.ttf', 'Georgia_Bold.ttf'),
        'Trebuchet': ('Trebuchet MS.ttf', 'trebuc.ttf'),
        'Trebuchet-Bold': ('Trebuchet MS Bold.ttf', 'trebucbd.ttf'),
    }
    found = {}
    for name, files in wanted.items():
        for d in dirs:
            for f in files:
                path = os.path.join(d, f)
                if os.path.exists(path):
                    try:
                        pdfmetrics.registerFont(TTFont(name, path))
                        found[name] = name
                    except Exception:
                        pass
                    break
            if name in found:
                break
    return {
        'title': found.get('Georgia-Bold', 'Times-Bold'),
        'body': found.get('Trebuchet', 'Helvetica'),
        'body_bold': found.get('Trebuchet-Bold', 'Helvetica-Bold'),
    }


FONTS = _register_fonts()


def _fit_font_size(text, font, target_width):
    """Font size at which `text` is `target_width` pt wide."""
    return target_width / pdfmetrics.stringWidth(text, font, 1)


class BrandedCanvas(canvas.Canvas):
    """Custom canvas: page border, first-page header, outline watermark, page numbers.

    The border/header/watermark are drawn by draw_page_background() at the START
    of each page (so images and text sit on top of the watermark); only the page
    number is drawn here at the end of the page.
    """
    
    def __init__(self, *args, **kwargs):
        self.watermark_text = kwargs.pop('watermark_text', None)
        self.header = kwargs.pop('header', None)
        canvas.Canvas.__init__(self, *args, **kwargs)

    def _draw_border(self):
        self.setStrokeColor(colors.black)
        self.setLineWidth(1)
        self.rect(BORDER_INSET, BORDER_INSET,
                  PAGE_W - 2 * BORDER_INSET, PAGE_H - 2 * BORDER_INSET)

    def _draw_header(self):
        h = self.header
        # Title
        self.setFillColor(ORANGE)
        self.setFont(FONTS['title'], TITLE_SIZE)
        self.drawCentredString(PAGE_W / 2, PAGE_H - TITLE_BASELINE_Y, h['name'])
        # Tagline (right aligned, under the title)
        tag_font = 'Helvetica-Bold'
        self.setFont(tag_font, _fit_font_size(h['tagline'], tag_font, TAGLINE_WIDTH))
        self.drawRightString(TAGLINE_RIGHT_X, PAGE_H - TAGLINE_BASELINE_Y, h['tagline'])
        # Contact line
        contact = f"{h['email']}/{h['website']}/{h['phone']}"
        self.setFillColor(RED)
        self.setFont(tag_font, _fit_font_size(contact, tag_font, CONTACT_WIDTH))
        self.drawString(CONTACT_X, PAGE_H - CONTACT_BASELINE_Y, contact)
        # Thick rule
        self.setStrokeColor(colors.black)
        self.setLineWidth(2)
        self.line(BORDER_INSET, PAGE_H - RULE_Y, PAGE_W - BORDER_INSET, PAGE_H - RULE_Y)

    def _draw_watermark(self):
        self.saveState()
        self.translate(PAGE_W / 2, PAGE_H / 2)
        self.rotate(42)
        font = FONTS['title']
        size = _fit_font_size(self.watermark_text, font, 347)
        width = pdfmetrics.stringWidth(self.watermark_text, font, size)
        txt = self.beginText(-width / 2, -size * 0.3)
        txt.setFont(font, size)
        txt.setTextRenderMode(1)  # outline only
        self.setStrokeColor(ORANGE)
        self.setLineWidth(1)
        txt.textOut(self.watermark_text)
        self.drawText(txt)
        self.restoreState()
        
    def draw_page_background(self):
        """Draw everything that must sit BEHIND the page content."""
        self.saveState()
        self._draw_border()
        if self.header and self.getPageNumber() == 1:
            self._draw_header()
        if self.watermark_text:
            self._draw_watermark()
        self.restoreState()

    def showPage(self):
        self.saveState()
        
        # Add page number (inside the border)
        self.setFont('Helvetica', 9)
        self.setFillColorRGB(0.5, 0.5, 0.5)
        self.drawRightString(PAGE_W - BORDER_INSET - 10, BORDER_INSET + 8,
                             f"Page {self.getPageNumber()}")
        
        self.restoreState()
        canvas.Canvas.showPage(self)


def _draw_background(canv, doc):
    """Page-start callback: runs before the flowables, so it is drawn underneath them."""
    canv.draw_page_background()


def create_custom_styles():
    """Create custom paragraph styles for professional look"""
    styles = getSampleStyleSheet()
    
    # Company Header Style
    styles.add(ParagraphStyle(
        name='CompanyHeader',
        parent=styles['Heading1'],
        fontSize=32,
        textColor=colors.HexColor('#D2691E'),  # Orange/Brown
        alignment=TA_CENTER,
        spaceAfter=6,
        fontName='Helvetica-Bold'
    ))
    
    # Tagline Style
    styles.add(ParagraphStyle(
        name='Tagline',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#D2691E'),
        alignment=TA_RIGHT,
        fontName='Helvetica-Bold'
    ))
    
    # Contact Info Style
    styles.add(ParagraphStyle(
        name='ContactInfo',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.white,
        alignment=TA_CENTER,
        fontName='Helvetica'
    ))
    
    # Section Header Style
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#D2691E'),
        spaceAfter=12,
        spaceBefore=12,
        fontName='Helvetica-Bold',
        borderWidth=1,
        borderColor=colors.HexColor('#D2691E'),
        borderPadding=5,
        backColor=colors.HexColor('#F5F5F5')
    ))
    
    # Highlight Style (for prices, important info)
    styles.add(ParagraphStyle(
        name='Highlight',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor('#D2691E'),
        fontName='Helvetica-Bold'
    ))
    
    # Day Header Style
    styles.add(ParagraphStyle(
        name='DayHeader',
        parent=styles['Heading3'],
        fontSize=12,
        textColor=colors.black,
        backColor=colors.HexColor('#FFD700'),
        fontName='Helvetica-Bold',
        borderPadding=5
    ))
    
    return styles


def generate_professional_pdf(quotation_data, customer_name, quotation_no, company_config=None):
    """
    Generate a professionally styled PDF quotation
    
    Args:
        quotation_data: Dictionary containing all quotation information
        customer_name: Name of the customer
        quotation_no: Quotation number
        company_config: Optional dictionary with company branding
            {
                'name': 'Company Name',
                'tagline': 'Your Tagline',
                'email': 'email@company.com',
                'website': 'www.company.com',
                'phone': '+91-1234567890',
                'logo_path': 'path/to/logo.png',  # Optional
                'watermark': 'COMPANY NAME'  # Optional
            }
    """
    
    buffer = io.BytesIO()
    
    # Default company config
    if company_config is None:
        company_config = {
            'name': 'TORNADO INDIA',
            'tagline': 'A SIGNATURE OF EXCELLENCE',
            'email': 'info@tornadoindia.in',
            'website': 'www.tornadoindia.in',
            'phone': '+918416812989 / +919076797409',
            'watermark': 'TORNADO INDIA'
        }
    
    # Create document with custom canvas
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=TOP_MARGIN,
        bottomMargin=50
    )
    
    styles = create_custom_styles()
    story = []
    
    # ==========================================
    # HEADER SECTION
    # The title, tagline, contact line and rule are drawn on page 1 by
    # BrandedCanvas; here we only reserve the vertical space for them.
    # ==========================================
    story.append(Spacer(1, FIRST_PAGE_BODY_Y - TOP_MARGIN))
    
    # ==========================================
    # GREETING & QUOTATION INFO
    # ==========================================
    
    story.append(Paragraph("Dear Sir,", styles['Normal']))
    story.append(Spacer(1, 12))
    
    greeting = f"Greetings from {company_config['name']}!"
    story.append(Paragraph(greeting, styles['Normal']))
    story.append(Spacer(1, 12))
    
    intro = f"Further to our discussion, <b>Please</b> find the most competitive offer as per below:"
    story.append(Paragraph(intro, styles['Normal']))
    story.append(Spacer(1, 12))
    
    # Customer & Quotation Details
    story.append(Paragraph(f"<b>Customer:</b> {customer_name}", styles['Highlight']))
    story.append(Paragraph(f"<b>Quotation No:</b> {quotation_no}", styles['Highlight']))
    story.append(Spacer(1, 20))
    
    # ==========================================
    # PACKAGE COST SECTION
    # ==========================================
    
    total_cost = quotation_data['total_cost']
    travelers = quotation_data['travelers']
    cities_str = " - ".join(quotation_data['cities'])
    
    # Hotel star rating per city (older quotations only have a single 'hotel_star')
    hotel_stars = quotation_data.get('hotel_stars') or {
        c: quotation_data.get('hotel_star') for c in quotation_data['cities']
    }
    if len(set(hotel_stars.values())) == 1:
        star_summary = f"{next(iter(hotel_stars.values()))}-Star"
    else:
        star_summary = ", ".join(f"{c}: {hotel_stars[c]}-Star" for c in quotation_data['cities'])
    
    # Nights are what the hotels charge; days = nights + 1. Older quotations only stored
    # 'days_per_city' (and billed hotels on it), so they keep the previous wording.
    if quotation_data.get('nights_per_city'):
        total_nights = sum(quotation_data['nights_per_city'])
        duration_text = f"{total_nights + 1} Days / {total_nights} Nights"
    else:
        duration_text = f"{sum(quotation_data['days_per_city'])} Days / {sum(quotation_data['days_per_city']) - 1} Nights"
    
    story.append(Paragraph(
        f"<b>Package Cost INR {total_cost:,}/- Per Person</b> (Min {travelers} Paying Pax Traveling together)",
        styles['Highlight']
    ))
    story.append(Spacer(1, 12))
    
    # ==========================================
    # TRIP SUMMARY
    # ==========================================
    
    story.append(Paragraph("Trip Summary", styles['SectionHeader']))
    
    summary_data = [
        [Paragraph('<b>Destination</b>', styles['Normal']), Paragraph(cities_str, styles['Normal'])],
        [Paragraph('<b>Duration</b>', styles['Normal']), Paragraph(duration_text, styles['Normal'])],
        [Paragraph('<b>Arrival Date</b>', styles['Normal']), Paragraph(quotation_data.get('arrival_date', 'Not specified'), styles['Normal'])],
        [Paragraph('<b>Departure Date</b>', styles['Normal']), Paragraph(quotation_data.get('departure_date', 'Not specified'), styles['Normal'])],
        [Paragraph('<b>Travelers</b>', styles['Normal']), Paragraph(str(travelers), styles['Normal'])],
        [Paragraph('<b>Hotel Category</b>', styles['Normal']), Paragraph(star_summary, styles['Normal'])],
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F5F5F5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 20))
    
    # ==========================================
    # HOTEL DETAILS
    # ==========================================
    
    story.append(Paragraph("Hotel Accommodations", styles['SectionHeader']))
    
    for city in quotation_data['cities']:
        pricing = quotation_data['pricing'][city]
        room_cfg = quotation_data['room_config'][city]
        
        hotel_nights = pricing.get('nights', pricing['days'])  # older records: 'days' was the billed nights
        hotel_info = f"<b>{hotel_nights} Nights {city}</b> stay at Hotel <b>{pricing['hotel_name']}</b> ({hotel_stars[city]}-Star)"
        story.append(Paragraph(hotel_info, styles['Normal']))
        
        room_info = f"Room Configuration: {room_cfg['rooms']} Room(s)"
        if room_cfg['extra_bed']:
            room_info += f" + Extra Bed"
        story.append(Paragraph(room_info, styles['Normal']))
        story.append(Spacer(1, 8))
    
    story.append(Spacer(1, 12))
    
    # ==========================================
    # TRAVEL PLAN / ITINERARY WITH DAY-SPECIFIC IMAGES
    # ==========================================
    
    story.append(Paragraph("Travel Plan", styles['SectionHeader']))
    
    day_counter = 1
    image_tracker = new_image_tracker()  # remembers which places/photos this PDF already used
    for city in quotation_data['cities']:
        itinerary = quotation_data['itinerary'][city]
        
        for day in itinerary:
            # Day header with dark background
            day_header = f"Day {day_counter:02d}: {day['title']}"
            day_para = Paragraph(day_header, styles['DayHeader'])
            
            day_table = Table([[day_para]], colWidths=[7*inch])
            day_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#4A4A4A')),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            story.append(day_table)
            story.append(Spacer(1, 8))
            
            # Activities
            for activity in day['activities']:
                story.append(Paragraph(f"• {activity}", styles['Normal']))
            
            story.append(Spacer(1, 12))
            
            # Add 2 images of landmarks from the day's itinerary (9.1 cm width × 5.93 cm height each)
            try:
                # Arrival-night / long-transfer / early-departure days have no sightseeing, so no photos
                if day.get('no_sightseeing'):
                    day_counter += 1
                    continue

                from image_fetcher import fetch_day_images_from_landmarks
                
                # Get landmarks from the itinerary for this day
                landmarks = day.get('landmarks', [])
                
                # Fallback: keep the day's real landmarks; add key_landmark, and only guess from
                # the activity text if the day has no landmark at all
                if not landmarks or len(landmarks) < 2:
                    landmarks = list(landmarks)
                    # Try key_landmark first
                    if day.get('key_landmark') and day['key_landmark'] not in landmarks:
                        landmarks.append(day['key_landmark'])
                    # Try to extract landmarks from activities
                    for activity in (day.get('activities', []) if not landmarks else []):
                        if 'visit' in activity.lower() or 'explore' in activity.lower():
                            # Extract potential landmark names (simple heuristic)
                            words = activity.split()
                            for i, word in enumerate(words):
                                if word.lower() in ['visit', 'explore', 'see']:
                                    if i + 1 < len(words):
                                        potential_landmark = ' '.join(words[i+1:i+4])  # Take next 3 words
                                        landmarks.append(potential_landmark.strip('.,!?'))
                                        break
                        if len(landmarks) >= 2:
                            break
                    
                # Places the client asked for in the notes take the (max 2) photo slots first
                must = [
                    spot.get('place') for spot in (quotation_data.get('sightseeing') or {}).get(city, [])
                    if spot.get('must_visit') and spot.get('place')
                ]
                must_keys = {m.strip().lower() for m in must}
                landmarks = sorted(
                    [l for l in landmarks if l], key=lambda l: l.strip().lower() not in must_keys
                )
                # Only the day's own landmarks are requested here. If one has no usable photo,
                # fetch_day_images_from_landmarks substitutes another place from this city
                # (rest of the sightseeing list / other days' landmarks) or the city overview.
                landmarks = landmarks[:2]
                
                own = {l.strip().lower() for l in landmarks}
                scheduled = set()  # places some day of this city already features
                for other_day in itinerary:
                    scheduled.add((other_day.get('key_landmark') or '').strip().lower())
                    scheduled.update((l or '').strip().lower() for l in (other_day.get('landmarks') or []))
                
                candidates = [spot.get('place') for spot in (quotation_data.get('sightseeing') or {}).get(city, [])]
                for other_day in itinerary:
                    candidates.append(other_day.get('key_landmark'))
                    candidates.extend(other_day.get('landmarks') or [])
                candidates = [c for c in dict.fromkeys(candidates) if c and c.strip().lower() not in own]
                # Prefer places no day is showing (so no photo repeats); borrow another day's landmark only as a last resort
                alternates = (
                    [c for c in candidates if c.strip().lower() not in scheduled]
                    + [c for c in candidates if c.strip().lower() in scheduled]
                )
                
                day_images = fetch_day_images_from_landmarks(
                    city, landmarks, alternates=alternates, used=image_tracker, must=must
                )
                
                # Build the rows (2 photos per row) from whichever images we actually have (no blank cells)
                slots = sorted(
                    int(k[5:]) for k in day_images if k.startswith('image') and day_images[k]
                )
                for start in range(0, len(slots), 2):
                    image_row = []
                    caption_row = []
                    for slot in slots[start:start + 2]:
                        image_row.append(RLImage(
                            io.BytesIO(day_images[f'image{slot}']), width=3.58*inch, height=2.33*inch
                        ))
                        caption_row.append(Paragraph(
                            f"<i>{day_images.get(f'landmark{slot}_name', '')}</i>", styles['Normal']
                        ))
                    col_widths = [3.58*inch] * len(image_row)
                    # Images table
                    images_table = Table([image_row], colWidths=col_widths)
                    images_table.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ]))
                    story.append(images_table)
                    
                    # Captions table
                    story.append(Spacer(1, 4))
                    captions_table = Table([caption_row], colWidths=col_widths)
                    captions_table.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ]))
                    story.append(captions_table)
                    story.append(Spacer(1, 12))
            except Exception as e:
                print(f"Error fetching images for day {day_counter}: {e}")
                pass  # Skip if images fail to load
            
            day_counter += 1
    
    # ==========================================
    # INCLUSIONS
    # ==========================================
    
    story.append(PageBreak())
    story.append(Paragraph("Inclusion", styles['SectionHeader']))
    
    inclusions = [
        "Hotel accommodations as per itinerary",
        "Daily breakfast",
        "All transfers and sightseeing by private vehicle",
        "Professional English-speaking guide",
        "All applicable taxes",
    ]
    
    for item in inclusions:
        story.append(Paragraph(f"• {item}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # ==========================================
    # EXCLUSIONS
    # ==========================================
    
    story.append(Paragraph("Exclusion", styles['SectionHeader']))
    
    exclusions = [
        "5% GST on total package price",
        "Airfare & airport taxes",
        "Visa and insurance charges",
        "Any meals other than specified above",
        "Any entrance fees or camera permits",
        "Any item of personal nature like tips, laundry, telephone calls etc.",
    ]
    
    for item in exclusions:
        story.append(Paragraph(f"• {item}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # ==========================================
    # CLOSING
    # ==========================================
    
    story.append(Paragraph("Looking forward to hearing from you.", styles['Normal']))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>Thanks</b>", styles['Normal']))
    story.append(Paragraph(f"<b>{company_config['name']}</b>", styles['Highlight']))
    story.append(Paragraph(company_config['phone'], styles['Normal']))
    
    # Build PDF with border, header and watermark
    doc.build(
        story,
        onFirstPage=_draw_background,
        onLaterPages=_draw_background,
        canvasmaker=lambda *args, **kwargs: BrandedCanvas(
            *args,
            watermark_text=company_config.get('watermark'),
            header=company_config,
            **kwargs
        )
    )
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return pdf_bytes

# Made with Bob
