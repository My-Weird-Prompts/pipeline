#!/usr/bin/env python3
"""
Episode PDF Transcript Generator

Generates professional PDF transcripts for podcast episodes.
Uses ReportLab for PDF generation with IBM Plex Sans font.

Features:
- Title page with episode metadata and synopsis
- Daniel's prompt section
- Full transcript with speaker avatars
- Proper pagination with colorful page numbers
- PDF metadata for SEO/indexing
"""

import io
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm, cm
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
        PageBreak, KeepTogether, Flowable
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.graphics.shapes import Drawing, Circle, Rect
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    print("Warning: reportlab not installed - PDF generation unavailable")


# Colors matching website theme
ACCENT_COLOR = colors.Color(99/255, 102/255, 241/255)  # Indigo
CORN_COLOR = colors.Color(30/255, 58/255, 95/255)  # Dark blue
HERMAN_COLOR = colors.Color(99/255, 102/255, 241/255)  # Indigo
DANIEL_COLOR = colors.Color(146/255, 64/255, 14/255)  # Amber
GRAY_COLOR = colors.Color(100/255, 116/255, 139/255)
DARK_COLOR = colors.Color(15/255, 23/255, 42/255)
LIGHT_BG = colors.Color(248/255, 250/255, 252/255)

# Bubble backgrounds
CORN_BUBBLE_BG = colors.Color(241/255, 245/255, 249/255)  # Light slate
HERMAN_BUBBLE_BG = colors.Color(224/255, 231/255, 255/255)  # Light indigo
DANIEL_BUBBLE_BG = colors.Color(255/255, 251/255, 235/255)  # Light amber


def register_fonts():
    """Register IBM Plex Sans fonts if available."""
    font_paths = [
        # Pipeline fonts directory (for Modal deployment)
        Path(__file__).parent.parent / "fonts",
        # Local development paths
        Path(__file__).parent.parent.parent / "website" / "public" / "fonts",
        # Modal app directory
        Path("/app/pipeline/fonts"),
        Path("/tmp/fonts"),
        Path.cwd() / "fonts",
    ]

    fonts_registered = False

    for font_dir in font_paths:
        regular = font_dir / "IBMPlexSans-Regular.ttf"
        bold = font_dir / "IBMPlexSans-Bold.ttf"

        if regular.exists() and bold.exists():
            try:
                pdfmetrics.registerFont(TTFont('IBMPlexSans', str(regular)))
                pdfmetrics.registerFont(TTFont('IBMPlexSans-Bold', str(bold)))
                fonts_registered = True
                print(f"Registered IBM Plex Sans fonts from {font_dir}")
                break
            except Exception as e:
                print(f"Failed to register fonts from {font_dir}: {e}")

    if not fonts_registered:
        print("IBM Plex Sans not found, using Helvetica fallback")

    return fonts_registered


def get_font_name(bold: bool = False) -> str:
    """Get the appropriate font name."""
    try:
        pdfmetrics.getFont('IBMPlexSans')
        return 'IBMPlexSans-Bold' if bold else 'IBMPlexSans'
    except:
        return 'Helvetica-Bold' if bold else 'Helvetica'


def create_styles():
    """Create paragraph styles for the PDF."""
    styles = getSampleStyleSheet()

    font_name = get_font_name()
    font_bold = get_font_name(bold=True)

    # Title style
    styles.add(ParagraphStyle(
        name='EpisodeTitle',
        fontName=font_bold,
        fontSize=22,
        leading=26,
        textColor=DARK_COLOR,
        spaceAfter=8*mm,
    ))

    # Section header style
    styles.add(ParagraphStyle(
        name='SectionHeader',
        fontName=font_bold,
        fontSize=14,
        leading=18,
        textColor=DARK_COLOR,
        spaceBefore=6*mm,
        spaceAfter=4*mm,
    ))

    # Synopsis style
    styles.add(ParagraphStyle(
        name='Synopsis',
        fontName=font_name,
        fontSize=11,
        leading=16,
        textColor=GRAY_COLOR,
        alignment=TA_JUSTIFY,
        spaceAfter=4*mm,
    ))

    # Meta info style
    styles.add(ParagraphStyle(
        name='MetaInfo',
        fontName=font_name,
        fontSize=10,
        leading=14,
        textColor=GRAY_COLOR,
        spaceAfter=3*mm,
    ))

    # Speaker name styles
    styles.add(ParagraphStyle(
        name='SpeakerCorn',
        fontName=font_bold,
        fontSize=11,
        leading=14,
        textColor=CORN_COLOR,
    ))

    styles.add(ParagraphStyle(
        name='SpeakerHerman',
        fontName=font_bold,
        fontSize=11,
        leading=14,
        textColor=HERMAN_COLOR,
    ))

    styles.add(ParagraphStyle(
        name='SpeakerDaniel',
        fontName=font_bold,
        fontSize=11,
        leading=14,
        textColor=DANIEL_COLOR,
    ))

    # Dialogue text style
    styles.add(ParagraphStyle(
        name='Dialogue',
        fontName=font_name,
        fontSize=10,
        leading=15,
        textColor=DARK_COLOR,
        alignment=TA_LEFT,
    ))

    # Footer style
    styles.add(ParagraphStyle(
        name='Footer',
        fontName=font_name,
        fontSize=8,
        leading=10,
        textColor=GRAY_COLOR,
    ))

    return styles


