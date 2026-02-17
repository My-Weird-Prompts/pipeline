#!/usr/bin/env python3
"""
Generate Open Graph images for social sharing (Twitter/X, Facebook, LinkedIn).

Creates 1200x630 landscape images with episode title and number embedded,
matching the site's visual style for consistent social media previews.

Usage:
    python generate_og_image.py --title "Episode Title" --episode-number 184 --output ./og-image.png

Or import and use programmatically:
    from generate_og_image import generate_og_image
    og_path = generate_og_image("Episode Title", 184, output_dir)
"""

import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import textwrap


# Color scheme matching the site's dark theme
COLORS = {
    'background_start': (30, 58, 95),      # #1e3a5f
    'background_end': (15, 23, 42),         # #0f172a
    'accent': (14, 165, 233),               # #0ea5e9 (cyan/blue)
    'accent_light': (56, 189, 248),         # #38bdf8
    'text_primary': (248, 250, 252),        # #f8fafc (white-ish)
    'text_secondary': (100, 116, 139),      # #64748b (muted)
    'text_muted': (148, 163, 184),          # #94a3b8
    'badge_bg': (14, 165, 233, 77),         # Transparent cyan
}

# Image dimensions for OG (Twitter/Facebook/LinkedIn)
OG_WIDTH = 1200
OG_HEIGHT = 630

# Image dimensions for Instagram (4:5 ratio - optimal for feed)
INSTAGRAM_WIDTH = 1080
INSTAGRAM_HEIGHT = 1350

# Avatar paths (relative to project root)
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent.parent
AVATARS_DIR = PROJECT_ROOT / "code" / "frontend" / "public" / "images"
FONTS_DIR = PROJECT_ROOT / "code" / "frontend" / "public" / "fonts"


