#!/usr/bin/env python3
"""
Episode Idea Generator Agent

Analyzes the MWP episode catalog (400+ episodes) and generates fresh prompt
ideas that complement the existing library — avoiding repetition and finding
topic gaps. Outputs individual markdown files and a combined PDF.

Usage:
    python -m pipeline.agents.idea_generator
    python -m pipeline.agents.idea_generator --count 20
    python -m pipeline.agents.idea_generator --focus "local-ai"
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from pipeline.database.postgres import get_all_episodes
from pipeline.llm.gemini import call_gemini


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------

CATEGORIES_JSON = Path(__file__).parent.parent.parent / "website" / "src" / "data" / "categories.json"


def load_categories() -> dict:
    """Load the category taxonomy from categories.json."""
    if CATEGORIES_JSON.exists():
        with open(CATEGORIES_JSON) as f:
            return json.load(f)
    print(f"  Warning: {CATEGORIES_JSON} not found, proceeding without taxonomy")
    return {"categories": []}


def build_topic_summary(episodes: list) -> dict:
    """
    Analyze the episode catalog and return a structured summary.

    Returns dict with keys:
      - total: int
      - tag_counts: dict[str, int]  (top 60 tags)
      - category_counts: dict[str, int]
      - subcategory_counts: dict[str, int]
      - recent_titles: list[str]  (last 20)
    """
    tag_counter: Counter = Counter()
    cat_counter: Counter = Counter()
    sub_counter: Counter = Counter()

    for ep in episodes:
        tags = ep.get("tags") or []
        for t in tags:
            tag_counter[t] += 1
        cat = ep.get("category")
        if cat:
            cat_counter[cat] += 1
        sub = ep.get("subcategory")
        if sub:
            sub_counter[sub] += 1

    recent = [ep["title"] for ep in episodes[-20:] if ep.get("title")]

    return {
        "total": len(episodes),
        "tag_counts": dict(tag_counter.most_common(60)),
        "category_counts": dict(cat_counter.most_common()),
        "subcategory_counts": dict(sub_counter.most_common()),
        "recent_titles": recent,
    }


def format_taxonomy(categories: dict) -> str:
    """Format the category taxonomy as readable text for the LLM."""
    lines = []
    for cat in categories.get("categories", []):
        lines.append(f"- **{cat['name']}** ({cat['id']}): {cat['description']}")
        for sub in cat.get("subcategories", []):
            lines.append(f"  - {sub['name']} ({sub['id']}): {sub['description']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

def build_prompt(summary: dict, taxonomy_text: str, count: int, focus: str | None) -> str:
    """Build the Gemini prompt for idea generation."""

    focus_instruction = ""
    if focus:
        focus_instruction = (
            f"\n**FOCUS AREA:** Prioritize ideas in or adjacent to the "
            f'"{focus}" category. At least half of the ideas should relate '
            f"to this area, but still include a few wildcards from other categories.\n"
        )

    return f"""You are a creative producer for "My Weird Prompts" (MWP), an AI-generated podcast where two AI co-hosts (Corn and Herman) discuss listener-submitted prompts about technology, AI, geopolitics, and everyday life.

The show has {summary['total']} episodes so far. Your job is to generate {count} fresh prompt ideas that would make great new episodes — ideas that complement the existing catalog without repeating what's already been covered.

## Existing Topic Distribution

**Top tags (with episode counts):**
{json.dumps(summary['tag_counts'], indent=2)}

**Category distribution:**
{json.dumps(summary['category_counts'], indent=2)}

**Subcategory distribution:**
{json.dumps(summary['subcategory_counts'], indent=2)}

## Category Taxonomy (use these for categorization)

{taxonomy_text}

## Recent Episodes (last 20 — avoid overlap)

{chr(10).join(f"- {t}" for t in summary['recent_titles'])}
{focus_instruction}
## Instructions

Generate exactly {count} episode prompt ideas. For each idea, output:

### Idea N: [Title]

**Category:** [category-id]
**Subcategory:** [subcategory-id]
**Tags:** [tag1, tag2, tag3]

[2-3 sentence description of the prompt idea — what would the listener ask about?]

**Why this works:** [1-2 sentences on why this is a good complement to the existing catalog — what gap does it fill?]

---

## Guidelines

- **Diversity:** Spread ideas across different categories. Don't cluster them all in one area.
- **Gaps:** Look at categories/subcategories with LOW episode counts — those are underexplored.
- **Freshness:** Avoid topics that overlap heavily with the recent 20 episodes listed above.
- **Specificity:** Each idea should be specific enough to record as a voice prompt. Not "tell me about AI" but "What would happen if every smartphone had a dedicated AI chip that could run GPT-4 class models locally?"
- **MWP style:** The show is conversational, opinionated, and doesn't shy away from weird or niche topics. Daniel (the prompter) is a tech enthusiast based in Israel who loves local AI, OSINT, home networking, and practical automation.
- **Variety of formats:** Mix deep-dives, comparisons, "what if" scenarios, practical guides, and opinion pieces.

Output ONLY the ideas in the format above. No preamble or closing remarks."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_ideas(response: str) -> list[dict]:
    """
    Parse the Gemini response into a list of idea dicts.

    Each dict has: number, title, category, subcategory, tags, description, rationale
    """
    ideas = []
    # Split on "### Idea" headers
    blocks = re.split(r"###\s+Idea\s+\d+\s*:\s*", response)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Title is the first line
        lines = block.split("\n", 1)
        title = lines[0].strip().rstrip("#").strip()
        rest = lines[1] if len(lines) > 1 else ""

        # Extract fields
        category = ""
        subcategory = ""
        tags = []
        description_lines = []
        rationale = ""

        for line in rest.split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("**Category:**"):
                category = line_stripped.replace("**Category:**", "").strip()
            elif line_stripped.startswith("**Subcategory:**"):
                subcategory = line_stripped.replace("**Subcategory:**", "").strip()
            elif line_stripped.startswith("**Tags:**"):
                tag_str = line_stripped.replace("**Tags:**", "").strip()
                tags = [t.strip() for t in tag_str.split(",") if t.strip()]
            elif line_stripped.startswith("**Why this works:**"):
                rationale = line_stripped.replace("**Why this works:**", "").strip()
            elif line_stripped == "---":
                continue
            elif line_stripped and not line_stripped.startswith("**"):
                description_lines.append(line_stripped)

        description = " ".join(description_lines).strip()

        if title and description:
            ideas.append({
                "number": len(ideas) + 1,
                "title": title,
                "category": category,
                "subcategory": subcategory,
                "tags": tags,
                "description": description,
                "rationale": rationale,
            })

    return ideas


# ---------------------------------------------------------------------------
# Output — Markdown
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Convert a title to a filename-safe slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text).strip("-")
    return text[:60]