class ColoredBox(Flowable):
    """A flowable that draws a colored rounded rectangle with content."""

    def __init__(self, content, width, bg_color, border_color=None, padding=8*mm):
        Flowable.__init__(self)
        self.content = content
        self.box_width = width
        self.bg_color = bg_color
        self.border_color = border_color or bg_color
        self.padding = padding

        # Calculate height based on content
        self.content_height = 0
        for item in content:
            if hasattr(item, 'wrap'):
                w, h = item.wrap(width - 2*padding, 1000)
                self.content_height += h
            elif isinstance(item, (int, float)):
                self.content_height += item

        self.box_height = self.content_height + 2*padding

    def wrap(self, availWidth, availHeight):
        return (self.box_width, self.box_height)

    def draw(self):
        # Draw rounded rectangle
        self.canv.setFillColor(self.bg_color)
        self.canv.setStrokeColor(self.border_color)
        self.canv.setLineWidth(0.5)
        self.canv.roundRect(0, 0, self.box_width, self.box_height, 4*mm, fill=1, stroke=1)

        # Draw content
        y = self.box_height - self.padding
        for item in self.content:
            if hasattr(item, 'wrap'):
                w, h = item.wrap(self.box_width - 2*self.padding, 1000)
                y -= h
                item.drawOn(self.canv, self.padding, y)
            elif isinstance(item, (int, float)):
                y -= item


def parse_transcript(transcript: str) -> list:
    """Parse transcript into speaker segments."""
    segments = []

    # Split by speaker labels
    pattern = r'(?=Corn:|Herman:)'
    parts = re.split(pattern, transcript)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if part.startswith('Corn:'):
            speaker = 'Corn'
            text = part[5:].strip()
        elif part.startswith('Herman:'):
            speaker = 'Herman'
            text = part[7:].strip()
        else:
            continue

        if text:
            segments.append({'speaker': speaker, 'text': text})

    return segments