def create_gradient_background(width: int, height: int) -> Image.Image:
    """Create a diagonal gradient background."""
    img = Image.new('RGB', (width, height))

    for y in range(height):
        for x in range(width):
            # Diagonal gradient factor (0 to 1)
            factor = (x / width * 0.5 + y / height * 0.5)

            r = int(COLORS['background_start'][0] * (1 - factor) + COLORS['background_end'][0] * factor)
            g = int(COLORS['background_start'][1] * (1 - factor) + COLORS['background_end'][1] * factor)
            b = int(COLORS['background_start'][2] * (1 - factor) + COLORS['background_end'][2] * factor)

            img.putpixel((x, y), (r, g, b))

    return img


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a font, with fallbacks for different systems."""
    # Try various fonts in order of preference
    font_options = [
        # Atkinson Hyperlegible - matches the blog's font
        str(FONTS_DIR / 'AtkinsonHyperlegible-Bold.ttf') if bold else str(FONTS_DIR / 'AtkinsonHyperlegible-Regular.ttf'),
        # Fallback sans-serif options
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf' if bold else '/usr/share/fonts/truetype/ubuntu/Ubuntu-Regular.ttf',
    ]

    for font_path in font_options:
        if Path(font_path).exists():
            return ImageFont.truetype(font_path, size)

    # Fallback to default
    return ImageFont.load_default()


def draw_rounded_rect(draw: ImageDraw.Draw, xy: tuple, radius: int, fill: tuple):
    """Draw a rounded rectangle."""
    x1, y1, x2, y2 = xy

    # Draw the main rectangle
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)

    # Draw the four corners
    draw.ellipse([x1, y1, x1 + 2*radius, y1 + 2*radius], fill=fill)
    draw.ellipse([x2 - 2*radius, y1, x2, y1 + 2*radius], fill=fill)
    draw.ellipse([x1, y2 - 2*radius, x1 + 2*radius, y2], fill=fill)
    draw.ellipse([x2 - 2*radius, y2 - 2*radius, x2, y2], fill=fill)


def create_circular_avatar(image_path: Path, size: int) -> Image.Image | None:
    """Load an image and make it circular with a border."""
    if not image_path.exists():
        return None

    try:
        img = Image.open(image_path).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)

        # Create circular mask
        mask = Image.new('L', (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([0, 0, size, size], fill=255)

        # Apply mask
        output = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        output.paste(img, (0, 0), mask)

        return output
    except Exception as e:
        print(f"Warning: Could not load avatar {image_path}: {e}")
        return None


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text to fit within a maximum width."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = font.getbbox(test_line)
        width = bbox[2] - bbox[0]

        if width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]

    if current_line:
        lines.append(' '.join(current_line))

    return lines


def generate_og_image(
    title: str,
    episode_number: int | None = None,
    output_dir: Path | None = None,
    output_filename: str | None = None,
) -> Path:
    """
    Generate an Open Graph image for an episode.

    Args:
        title: Episode title
        episode_number: Episode number (optional)
        output_dir: Directory to save the image
        output_filename: Custom filename (default: og-image.png)

    Returns:
        Path to the generated image
    """
    # Create gradient background
    img = create_gradient_background(OG_WIDTH, OG_HEIGHT)
    draw = ImageDraw.Draw(img)

    # Padding
    padding = 60
    content_width = OG_WIDTH - (padding * 2)

    # ===== TOP BAR: Avatars and brand name =====
    top_y = padding

    # Load avatars - BIGGER
    avatar_size = 72
    corn_avatar = create_circular_avatar(AVATARS_DIR / "corn-avatar.png", avatar_size)
    herman_avatar = create_circular_avatar(AVATARS_DIR / "herman-avatar.png", avatar_size)
    daniel_avatar = create_circular_avatar(AVATARS_DIR / "daniel-avatar.png", avatar_size)

    # Position avatars with spacing (no overlap)
    avatar_gap = 12
    avatar_x = padding
    avatar_y = top_y

    # Draw avatars (spaced out, left to right)
    if corn_avatar:
        img.paste(corn_avatar, (avatar_x, avatar_y), corn_avatar)
    if herman_avatar:
        img.paste(herman_avatar, (avatar_x + avatar_size + avatar_gap, avatar_y), herman_avatar)
    if daniel_avatar:
        img.paste(daniel_avatar, (avatar_x + 2 * (avatar_size + avatar_gap), avatar_y), daniel_avatar)

    # Brand name - BIGGER
    total_avatar_width = avatar_size * 3 + avatar_gap * 2
    brand_font = get_font(36, bold=True)
    draw.text(
        (avatar_x + total_avatar_width + 25, avatar_y + avatar_size // 2),
        "MY WEIRD PROMPTS",
        font=brand_font,
        fill=COLORS['text_primary'],
        anchor="lm"
    )

    # ===== MAIN CONTENT AREA =====
    content_top = top_y + avatar_size + 50
    content_bottom = OG_HEIGHT - padding - 70  # Leave room for footer

    # Episode badge (if episode number provided)
    badge_y = content_top

    if episode_number:
        badge_text = f"EPISODE #{episode_number}"
        badge_font = get_font(22, bold=True)
        bbox = badge_font.getbbox(badge_text)
        badge_width = bbox[2] - bbox[0] + 48
        badge_height = 44

        # Semi-transparent badge background
        badge_img = Image.new('RGBA', (badge_width, badge_height), (0, 0, 0, 0))
        badge_draw = ImageDraw.Draw(badge_img)
        draw_rounded_rect(
            badge_draw,
            (0, 0, badge_width, badge_height),
            radius=badge_height // 2,
            fill=(14, 165, 233, 100)  # Semi-transparent cyan
        )
        img.paste(badge_img, (padding, badge_y), badge_img)

        # Badge text - almost white
        draw.text(
            (padding + badge_width // 2, badge_y + badge_height // 2),
            badge_text,
            font=badge_font,
            fill=(240, 245, 250),  # Almost white
            anchor="mm"
        )

        title_y = badge_y + badge_height + 25
    else:
        title_y = badge_y + 20

    # ===== TITLE =====
    # Determine font size based on title length
    if len(title) > 70:
        title_font_size = 40
    elif len(title) > 50:
        title_font_size = 48
    else:
        title_font_size = 56

    title_font = get_font(title_font_size, bold=True)

    # Wrap title text
    title_lines = wrap_text(title, title_font, content_width)

    # Limit to 3 lines max
    if len(title_lines) > 3:
        title_lines = title_lines[:3]
        title_lines[-1] = title_lines[-1][:len(title_lines[-1])-3] + "..."

    # Draw title lines - pure white for better contrast
    line_height = title_font_size + 12
    for i, line in enumerate(title_lines):
        draw.text(
            (padding, title_y + i * line_height),
            line,
            font=title_font,
            fill=(255, 255, 255)  # Pure white
        )

    # ===== SUBTITLE =====
    subtitle_y = title_y + len(title_lines) * line_height + 15
    subtitle_font = get_font(26)
    subtitle_text = "The AI-Generated Podcast"
    draw.text(
        (padding, subtitle_y),
        subtitle_text,
        font=subtitle_font,
        fill=COLORS['text_muted']
    )

    # ===== FOOTER =====
    footer_y = OG_HEIGHT - padding - 20

    # Horizontal line
    draw.line(
        [(padding, footer_y - 25), (OG_WIDTH - padding, footer_y - 25)],
        fill=(148, 163, 184),  # Muted color
        width=1
    )

    # Hosts info (left)
    hosts_font = get_font(20)
    draw.text(
        (padding, footer_y),
        "Hosted by Corn & Herman",
        font=hosts_font,
        fill=COLORS['text_muted'],
        anchor="lm"
    )

    # ===== SAVE IMAGE =====
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        output_filename = "og-image.png"

    output_path = output_dir / output_filename
    img.save(output_path, "PNG", optimize=True)

    print(f"Generated OG image: {output_path}")
    return output_path


def generate_instagram_image(
    title: str,
    episode_number: int | None = None,
    output_dir: Path | None = None,
    output_filename: str | None = None,
) -> Path:
    """
    Generate an Instagram-optimized square image for an episode.

    Creates a 1080x1080 square image suitable for Instagram feed posts.

    Args:
        title: Episode title
        episode_number: Episode number (optional)
        output_dir: Directory to save the image
        output_filename: Custom filename (default: instagram-image.png)

    Returns:
        Path to the generated image
    """
    # Create gradient background (square)
    img = create_gradient_background(INSTAGRAM_WIDTH, INSTAGRAM_HEIGHT)
    draw = ImageDraw.Draw(img)

    # Padding (proportionally larger for square)
    padding = 70
    content_width = INSTAGRAM_WIDTH - (padding * 2)

    # ===== TOP BAR: Brand and avatars =====
    top_y = padding

    # Brand name first (centered at top)
    brand_font = get_font(42, bold=True)
    brand_text = "MY WEIRD PROMPTS"
    brand_bbox = brand_font.getbbox(brand_text)
    brand_width = brand_bbox[2] - brand_bbox[0]
    draw.text(
        (INSTAGRAM_WIDTH // 2 - brand_width // 2, top_y),
        brand_text,
        font=brand_font,
        fill=COLORS['text_primary']
    )

    # Load avatars - centered below brand
    avatar_size = 90
    corn_avatar = create_circular_avatar(AVATARS_DIR / "corn-avatar.png", avatar_size)
    herman_avatar = create_circular_avatar(AVATARS_DIR / "herman-avatar.png", avatar_size)
    daniel_avatar = create_circular_avatar(AVATARS_DIR / "daniel-avatar.png", avatar_size)

    # Position avatars centered
    avatar_gap = 15
    total_avatar_width = avatar_size * 3 + avatar_gap * 2
    avatar_start_x = (INSTAGRAM_WIDTH - total_avatar_width) // 2
    avatar_y = top_y + 60

    # Draw avatars
    if corn_avatar:
        img.paste(corn_avatar, (avatar_start_x, avatar_y), corn_avatar)
    if herman_avatar:
        img.paste(herman_avatar, (avatar_start_x + avatar_size + avatar_gap, avatar_y), herman_avatar)
    if daniel_avatar:
        img.paste(daniel_avatar, (avatar_start_x + 2 * (avatar_size + avatar_gap), avatar_y), daniel_avatar)

    # ===== MAIN CONTENT AREA (centered vertically) =====
    content_top = avatar_y + avatar_size + 60

    # Episode badge (if episode number provided) - centered
    badge_y = content_top

    if episode_number:
        badge_text = f"EPISODE #{episode_number}"
        badge_font = get_font(24, bold=True)
        bbox = badge_font.getbbox(badge_text)
        badge_width = bbox[2] - bbox[0] + 48
        badge_height = 48

        # Calculate centered position
        badge_x = (INSTAGRAM_WIDTH - badge_width) // 2

        # Semi-transparent badge background
        badge_img = Image.new('RGBA', (badge_width, badge_height), (0, 0, 0, 0))
        badge_draw = ImageDraw.Draw(badge_img)
        draw_rounded_rect(
            badge_draw,
            (0, 0, badge_width, badge_height),
            radius=badge_height // 2,
            fill=(14, 165, 233, 100)  # Semi-transparent cyan
        )
        img.paste(badge_img, (badge_x, badge_y), badge_img)

        # Badge text
        draw.text(
            (INSTAGRAM_WIDTH // 2, badge_y + badge_height // 2),
            badge_text,
            font=badge_font,
            fill=(240, 245, 250),
            anchor="mm"
        )

        title_y = badge_y + badge_height + 60  # More spacing after badge
    else:
        title_y = badge_y + 50

    # ===== TITLE (centered, multi-line) =====
    # Determine font size based on title length - larger sizes for better Instagram visibility
    if len(title) > 80:
        title_font_size = 58
    elif len(title) > 60:
        title_font_size = 70
    elif len(title) > 40:
        title_font_size = 82
    else:
        title_font_size = 92

    title_font = get_font(title_font_size, bold=True)

    # Wrap title text
    title_lines = wrap_text(title, title_font, content_width)

    # Limit to 4 lines max for square format
    if len(title_lines) > 4:
        title_lines = title_lines[:4]
        title_lines[-1] = title_lines[-1][:len(title_lines[-1])-3] + "..."

    # Calculate total title block height for vertical centering
    line_height = title_font_size + 18
    title_block_height = len(title_lines) * line_height

    # Draw title lines - centered horizontally
    for i, line in enumerate(title_lines):
        line_bbox = title_font.getbbox(line)
        line_width = line_bbox[2] - line_bbox[0]
        draw.text(
            (INSTAGRAM_WIDTH // 2 - line_width // 2, title_y + i * line_height),
            line,
            font=title_font,
            fill=(255, 255, 255)  # Pure white
        )

    # ===== FOOTER =====
    footer_y = INSTAGRAM_HEIGHT - padding - 30

    # Horizontal line
    draw.line(
        [(padding, footer_y - 30), (INSTAGRAM_WIDTH - padding, footer_y - 30)],
        fill=(148, 163, 184),
        width=1
    )

    # Hosts info (centered)
    hosts_font = get_font(22)
    hosts_text = "Hosted by Corn & Herman"
    hosts_bbox = hosts_font.getbbox(hosts_text)
    hosts_width = hosts_bbox[2] - hosts_bbox[0]
    draw.text(
        (INSTAGRAM_WIDTH // 2 - hosts_width // 2, footer_y),
        hosts_text,
        font=hosts_font,
        fill=COLORS['text_muted']
    )

    # ===== SAVE IMAGE =====
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        output_filename = "instagram-image.png"

    output_path = output_dir / output_filename
    img.save(output_path, "PNG", optimize=True)

    print(f"Generated Instagram image: {output_path}")
    return output_path


def generate_instagram_image_with_cover(
    title: str,
    cover_art_path: str | Path,
    episode_number: int | None = None,
    output_dir: Path | None = None,
    output_filename: str | None = None,
) -> Path:
    """
    Generate an Instagram image with cover art as background.

    Creates a 1080x1080 square image with the episode's cover art as background,
    a dark overlay for readability, and the title overlaid on top.

    Args:
        title: Episode title
        cover_art_path: Path or URL to the cover art image
        episode_number: Episode number (optional)
        output_dir: Directory to save the image
        output_filename: Custom filename (default: instagram-image.png)

    Returns:
        Path to the generated image
    """
    import requests
    from io import BytesIO

    # Load cover art (from URL or local path)
    cover_art_path = str(cover_art_path)
    try:
        if cover_art_path.startswith('http'):
            response = requests.get(cover_art_path, timeout=30)
            response.raise_for_status()
            cover_img = Image.open(BytesIO(response.content)).convert("RGB")
        else:
            cover_img = Image.open(cover_art_path).convert("RGB")
    except Exception as e:
        print(f"Warning: Could not load cover art ({e}), falling back to gradient")
        return generate_instagram_image(title, episode_number, output_dir, output_filename)

    # Resize and crop cover art to square (center crop)
    width, height = cover_img.size
    min_dim = min(width, height)

    # Center crop to square
    left = (width - min_dim) // 2
    top = (height - min_dim) // 2
    cover_img = cover_img.crop((left, top, left + min_dim, top + min_dim))

    # Resize to Instagram dimensions
    cover_img = cover_img.resize((INSTAGRAM_WIDTH, INSTAGRAM_HEIGHT), Image.LANCZOS)

    # Create dark overlay for readability (lighter to show more cover art)
    overlay = Image.new('RGBA', (INSTAGRAM_WIDTH, INSTAGRAM_HEIGHT), (15, 23, 42, 140))
    cover_img = cover_img.convert('RGBA')
    img = Image.alpha_composite(cover_img, overlay)

    draw = ImageDraw.Draw(img)

    # Padding
    padding = 70
    content_width = INSTAGRAM_WIDTH - (padding * 2)

    # ===== TOP BAR: Brand and avatars =====
    top_y = padding

    # Brand name (centered at top)
    brand_font = get_font(42, bold=True)
    brand_text = "MY WEIRD PROMPTS"
    brand_bbox = brand_font.getbbox(brand_text)
    brand_width = brand_bbox[2] - brand_bbox[0]
    draw.text(
        (INSTAGRAM_WIDTH // 2 - brand_width // 2, top_y),
        brand_text,
        font=brand_font,
        fill=COLORS['text_primary']
    )

    # Load avatars
    avatar_size = 90
    corn_avatar = create_circular_avatar(AVATARS_DIR / "corn-avatar.png", avatar_size)
    herman_avatar = create_circular_avatar(AVATARS_DIR / "herman-avatar.png", avatar_size)
    daniel_avatar = create_circular_avatar(AVATARS_DIR / "daniel-avatar.png", avatar_size)

    # Position avatars centered (more space after brand title)
    avatar_gap = 15
    total_avatar_width = avatar_size * 3 + avatar_gap * 2
    avatar_start_x = (INSTAGRAM_WIDTH - total_avatar_width) // 2
    avatar_y = top_y + 80  # More space after brand title

    # Draw avatars
    if corn_avatar:
        img.paste(corn_avatar, (avatar_start_x, avatar_y), corn_avatar)
    if herman_avatar:
        img.paste(herman_avatar, (avatar_start_x + avatar_size + avatar_gap, avatar_y), herman_avatar)
    if daniel_avatar:
        img.paste(daniel_avatar, (avatar_start_x + 2 * (avatar_size + avatar_gap), avatar_y), daniel_avatar)

    # ===== EPISODE BADGE =====
    content_top = avatar_y + avatar_size + 80  # More space after avatars
    badge_y = content_top

    if episode_number:
        badge_text = f"EPISODE #{episode_number}"
        badge_font = get_font(24, bold=True)
        bbox = badge_font.getbbox(badge_text)
        badge_width = bbox[2] - bbox[0] + 48
        badge_height = 48

        badge_x = (INSTAGRAM_WIDTH - badge_width) // 2

        # Semi-transparent badge background
        badge_img = Image.new('RGBA', (badge_width, badge_height), (0, 0, 0, 0))
        badge_draw = ImageDraw.Draw(badge_img)
        draw_rounded_rect(
            badge_draw,
            (0, 0, badge_width, badge_height),
            radius=badge_height // 2,
            fill=(14, 165, 233, 150)  # Semi-transparent cyan
        )
        img.paste(badge_img, (badge_x, badge_y), badge_img)

        # Badge text
        draw.text(
            (INSTAGRAM_WIDTH // 2, badge_y + badge_height // 2),
            badge_text,
            font=badge_font,
            fill=(240, 245, 250),
            anchor="mm"
        )

        content_area_top = badge_y + badge_height + 40
    else:
        content_area_top = badge_y + 40

    # ===== TITLE =====
    if len(title) > 80:
        title_font_size = 58
    elif len(title) > 60:
        title_font_size = 70
    elif len(title) > 40:
        title_font_size = 82
    else:
        title_font_size = 92

    title_font = get_font(title_font_size, bold=True)
    title_lines = wrap_text(title, title_font, content_width)

    if len(title_lines) > 4:
        title_lines = title_lines[:4]
        title_lines[-1] = title_lines[-1][:len(title_lines[-1])-3] + "..."

    line_height = title_font_size + 18
    title_block_height = len(title_lines) * line_height

    # Calculate footer position first so we can center title
    footer_y = INSTAGRAM_HEIGHT - padding - 30
    content_area_bottom = footer_y - 60  # Space before footer line

    # Position title at ~40% down in the available space
    available_height = content_area_bottom - content_area_top
    title_y = content_area_top + int((available_height - title_block_height) * 0.4)

    # Draw title with slight shadow for readability
    for i, line in enumerate(title_lines):
        line_bbox = title_font.getbbox(line)
        line_width = line_bbox[2] - line_bbox[0]
        x = INSTAGRAM_WIDTH // 2 - line_width // 2
        y = title_y + i * line_height
        # Shadow
        draw.text((x + 2, y + 2), line, font=title_font, fill=(0, 0, 0, 128))
        # Main text
        draw.text((x, y), line, font=title_font, fill=(255, 255, 255))

    # ===== FOOTER =====

    # Horizontal line (semi-transparent)
    draw.line(
        [(padding, footer_y - 30), (INSTAGRAM_WIDTH - padding, footer_y - 30)],
        fill=(148, 163, 184, 150),
        width=1
    )

    # Hosts info
    hosts_font = get_font(22)
    hosts_text = "Hosted by Corn & Herman"
    hosts_bbox = hosts_font.getbbox(hosts_text)
    hosts_width = hosts_bbox[2] - hosts_bbox[0]
    draw.text(
        (INSTAGRAM_WIDTH // 2 - hosts_width // 2, footer_y),
        hosts_text,
        font=hosts_font,
        fill=COLORS['text_muted']
    )

    # ===== SAVE =====
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        output_filename = "instagram-image.png"

    output_path = output_dir / output_filename

    # Convert to RGB for PNG save (remove alpha)
    img = img.convert('RGB')
    img.save(output_path, "PNG", optimize=True)

    print(f"Generated Instagram image with cover art: {output_path}")
    return output_path


def get_bundled_font(font_name: str, size: int) -> ImageFont.FreeTypeFont:
    """
    Get a bundled font from the project fonts directory.

    Available fonts (bundled for Modal deployment):
    - montserrat-bold: Modern, fun header font
    - montserrat-extrabold: Extra bold variant
    - firacode-bold: Techy monospace for numbers
    - space-grotesk: Geometric, tech-forward

    Falls back to system fonts if bundled not found.
    """
    # Bundled fonts directory (works in both local and Modal)
    bundled_dir = Path(__file__).parent / "fonts"

    font_map = {
        "montserrat-bold": "Montserrat-Bold.otf",
        "montserrat-extrabold": "Montserrat-ExtraBold.otf",
        "firacode-bold": "FiraCode-Bold.ttf",
        "firacode-semibold": "FiraCode-SemiBold.ttf",
        "space-grotesk": "SpaceGrotesk-Variable.ttf",
        "comfortaa": "Comfortaa-Bold.ttf",       # Friendly, rounded, fun
        "ibm-plex-bold": "IBMPlexSans-Bold.otf", # Clean, professional
    }

    # Try bundled font first
    if font_name in font_map:
        bundled_path = bundled_dir / font_map[font_name]
        if bundled_path.exists():
            return ImageFont.truetype(str(bundled_path), size)

    # Fallback to system fonts
    fallbacks = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ]
    for fallback in fallbacks:
        if Path(fallback).exists():
            return ImageFont.truetype(fallback, size)

    return ImageFont.load_default()


def get_ibm_plex_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get IBM Plex Sans font, with fallbacks. Legacy function for backward compatibility."""
    import os
    home = os.path.expanduser("~")

    font_options = [
        # User local fonts (most reliable)
        f'{home}/.local/share/fonts/IBMPlexSans-Bold.otf' if bold else f'{home}/.local/share/fonts/IBMPlexSans-Regular.otf',
        # System-wide IBM Plex
        '/usr/share/fonts/truetype/ibm-plex/IBMPlexSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/ibm-plex/IBMPlexSans-Regular.ttf',
        '/usr/share/fonts/opentype/ibm-plex/IBMPlexSans-Bold.otf' if bold else '/usr/share/fonts/opentype/ibm-plex/IBMPlexSans-Regular.otf',
        # Try project fonts directory
        str(FONTS_DIR / 'IBMPlexSans-Bold.ttf') if bold else str(FONTS_DIR / 'IBMPlexSans-Regular.ttf'),
        # Fallback to system fonts
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]

    for font_path in font_options:
        if Path(font_path).exists():
            return ImageFont.truetype(font_path, size)

    # Fallback to default
    return ImageFont.load_default()