def save_markdown(ideas: list[dict], output_dir: Path) -> Path:
    """
    Save each idea as an individual markdown file and a combined file.

    Returns path to the combined markdown file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Individual files
    width = 3 if len(ideas) >= 100 else 2
    for idea in ideas:
        filename = f"{idea['number']:0{width}d}-{slugify(idea['title'])}.md"
        filepath = output_dir / filename
        content = format_idea_markdown(idea)
        filepath.write_text(content)

    # Combined file
    combined_path = output_dir / "all-ideas.md"
    date_str = datetime.now().strftime("%B %d, %Y")
    parts = [f"# MWP Episode Ideas — {date_str}\n"]
    parts.append(f"Generated {len(ideas)} prompt ideas for My Weird Prompts.\n")
    parts.append("---\n")
    for idea in ideas:
        parts.append(format_idea_markdown(idea))
        parts.append("\n---\n")

    combined_path.write_text("\n".join(parts))
    return combined_path


def format_idea_markdown(idea: dict) -> str:
    """Format a single idea as markdown."""
    lines = [f"## {idea['number']}. {idea['title']}\n"]

    if idea["category"]:
        lines.append(f"**Category:** {idea['category']}")
    if idea["subcategory"]:
        lines.append(f"**Subcategory:** {idea['subcategory']}")
    if idea["tags"]:
        lines.append(f"**Tags:** {', '.join(idea['tags'])}")

    lines.append("")
    lines.append(idea["description"])
    lines.append("")

    if idea["rationale"]:
        lines.append(f"**Why this works:** {idea['rationale']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output — PDF
# ---------------------------------------------------------------------------

def generate_pdf(ideas: list[dict], output_path: Path) -> bool:
    """
    Generate a PDF of the ideas using ReportLab.

    Returns True on success, False if ReportLab is unavailable.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
    except ImportError:
        print("  Warning: reportlab not installed — skipping PDF generation")
        return False

    # Try to register fonts (same pattern as generate_pdf.py)
    font_name = "Helvetica"
    font_bold = "Helvetica-Bold"
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        font_dirs = [
            Path(__file__).parent.parent / "fonts",
            Path(__file__).parent.parent.parent / "website" / "public" / "fonts",
        ]
        for font_dir in font_dirs:
            regular = font_dir / "IBMPlexSans-Regular.ttf"
            bold = font_dir / "IBMPlexSans-Bold.ttf"
            if regular.exists() and bold.exists():
                pdfmetrics.registerFont(TTFont("IBMPlexSans", str(regular)))
                pdfmetrics.registerFont(TTFont("IBMPlexSans-Bold", str(bold)))
                font_name = "IBMPlexSans"
                font_bold = "IBMPlexSans-Bold"
                break
    except Exception:
        pass

    # Colors
    ACCENT = colors.Color(99/255, 102/255, 241/255)
    DARK = colors.Color(15/255, 23/255, 42/255)
    GRAY = colors.Color(100/255, 116/255, 139/255)
    LIGHT_BG = colors.Color(248/255, 250/255, 252/255)

    # Styles
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="DocTitle", fontName=font_bold, fontSize=24, leading=30,
        textColor=DARK, spaceAfter=6*mm,
    ))
    styles.add(ParagraphStyle(
        name="DocSubtitle", fontName=font_name, fontSize=12, leading=16,
        textColor=GRAY, spaceAfter=12*mm,
    ))
    styles.add(ParagraphStyle(
        name="IdeaTitle", fontName=font_bold, fontSize=14, leading=18,
        textColor=ACCENT, spaceBefore=4*mm, spaceAfter=3*mm,
    ))
    styles.add(ParagraphStyle(
        name="IdeaMeta", fontName=font_name, fontSize=9, leading=13,
        textColor=GRAY, spaceAfter=2*mm,
    ))
    styles.add(ParagraphStyle(
        name="IdeaBody", fontName=font_name, fontSize=10, leading=15,
        textColor=DARK, alignment=TA_JUSTIFY, spaceAfter=2*mm,
    ))
    styles.add(ParagraphStyle(
        name="IdeaRationale", fontName=font_name, fontSize=9, leading=13,
        textColor=GRAY, alignment=TA_LEFT, spaceAfter=4*mm,
        leftIndent=8*mm,
    ))
    styles.add(ParagraphStyle(
        name="TOCEntry", fontName=font_name, fontSize=10, leading=16,
        textColor=DARK,
    ))

    # Build document
    page_width, page_height = A4
    margin = 18*mm

    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=20*mm,
        title="MWP Episode Ideas",
        author="My Weird Prompts",
    )

    story = []
    date_str = datetime.now().strftime("%B %d, %Y")

    # --- Title page ---
    story.append(Spacer(1, 30*mm))
    story.append(Paragraph(
        '<font color="#6366f1">MY WEIRD PROMPTS</font>',
        styles["DocSubtitle"],
    ))
    story.append(Paragraph(f"Episode Ideas — {date_str}", styles["DocTitle"]))
    story.append(Paragraph(
        f"{len(ideas)} prompt ideas to complement the existing catalog",
        styles["DocSubtitle"],
    ))

    # --- Table of contents ---
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(
        '<font color="#0f172a"><b>TABLE OF CONTENTS</b></font>',
        styles["IdeaTitle"],
    ))
    for idea in ideas:
        cat_label = f" [{idea['category']}]" if idea["category"] else ""
        story.append(Paragraph(
            f"{idea['number']}. {idea['title']}{cat_label}",
            styles["TOCEntry"],
        ))

    story.append(PageBreak())

    # --- Idea pages ---
    for idea in ideas:
        story.append(Paragraph(
            f"{idea['number']}. {idea['title']}",
            styles["IdeaTitle"],
        ))

        meta_parts = []
        if idea["category"]:
            meta_parts.append(f"Category: {idea['category']}")
        if idea["subcategory"]:
            meta_parts.append(f"Subcategory: {idea['subcategory']}")
        if idea["tags"]:
            meta_parts.append(f"Tags: {', '.join(idea['tags'])}")
        if meta_parts:
            story.append(Paragraph(" · ".join(meta_parts), styles["IdeaMeta"]))

        story.append(Paragraph(idea["description"], styles["IdeaBody"]))

        if idea["rationale"]:
            story.append(Paragraph(
                f'<i>Why this works: {idea["rationale"]}</i>',
                styles["IdeaRationale"],
            ))

        # Light divider
        story.append(Spacer(1, 2*mm))

    # Footer
    def add_footer(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(GRAY)
        canvas.setFont(font_name, 8)
        canvas.drawCentredString(page_width / 2, 10*mm, f"Page {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"  PDF saved: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _generate_batch(
    summary: dict,
    taxonomy_text: str,
    batch_size: int,
    focus: str | None,
    previous_titles: list[str],
    batch_num: int,
    total_batches: int,
) -> list[dict]:
    """Generate a single batch of ideas, aware of previously generated titles."""

    # Add dedup instruction if we have previous titles
    dedup_instruction = ""
    if previous_titles:
        titles_list = "\n".join(f"- {t}" for t in previous_titles)
        dedup_instruction = (
            f"\n\n## ALREADY GENERATED (do NOT repeat these topics)\n\n"
            f"{titles_list}\n\n"
            f"Generate completely DIFFERENT ideas from the ones above. "
            f"Do not revisit the same angles even with different titles.\n"
        )

    prompt = build_prompt(summary, taxonomy_text, batch_size, focus)
    prompt += dedup_instruction

    # Scale max_tokens based on batch size (~300 tokens per idea)
    max_tokens = min(batch_size * 400, 65536)

    print(f"  Batch {batch_num}/{total_batches}: requesting {batch_size} ideas "
          f"(max_tokens={max_tokens})...")

    response = call_gemini(
        prompt=prompt,
        model="google/gemini-3-flash-preview",
        max_tokens=max_tokens,
        temperature=0.9,
    )

    ideas = parse_ideas(response)
    print(f"  Batch {batch_num}/{total_batches}: parsed {len(ideas)} ideas")
    return ideas


def run(count: int = 15, focus: str | None = None) -> Path | None:
    """
    Run the idea generator end-to-end.

    For counts > 30, automatically batches requests to avoid token limits
    and improve idea diversity.

    Returns the PDF path if successful, None otherwise.
    """
    print("=" * 60)
    print("MWP Episode Idea Generator")
    print("=" * 60)

    # 1. Fetch episodes
    print("\n[1/5] Fetching episodes from database...")
    episodes = get_all_episodes()
    if not episodes:
        print("  ERROR: No episodes found. Check POSTGRES_URL.")
        return None
    print(f"  Found {len(episodes)} episodes")

    # 2. Analyze topics
    print("\n[2/5] Analyzing topic distribution...")
    summary = build_topic_summary(episodes)
    print(f"  {len(summary['tag_counts'])} unique tags, "
          f"{len(summary['category_counts'])} categories")

    # 3. Load taxonomy
    print("\n[3/5] Loading category taxonomy...")
    categories = load_categories()
    taxonomy_text = format_taxonomy(categories)
    print(f"  {len(categories.get('categories', []))} categories loaded")

    # 4. Generate ideas (with batching for large counts)
    BATCH_SIZE = 25
    all_ideas: list[dict] = []

    if count <= BATCH_SIZE:
        # Single batch
        print(f"\n[4/5] Generating {count} episode ideas via Gemini...")
        prompt = build_prompt(summary, taxonomy_text, count, focus)
        max_tokens = min(count * 400, 65536)
        response = call_gemini(
            prompt=prompt,
            model="google/gemini-3-flash-preview",
            max_tokens=max_tokens,
            temperature=0.9,
        )
        all_ideas = parse_ideas(response)
        if not all_ideas:
            print("  ERROR: Failed to parse any ideas from Gemini response")
            print("  Raw response (first 500 chars):")
            print(f"  {response[:500]}")
            return None
    else:
        # Multi-batch generation
        total_batches = (count + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\n[4/5] Generating {count} ideas in {total_batches} batches "
              f"of ~{BATCH_SIZE}...")

        remaining = count
        batch_num = 0
        while remaining > 0:
            batch_num += 1
            batch_count = min(remaining, BATCH_SIZE)
            previous_titles = [idea["title"] for idea in all_ideas]

            batch_ideas = _generate_batch(
                summary=summary,
                taxonomy_text=taxonomy_text,
                batch_size=batch_count,
                focus=focus,
                previous_titles=previous_titles,
                batch_num=batch_num,
                total_batches=total_batches,
            )

            if not batch_ideas:
                print(f"  WARNING: Batch {batch_num} returned 0 ideas, retrying...")
                batch_ideas = _generate_batch(
                    summary=summary,
                    taxonomy_text=taxonomy_text,
                    batch_size=batch_count,
                    focus=focus,
                    previous_titles=previous_titles,
                    batch_num=batch_num,
                    total_batches=total_batches,
                )

            if batch_ideas:
                # Renumber ideas to be sequential
                for idea in batch_ideas:
                    idea["number"] = len(all_ideas) + 1
                    all_ideas.append(idea)
                remaining -= len(batch_ideas)
            else:
                print(f"  ERROR: Batch {batch_num} failed twice, stopping.")
                break

            print(f"  Progress: {len(all_ideas)}/{count} ideas generated")

    print(f"  Total: {len(all_ideas)} ideas generated")

    # 5. Save output
    print("\n[5/5] Saving output...")
    date_slug = datetime.now().strftime("%Y-%m-%d")
    output_dir = Path(__file__).parent.parent / "output" / "episode-ideas" / date_slug

    md_path = save_markdown(all_ideas, output_dir)
    print(f"  Markdown: {md_path}")
    print(f"  Individual files: {output_dir}/01-*.md ... "
          f"{output_dir}/{len(all_ideas):03d}-*.md")

    pdf_path = output_dir / f"episode-ideas-{date_slug}.pdf"
    generate_pdf(all_ideas, pdf_path)

    print("\n" + "=" * 60)
    print(f"Done! {len(all_ideas)} ideas generated.")
    print(f"PDF: {pdf_path}")
    print("=" * 60)

    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="Generate MWP episode ideas")
    parser.add_argument(
        "--count", type=int, default=15,
        help="Number of ideas to generate (default: 15)",
    )
    parser.add_argument(
        "--focus", type=str, default=None,
        help="Focus on a specific category ID (e.g., 'local-ai')",
    )
    args = parser.parse_args()

    pdf_path = run(count=args.count, focus=args.focus)
    if not pdf_path:
        sys.exit(1)


if __name__ == "__main__":
    main()