def generate_episode_pdf(
    title: str,
    episode_number: Optional[int],
    pub_date: datetime,
    duration: Optional[str],
    description: Optional[str],
    prompt_transcript: Optional[str],
    prompt_summary: Optional[str],
    transcript: str,
    episode_url: str,
    output_path: Optional[Path] = None,
) -> Optional[bytes]:
    """
    Generate a PDF transcript for an episode.

    Args:
        title: Episode title
        episode_number: Episode number (e.g., 360)
        pub_date: Publication date
        duration: Runtime string (e.g., "28:36")
        description: Episode synopsis/description
        prompt_transcript: Full prompt transcript
        prompt_summary: Summarized prompt (if available, will be labeled as summary)
        transcript: Full dialogue transcript with Corn:/Herman: labels
        episode_url: URL to the episode page
        output_path: Optional path to save the PDF file

    Returns:
        PDF bytes if successful, None otherwise
    """
    if not HAS_REPORTLAB:
        print("ReportLab not available - cannot generate PDF")
        return None

    # Register fonts
    register_fonts()

    # Create styles
    styles = create_styles()

    # Create buffer
    buffer = io.BytesIO()

    # Page dimensions
    page_width, page_height = A4
    margin = 18*mm
    content_width = page_width - 2*margin

    # Create document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=25*mm,  # Extra space for footer
        title=title,
        author="My Weird Prompts",
        subject=f"Episode {episode_number or ''} - Podcast Transcript",
        creator="myweirdprompts.com",
    )

    # Build story (content)
    story = []

    # ============ TITLE PAGE ============

    # Show name header
    story.append(Paragraph(
        '<font color="#6366f1"><b>MY WEIRD PROMPTS</b></font>',
        styles['SectionHeader']
    ))
    story.append(Paragraph('Podcast Transcript', styles['MetaInfo']))
    story.append(Spacer(1, 6*mm))

    # Episode number badge
    if episode_number:
        story.append(Paragraph(
            f'<font color="#6366f1"><b>EPISODE #{episode_number}</b></font>',
            styles['MetaInfo']
        ))
        story.append(Spacer(1, 4*mm))

    # Episode title
    story.append(Paragraph(title, styles['EpisodeTitle']))

    # Publication info
    date_str = pub_date.strftime("%B %d, %Y")
    meta_text = f"Published {date_str}"
    if duration:
        meta_text += f"  •  Runtime: {duration}"
    story.append(Paragraph(meta_text, styles['MetaInfo']))
    story.append(Spacer(1, 4*mm))

    # Episode URL
    story.append(Paragraph(
        f'<font color="#6366f1"><link href="{episode_url}">{episode_url}</link></font>',
        styles['MetaInfo']
    ))
    story.append(Spacer(1, 8*mm))

    # Divider
    story.append(Spacer(1, 2*mm))

    # Synopsis section
    if description:
        story.append(Paragraph(
            '<font color="#0f172a"><b>EPISODE SYNOPSIS</b></font>',
            styles['SectionHeader']
        ))
        story.append(Paragraph(description, styles['Synopsis']))
        story.append(Spacer(1, 6*mm))

    # Daniel's Prompt section
    prompt_text = prompt_summary or prompt_transcript
    if prompt_text:
        prompt_label = "DANIEL'S PROMPT (Summary)" if prompt_summary else "DANIEL'S PROMPT"
        story.append(Paragraph(
            f'<font color="#92400e"><b>{prompt_label}</b></font>',
            styles['SectionHeader']
        ))

        # Create prompt box content
        prompt_content = [
            Paragraph('<font color="#92400e"><b>Daniel</b></font>', styles['SpeakerDaniel']),
            4*mm,
            Paragraph(prompt_text, styles['Dialogue']),
        ]

        prompt_box = ColoredBox(
            prompt_content,
            content_width,
            DANIEL_BUBBLE_BG,
            colors.Color(251/255, 191/255, 36/255),  # Amber border
        )
        story.append(prompt_box)
        story.append(Spacer(1, 8*mm))

    # ============ TRANSCRIPT ============

    story.append(PageBreak())

    story.append(Paragraph(
        '<font color="#0f172a"><b>TRANSCRIPT</b></font>',
        styles['EpisodeTitle']
    ))
    story.append(Spacer(1, 6*mm))

    # Parse and render transcript
    segments = parse_transcript(transcript)

    for segment in segments:
        speaker = segment['speaker']
        text = segment['text']

        if speaker == 'Corn':
            bg_color = CORN_BUBBLE_BG
            border_color = colors.Color(203/255, 213/255, 225/255)
            speaker_style = styles['SpeakerCorn']
        else:
            bg_color = HERMAN_BUBBLE_BG
            border_color = colors.Color(165/255, 180/255, 252/255)
            speaker_style = styles['SpeakerHerman']

        # Create bubble content
        bubble_content = [
            Paragraph(f'<b>{speaker}</b>', speaker_style),
            3*mm,
            Paragraph(text, styles['Dialogue']),
        ]

        bubble = ColoredBox(
            bubble_content,
            content_width,
            bg_color,
            border_color,
            padding=6*mm,
        )
        story.append(bubble)
        story.append(Spacer(1, 3*mm))

    # Build PDF with custom page handling
    def add_page_footer(canvas, doc):
        """Add footer to each page."""
        canvas.saveState()

        page_num = doc.page

        # Footer background
        canvas.setFillColor(LIGHT_BG)
        canvas.rect(0, 0, page_width, 22*mm, fill=1, stroke=0)

        # Divider line
        canvas.setStrokeColor(colors.Color(226/255, 232/255, 240/255))
        canvas.setLineWidth(0.5)
        canvas.line(margin, 22*mm, page_width - margin, 22*mm)

        # Page number circle
        circle_x = page_width / 2
        circle_y = 12*mm
        canvas.setFillColor(ACCENT_COLOR)
        canvas.circle(circle_x, circle_y, 5*mm, fill=1, stroke=0)

        # Page number text
        canvas.setFillColor(colors.white)
        canvas.setFont(get_font_name(bold=True), 12)
        canvas.drawCentredString(circle_x, circle_y - 4, str(page_num))

        # Left: Episode info
        canvas.setFillColor(DARK_COLOR)
        canvas.setFont(get_font_name(bold=True), 8)
        ep_label = f"Episode #{episode_number}" if episode_number else "My Weird Prompts"
        canvas.drawString(margin, 16*mm, ep_label)

        # Left row 2: Streaming info
        canvas.setFillColor(GRAY_COLOR)
        canvas.setFont(get_font_name(), 7)
        canvas.drawString(margin, 11*mm, "Available on Spotify & Apple Podcasts")

        # Right: Site name
        canvas.setFillColor(ACCENT_COLOR)
        canvas.setFont(get_font_name(bold=True), 8)
        canvas.drawRightString(page_width - margin, 16*mm, "myweirdprompts.com")

        # Right row 2: Listen link
        canvas.setFont(get_font_name(), 7)
        canvas.drawRightString(page_width - margin, 11*mm, "Click to listen online")

        canvas.restoreState()

    # Build document
    doc.build(story, onFirstPage=add_page_footer, onLaterPages=add_page_footer)

    # Get PDF bytes
    pdf_bytes = buffer.getvalue()
    buffer.close()

    # Optionally save to file
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(pdf_bytes)
        print(f"PDF saved to {output_path} ({len(pdf_bytes) / 1024:.1f} KB)")

    return pdf_bytes