def generate_og_image_from_cover(
    cover_art_path: str | Path,
    title: str,
    episode_number: int | None = None,
    output_dir: Path | None = None,
    output_filename: str | None = None,
) -> Path:
    """
    Generate an OG image (1200x630) using the cover art as background.

    Design (Canva-style):
    - Cover art as full background
    - Semi-transparent dark overlay band for text area
    - "My Weird Prompts" header with highlight bar (top-left)
    - Episode title (large, left-aligned, below header)
    - Episode number as "#NNN" (below title)

    Args:
        cover_art_path: Path or URL to the cover art image
        title: Episode title
        episode_number: Episode number (displayed as #NNN)
        output_dir: Directory to save the image
        output_filename: Custom filename (default: og-image.png)

    Returns:
        Path to the generated image
    """
    import requests
    from io import BytesIO

    # Load cover art (from URL or local path)
    cover_art_path = str(cover_art_path)
    try:
        if cover_art_path.startswith('http'):
            response = requests.get(cover_art_path, timeout=30)
            response.raise_for_status()
            cover_img = Image.open(BytesIO(response.content)).convert("RGB")
        else:
            cover_img = Image.open(cover_art_path).convert("RGB")
    except Exception as e:
        print(f"Warning: Could not load cover art ({e}), falling back to gradient OG")
        return generate_og_image(title, episode_number, output_dir, output_filename)

    # Get cover dimensions
    orig_width, orig_height = cover_img.size

    # Target aspect ratio for OG: 1200x630 = 1.905:1
    target_ratio = OG_WIDTH / OG_HEIGHT
    current_ratio = orig_width / orig_height

    # Resize and crop to fill OG dimensions
    if current_ratio > target_ratio:
        # Image is wider - crop sides
        new_height = orig_height
        new_width = int(orig_height * target_ratio)
        left = (orig_width - new_width) // 2
        cover_img = cover_img.crop((left, 0, left + new_width, new_height))
    else:
        # Image is taller - crop top/bottom
        new_width = orig_width
        new_height = int(orig_width / target_ratio)
        top = (orig_height - new_height) // 2
        cover_img = cover_img.crop((0, top, new_width, top + new_height))

    # Resize to OG dimensions
    cover_img = cover_img.resize((OG_WIDTH, OG_HEIGHT), Image.LANCZOS)
    cover_img = cover_img.convert('RGBA')

    # Layout constants
    LEFT_MARGIN = 45  # Tighter padding from left edge
    PADDING = 25  # Padding around text block for overlay

    # ===== CALCULATE TEXT DIMENSIONS FIRST (for vertical centering) =====

    # Header font
    header_text = "My Weird Prompts"
    header_font_size = 40
    header_font = get_bundled_font("comfortaa", header_font_size)
    header_bbox = header_font.getbbox(header_text)
    header_height = header_bbox[3] - header_bbox[1]
    header_width = header_bbox[2] - header_bbox[0]

    # Title font - calculate size based on length
    if len(title) > 70:
        title_font_size = 44
    elif len(title) > 50:
        title_font_size = 52
    elif len(title) > 35:
        title_font_size = 60
    else:
        title_font_size = 68

    title_font = get_ibm_plex_font(title_font_size, bold=True)
    max_width = OG_WIDTH - LEFT_MARGIN - 80
    title_lines = wrap_text(title, title_font, max_width)

    # Limit to 2 lines
    if len(title_lines) > 2:
        title_lines = title_lines[:2]
        if len(title_lines[-1]) > 3:
            title_lines[-1] = title_lines[-1][:-3] + "..."

    line_height = title_font_size + 10
    title_block_height = len(title_lines) * line_height

    # Episode number
    episode_font_size = 36
    episode_font = get_ibm_plex_font(episode_font_size, bold=True)
    episode_height = episode_font_size + 12 if episode_number else 0

    # Total content height
    gap_header_title = 30
    gap_title_episode = 12
    total_content_height = header_height + gap_header_title + title_block_height + gap_title_episode + episode_height

    # Calculate vertical center position
    start_y = (OG_HEIGHT - total_content_height) // 2

    # ===== CREATE TIGHT OVERLAY AROUND TEXT (starts from left edge) =====
    overlay = Image.new('RGBA', (OG_WIDTH, OG_HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # Calculate max text width for overlay sizing
    max_text_width = max(
        header_width + 24,  # header with highlight padding
        max(title_font.getbbox(line)[2] - title_font.getbbox(line)[0] for line in title_lines) if title_lines else 0,
        episode_font.getbbox(f"#{episode_number}")[2] - episode_font.getbbox(f"#{episode_number}")[0] if episode_number else 0
    )

    # Overlay bounds - starts from left edge, tight to text on right
    overlay_top = start_y - PADDING
    overlay_bottom = start_y + total_content_height + PADDING
    overlay_left = 0  # Start from left edge
    overlay_right = LEFT_MARGIN + max_text_width + PADDING + 20  # Tight to text width

    overlay_draw.rectangle(
        [(overlay_left, overlay_top), (overlay_right, overlay_bottom)],
        fill=(0, 0, 0, 140)  # ~55% opacity
    )

    img = Image.alpha_composite(cover_img, overlay)
    draw = ImageDraw.Draw(img)

    # ===== DRAW "MY WEIRD PROMPTS" HEADER WITH HIGHLIGHT =====
    header_y = start_y
    highlight_padding_x = 12
    highlight_padding_y = 8
    highlight_color = (138, 97, 168, 200)  # Purple with transparency

    draw.rectangle(
        [
            (LEFT_MARGIN - highlight_padding_x, header_y - highlight_padding_y),
            (LEFT_MARGIN + header_width + highlight_padding_x, header_y + header_height + highlight_padding_y)
        ],
        fill=highlight_color
    )
    draw.text((LEFT_MARGIN, header_y), header_text, font=header_font, fill=(255, 255, 255))

    # ===== DRAW EPISODE TITLE =====
    title_y = header_y + header_height + gap_header_title

    for i, line in enumerate(title_lines):
        y = title_y + i * line_height
        # Shadow for depth
        draw.text((LEFT_MARGIN + 3, y + 3), line, font=title_font, fill=(0, 0, 0, 180))
        # Main white text
        draw.text((LEFT_MARGIN, y), line, font=title_font, fill=(255, 255, 255))

    # ===== DRAW EPISODE NUMBER =====
    if episode_number:
        episode_text = f"#{episode_number}"
        ep_y = title_y + title_block_height + gap_title_episode

        # Shadow
        draw.text((LEFT_MARGIN + 2, ep_y + 2), episode_text, font=episode_font, fill=(0, 0, 0, 150))
        # Lighter green for better contrast
        draw.text((LEFT_MARGIN, ep_y), episode_text, font=episode_font, fill=(140, 230, 140))

    # ===== HOST AVATARS (bottom right, overlapping circles) =====
    host_avatars = [
        "https://www.myweirdprompts.com/images/hosts/daniel.png",
        "https://www.myweirdprompts.com/images/hosts/corn.png",
        "https://www.myweirdprompts.com/images/hosts/herman.png",
    ]

    avatar_size = 90
    avatar_spacing = 15  # Gap between avatars (no overlap)
    avatar_y = OG_HEIGHT - avatar_size - 35  # 35px from bottom
    total_avatars_width = (avatar_size * 3) + (avatar_spacing * 2)
    avatar_start_x = OG_WIDTH - 50 - total_avatars_width  # Right aligned with margin

    for i, avatar_url in enumerate(host_avatars):
        try:
            avatar_response = requests.get(avatar_url, timeout=10)
            avatar_response.raise_for_status()
            avatar_img = Image.open(BytesIO(avatar_response.content)).convert("RGBA")
            avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.LANCZOS)

            # Create circular mask
            mask = Image.new('L', (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)

            # Create circular avatar
            circular_avatar = Image.new('RGBA', (avatar_size, avatar_size), (0, 0, 0, 0))
            circular_avatar.paste(avatar_img, (0, 0), mask)

            # Add white border ring
            border_size = 4
            border = Image.new('RGBA', (avatar_size, avatar_size), (0, 0, 0, 0))
            border_draw = ImageDraw.Draw(border)
            border_draw.ellipse((0, 0, avatar_size - 1, avatar_size - 1), outline=(255, 255, 255, 255), width=border_size)

            # Position: avatars spaced out with gap
            x_pos = avatar_start_x + i * (avatar_size + avatar_spacing)

            # Composite avatar onto main image
            img.paste(circular_avatar, (x_pos, avatar_y), circular_avatar)
            img.paste(border, (x_pos, avatar_y), border)

        except Exception as e:
            print(f"Warning: Could not load avatar {avatar_url}: {e}")

    # ===== SAVE =====
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        output_filename = "og-image.png"

    output_path = output_dir / output_filename

    # Convert to RGB for PNG save
    img = img.convert('RGB')
    img.save(output_path, "PNG", optimize=True)

    print(f"Generated OG image: {output_path}")
    return output_path


def generate_og_image_branded(
    title: str,
    episode_number: int | None = None,
    output_dir: Path | None = None,
    output_filename: str | None = None,
) -> Path:
    """
    Generate an OG image (1200x630) using the brand kit base image.

    This is the simple, reliable approach: takes the og-default.png brand asset
    and overlays the episode title at the bottom and episode number in the top right.

    Args:
        title: Episode title (displayed at bottom)
        episode_number: Episode number (displayed in top right with # prefix)
        output_dir: Directory to save the image
        output_filename: Custom filename (default: og-image.png)

    Returns:
        Path to the generated image
    """
    import math

    print(f"Generating branded OG image for: {title}")

    # Load the brand kit OG default image
    brand_kit_path = Path(__file__).parent.parent.parent / "assets" / "brand-kit" / "og-default.png"
    if not brand_kit_path.exists():
        raise FileNotFoundError(f"Brand kit OG default not found: {brand_kit_path}")

    img = Image.open(brand_kit_path).convert("RGBA")

    # Set up output path
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        output_filename = "og-image.png"

    output_path = output_dir / output_filename

    draw = ImageDraw.Draw(img)

    # Episode number in top right (stylized with # and rotation)
    if episode_number is not None:
        ep_text = f"#{episode_number}"
        # Bigger font
        episode_font = get_bundled_font("firacode-bold", 80)

        # Create a separate layer for the episode number (for rotation)
        bbox = episode_font.getbbox(ep_text)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Make the layer larger to accommodate rotation without clipping
        layer_size = int(max(text_width, text_height) * 1.8)
        ep_layer = Image.new("RGBA", (layer_size, layer_size), (0, 0, 0, 0))
        ep_draw = ImageDraw.Draw(ep_layer)

        # Draw text centered in the layer
        text_x = (layer_size - text_width) // 2
        text_y = (layer_size - text_height) // 2

        # Shadow for depth
        ep_draw.text((text_x + 2, text_y + 2), ep_text, font=episode_font, fill=(0, 0, 0, 180))
        # Main text in silver-white (high-tech but readable)
        ep_draw.text((text_x, text_y), ep_text, font=episode_font, fill=(220, 225, 235))

        # Rotate 10 degrees counter-clockwise
        ep_layer = ep_layer.rotate(10, resample=Image.BICUBIC, expand=False)

        # Position: upper-right corner, high enough to not cover the show name
        # The layer is ~1.8x the text size for rotation padding, so we need negative Y
        # to push the visible text up near the top edge
        padding = 30
        paste_x = OG_WIDTH - layer_size - padding + 50  # Right side
        paste_y = -70  # Negative to push text higher (layer has rotation padding)

        img.paste(ep_layer, (paste_x, paste_y), ep_layer)

        print(f"  Added episode number: {ep_text} (rotated -10°)")

    # Dynamic title font sizing based on word count
    word_count = len(title.split())
    char_count = len(title)

    if char_count <= 25:
        title_font_size = 64  # Short titles get bigger font
    elif char_count <= 45:
        title_font_size = 54  # Medium titles
    elif char_count <= 70:
        title_font_size = 46  # Longer titles
    else:
        title_font_size = 38  # Very long titles

    title_font = get_bundled_font("ibm-plex-bold", title_font_size)

    # Title at bottom, centered
    max_width = OG_WIDTH - 80  # 40px padding on each side

    # Simple word wrap
    words = title.split()
    lines = []
    current_line = []

    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=title_font)
        if bbox[2] - bbox[0] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]

    if current_line:
        lines.append(' '.join(current_line))

    # Calculate total height of text block
    line_height = title_font_size + 10
    total_text_height = len(lines) * line_height

    # Position at bottom with padding
    bottom_padding = 40
    start_y = OG_HEIGHT - total_text_height - bottom_padding

    # Draw each line centered
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        text_width = bbox[2] - bbox[0]
        x = (OG_WIDTH - text_width) // 2
        y = start_y + (i * line_height)

        # Shadow for readability
        for offset in [(2, 2), (1, 1)]:
            draw.text((x + offset[0], y + offset[1]), line, font=title_font, fill=(0, 0, 0, 200))

        # Main text in white
        draw.text((x, y), line, font=title_font, fill=(248, 250, 252))

    print(f"  Added title: {title} (font size: {title_font_size}px)")

    # Save
    img.convert("RGB").save(output_path, "PNG", optimize=True)
    print(f"Generated branded OG image: {output_path}")

    return output_path


def generate_og_image_flux2(
    title: str,
    episode_number: int | None = None,
    output_dir: Path | None = None,
    output_filename: str | None = None,
) -> Path:
    """
    Generate an OG image (1200x630) using Flux 2 via Fal AI.

    Creates a stylized social sharing image with the episode title rendered
    artistically by the AI model. The title is included in the prompt so
    Flux 2 renders it in a fun, thematic font matching the episode's subject.

    Args:
        title: Episode title (will be rendered in the image by the AI)
        episode_number: Episode number (optional, included in prompt)
        output_dir: Directory to save the image
        output_filename: Custom filename (default: og-image-flux2.png)

    Returns:
        Path to the generated image
    """
    import os
    import urllib.request

    # Try to import fal_client
    try:
        import fal_client
    except ImportError:
        raise RuntimeError("fal-client not installed. Run: pip install fal-client")

    # Ensure FAL_KEY is set
    fal_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")
    if not fal_key:
        raise RuntimeError("FAL_KEY or FAL_API_KEY not set in environment")
    os.environ["FAL_KEY"] = fal_key

    print(f"Generating OG image with Flux 2 (1200x630)...")

    # Build the prompt with title and episode number as separate text elements
    episode_label = f"Episode #{episode_number}" if episode_number else ""

    # Prompt designed for clean typography with creative, vibrant thematic background
    prompt = f"""A visually striking podcast social media banner image, landscape format.

TEXT LAYOUT:
- Main title "{title}" displayed prominently in the center-left area
- Below the title: "{episode_label}" in smaller text

TYPOGRAPHY:
- Clean, geometric sans-serif typeface (like IBM Plex Sans or Inter)
- Bold weight for title, medium for episode number
- Pure white text with subtle drop shadow for contrast
- Professional, modern - NOT cartoon, bubble, or decorative fonts

BACKGROUND (be creative and vibrant!):
- Eye-catching, colorful artistic interpretation of: {title}
- Use rich, saturated colors - blues, purples, teals, magentas, oranges
- Abstract geometric shapes, flowing gradients, light trails, or cosmic elements
- Dynamic composition with depth and visual interest
- Semi-transparent dark overlay on left side where text appears (for legibility)
- Right side can be more vibrant and detailed
- Keep the bottom-right corner relatively clear/simple (avatars will be overlaid there)

AVOID THESE CLICHÉS:
- NO brain icons or neural network imagery (overused for AI topics)
- NO generic circuit boards or matrix-style falling text
- NO literal robots or androids
- NO generic globe/world imagery
- NO people, faces, avatars, or character illustrations of any kind

STYLE INSPIRATION:
- Modern tech conference graphics
- Spotify playlist covers
- Apple keynote visuals
- Gradient-rich, contemporary digital art

The image should feel fresh, creative, and visually exciting while maintaining text legibility."""

    # Set up output path
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename is None:
        output_filename = "og-image-flux2.png"

    output_path = output_dir / output_filename

    try:
        # Call Flux 2 with exact OG dimensions
        result = fal_client.subscribe(
            "fal-ai/flux-2",
            arguments={
                "prompt": prompt,
                "image_size": {
                    "width": OG_WIDTH,   # 1200
                    "height": OG_HEIGHT,  # 630
                },
                "num_images": 1,
                "output_format": "png",
                "guidance_scale": 3.5,  # Moderate guidance for creativity + adherence
                "num_inference_steps": 28,
                "enable_safety_checker": True,
            }
        )

        # Extract image URL from response
        images = result.get("images", [])
        if not images:
            raise RuntimeError(f"No images returned from Flux 2: {result}")

        image_url = images[0].get("url")
        if not image_url:
            raise RuntimeError(f"No URL in Flux 2 response: {result}")

        # Download the image to a temp file first
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        urllib.request.urlretrieve(image_url, tmp_path)

        # Resize to exact OG dimensions (Flux 2 may round to different sizes)
        img = Image.open(tmp_path)
        if img.size != (OG_WIDTH, OG_HEIGHT):
            print(f"  Resizing from {img.size[0]}x{img.size[1]} to {OG_WIDTH}x{OG_HEIGHT}")
            img = img.resize((OG_WIDTH, OG_HEIGHT), Image.LANCZOS)

        # Convert to RGBA for compositing
        img = img.convert("RGBA")

        # Add show logo in top-right corner
        logo_path = Path(__file__).parent.parent.parent / "assets" / "icon" / "mwp-logo-v2.png"
        if logo_path.exists():
            try:
                logo = Image.open(logo_path).convert("RGBA")
                # Scale logo to larger height (~240px)
                logo_target_height = 240
                scale_factor = logo_target_height / logo.height
                logo_new_size = (int(logo.width * scale_factor), logo_target_height)
                logo = logo.resize(logo_new_size, Image.LANCZOS)

                # Position in top-right with padding
                padding = 20
                x = OG_WIDTH - logo.width - padding
                y = padding

                img.paste(logo, (x, y), logo)
                print(f"  Added show logo")
            except Exception as e:
                print(f"  Warning: Could not add logo: {e}")

        # Overlay host avatars in bottom-left corner
        overlay_path = Path(__file__).parent.parent.parent / "assets" / "overlay.png"
        if overlay_path.exists():
            try:
                overlay = Image.open(overlay_path).convert("RGBA")
                # Scale down to ~35% of original width, maintaining aspect ratio
                overlay_target_width = 400
                scale_factor = overlay_target_width / overlay.width
                overlay_new_size = (overlay_target_width, int(overlay.height * scale_factor))
                overlay = overlay.resize(overlay_new_size, Image.LANCZOS)

                # Position in bottom-left with padding
                padding = 20
                x = padding
                y = OG_HEIGHT - overlay.height - padding

                img.paste(overlay, (x, y), overlay)
                print(f"  Added host avatars overlay")
            except Exception as e:
                print(f"  Warning: Could not add overlay: {e}")

        # Convert to RGB and save
        img = img.convert("RGB")
        img.save(output_path, "PNG", optimize=True)

        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)

        print(f"Generated Flux 2 OG image: {output_path}")
        return output_path

    except Exception as e:
        print(f"Error generating Flux 2 OG image: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Generate Open Graph and Instagram images for social sharing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python generate_og_image.py --title "Fork or Stay? The Art of Customizing Open Source" --episode-number 184
    python generate_og_image.py --title "My Episode Title" --output ./images/og.png
    python generate_og_image.py --title "My Episode Title" --instagram --output ./images/instagram.png
    python generate_og_image.py --title "My Episode Title" --all --output-dir ./images/
        """
    )

    parser.add_argument(
        "--title", "-t",
        required=True,
        help="Episode title"
    )

    parser.add_argument(
        "--episode-number", "-n",
        type=int,
        help="Episode number (optional)"
    )

    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path.cwd() / "og-image.png",
        help="Output file path (default: ./og-image.png)"
    )

    parser.add_argument(
        "--output-dir", "-d",
        type=Path,
        help="Output directory (used with --all)"
    )

    parser.add_argument(
        "--instagram",
        action="store_true",
        help="Generate Instagram square image instead of OG image"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate both OG and Instagram images"
    )

    parser.add_argument(
        "--flux2",
        action="store_true",
        help="Generate OG image using Flux 2 AI (requires FAL_KEY)"
    )

    parser.add_argument(
        "--branded",
        action="store_true",
        help="Generate OG image using brand kit base (simple, reliable)"
    )

    args = parser.parse_args()

    if args.branded:
        # Generate OG image using brand kit base (simple, reliable)
        output_dir = args.output.parent
        output_filename = args.output.name
        generate_og_image_branded(
            title=args.title,
            episode_number=args.episode_number,
            output_dir=output_dir,
            output_filename=output_filename,
        )
    elif args.all:
        # Generate both images
        output_dir = args.output_dir or args.output.parent
        generate_og_image(
            title=args.title,
            episode_number=args.episode_number,
            output_dir=output_dir,
            output_filename="og-image.png",
        )
        generate_instagram_image(
            title=args.title,
            episode_number=args.episode_number,
            output_dir=output_dir,
            output_filename="instagram-image.png",
        )
    elif args.flux2:
        # Generate OG image using Flux 2 AI
        output_dir = args.output.parent
        output_filename = args.output.name if args.output.name != "og-image.png" else "og-image-flux2.png"
        generate_og_image_flux2(
            title=args.title,
            episode_number=args.episode_number,
            output_dir=output_dir,
            output_filename=output_filename,
        )
    elif args.instagram:
        # Generate Instagram image only
        output_dir = args.output.parent
        output_filename = args.output.name
        generate_instagram_image(
            title=args.title,
            episode_number=args.episode_number,
            output_dir=output_dir,
            output_filename=output_filename,
        )
    else:
        # Generate OG image only (default)
        output_dir = args.output.parent
        output_filename = args.output.name
        generate_og_image(
            title=args.title,
            episode_number=args.episode_number,
            output_dir=output_dir,
            output_filename=output_filename,
        )


if __name__ == "__main__":
    main()