def generate_pdf_from_episode(episode: dict, output_path: Optional[Path] = None) -> Optional[bytes]:
    """
    Generate PDF from an episode dictionary.

    Args:
        episode: Episode data dictionary with keys like title, episodeNumber, etc.
        output_path: Optional path to save the PDF

    Returns:
        PDF bytes if successful
    """
    # Parse pub_date if it's a string
    pub_date = episode.get('pubDate') or episode.get('pub_date')
    if isinstance(pub_date, str):
        # Try ISO format first
        try:
            pub_date = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
        except:
            pub_date = datetime.now()
    elif pub_date is None:
        pub_date = datetime.now()

    # Build episode URL
    slug = episode.get('slug', '')
    episode_url = f"https://myweirdprompts.com/episode/{slug}/"

    return generate_episode_pdf(
        title=episode.get('title', 'Untitled Episode'),
        episode_number=episode.get('episodeNumber') or episode.get('episode_number'),
        pub_date=pub_date,
        duration=episode.get('podcastDuration') or episode.get('podcast_duration') or episode.get('duration'),
        description=episode.get('description'),
        prompt_transcript=episode.get('promptTranscript') or episode.get('prompt_transcript'),
        prompt_summary=episode.get('promptSummary') or episode.get('prompt_summary'),
        transcript=episode.get('transcript', ''),
        episode_url=episode_url,
        output_path=output_path,
    )


if __name__ == "__main__":
    # Test with sample data
    sample_episode = {
        'title': 'Test Episode: The Future of AI Podcasting',
        'episodeNumber': 999,
        'pubDate': datetime.now(),
        'podcastDuration': '25:30',
        'description': 'In this test episode, we explore the fascinating world of AI-generated podcasts and how they might change the media landscape forever.',
        'promptTranscript': 'I have been thinking about how AI might change podcasting. What do you think the future holds?',
        'transcript': '''Corn: Hey everyone, welcome back to My Weird Prompts. I am Corn, and I am joined by my brother.

Herman: Herman Poppleberry at your service. And what a fascinating prompt we have today about AI and podcasting.

Corn: It really is. The idea that AI could fundamentally change how we create and consume audio content is mind-blowing.

Herman: Absolutely. Let me break down some of the key trends we are seeing in this space.''',
        'slug': 'test-episode-ai-podcasting',
    }

    output = Path('/tmp/test-episode.pdf')
    pdf_bytes = generate_pdf_from_episode(sample_episode, output)

    if pdf_bytes:
        print(f"Generated PDF: {len(pdf_bytes)} bytes")
