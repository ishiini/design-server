from fastapi import FastAPI
from fastapi.responses import Response
import anthropic
import subprocess
import tempfile
import os
import re
import base64
import io
import httpx

app = FastAPI()

# List available fonts at startup
FONTS_DIR = "/app/fonts"
ASSETS_DIR = "/tmp/assets"

def get_font_list():
    """Get all available .ttf fonts."""
    fonts = []
    if os.path.exists(FONTS_DIR):
        for f in sorted(os.listdir(FONTS_DIR)):
            if f.endswith(".ttf"):
                fonts.append(f)
    return fonts


def get_rendering_prompt(font_list, available_assets=None):
    """System prompt for Pass 2 (code rendering) and Pass 3 (review)."""
    asset_section = ""
    if available_assets:
        asset_list = "\n".join(f"    - {a['path']} ({a['description']})" for a in available_assets)
        asset_section = f"""
AVAILABLE IMAGE ASSETS:
The creative director requested generated imagery. These files are ready to use:
{asset_list}

Load them with: img_asset = Image.open("{available_assets[0]['path']}").convert("RGBA")
Then resize, position, mask, color-adjust, and composite them into your design.
You can apply filters, crop to shapes, add overlays, adjust opacity, or use them as masks.
These are high-quality AI-generated images — treat them as raw material to art-direct into your composition.
"""

    return f"""You render designs as Python code using Pillow and Cairo. You receive a CONTENT MANIFEST, LAYOUT, and COLOR + TYPE direction. Translate these into code that produces a DESIGNED poster — not just text on a background.

DESIGN MOVES — use at least 3 of these in every design. This is what separates a design from a text dump:

1. COLOR BLOCK: A bold rectangle of color that creates visual weight and zones the canvas.
   draw.rectangle([0, 0, int(width*0.55), int(height*0.4)], fill=accent_color)
   Place text ON TOP of color blocks for contrast. This is the #1 way to make a poster feel designed.

2. SCALE CONTRAST: Make the title MASSIVE (12-18% of canvas height). Make details TINY (2-3%). The dramatic difference between huge and small creates visual tension and hierarchy.

3. HORIZONTAL RULES: Thin lines that divide and structure the canvas. Use 1-2px weight.
   draw.line([(margin_x, y), (width - margin_x, y)], fill=rule_color, width=2)
   Place them between content sections, not as filler.

4. GEOMETRIC ACCENT: One bold shape — a circle, a thick vertical bar, or a diagonal — that anchors the composition and creates asymmetry.
   draw.ellipse([x-r, y-r, x+r, y+r], fill=accent_color)  # bold circle
   draw.rectangle([width-int(width*0.08), 0, width, height], fill=accent_color)  # side bar

5. TYPE AS SHAPE: When the title is big enough, it becomes a visual element itself. Let it fill the width. Let it touch edges (with margin). Stack words on separate lines for vertical rhythm.

6. SPATIAL ZONES: Divide the canvas into 2-3 distinct zones by background color or density. Top zone = title (bold, sparse). Middle zone = details (dense, structured). Bottom zone = secondary info or empty breathing room.

7. INFORMATION GRID: For program info (times, names, venues), use a consistent left-aligned column with fixed vertical rhythm. Each entry gets the same spacing. Align elements to invisible grid lines.

8. CONTRAST FLIP: Place some text in an inverted color scheme (light text on dark block, or dark text on light block within a darker canvas) to create focal points.

Every design MUST have: at least one color block, dramatic scale contrast between title and details, and at least one structural rule or geometric accent. Without these, the output is just a text list.

{asset_section}

TECHNICAL RULES:
- Output ONLY valid Python code, no explanations, no markdown
- Save to os.environ["OUTPUT_PATH"]
- Libraries: PIL, cairo, numpy, math only
- Canvas: Posters 2400x3200, Social 2160x2160, Logos 2048x2048. Never exceed 4000px.
- Wrap code in try/except and print errors
- Fonts at /app/fonts/ — NEVER use system font paths
  Load: ImageFont.truetype("/app/fonts/WorkSans-Bold.ttf", 120)
  On failure, fall back to another /app/fonts/ font, NOT ImageFont.load_default()

AVAILABLE FONTS:
{font_list}

Font guidance:
- Elegant/editorial: InstrumentSerif, LibreBaskerville, Lora, CrimsonPro, Italiana
- Modern/clean: WorkSans, Outfit, InstrumentSans, BricolageGrotesque
- Bold/display: BigShoulders, YoungSerif, Gloock, Boldonse, EricaOne
- Mono/technical: JetBrainsMono, IBMPlexMono, GeistMono, RedHatMono, DMMono
- Thin/minimal: PoiretOne, SmoochSans, Jura
- Mix intentionally — display font for titles, clean sans for details

MANDATORY: YOUR CODE MUST START WITH THIS HELPER FUNCTION.
Copy it exactly, then use safe_text() for EVERY text element. No exceptions.

```
def safe_text(draw, text, x, y, font_path, max_size, max_w, color, anchor="lt"):
    \"\"\"Draw text that NEVER exceeds max_w pixels wide. Auto-shrinks font if needed.\"\"\"
    size = max_size
    font = ImageFont.truetype(font_path, size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    while tw > max_w and size > 10:
        size = int(size * max_w / tw) - 1
        font = ImageFont.truetype(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
    draw.text((x, y), text, font=font, fill=color, anchor=anchor)
    th = bbox[3] - bbox[1]
    return y + th  # returns the y position BELOW this text
```

CODE STRUCTURE — follow this exact order:
1. Import libraries, define canvas size and margins (5% min on all sides)
   margin_x = int(width * 0.06)
   margin_y = int(height * 0.05)
   usable_w = width - 2 * margin_x
2. Define safe_text() helper (above)
3. Create background with a deliberate color
4. Track current_y starting at margin_y. Place text TOP TO BOTTOM:
   current_y = safe_text(draw, "TITLE", margin_x, current_y, font_path, size, usable_w, color)
   current_y += spacing
   current_y = safe_text(draw, "SUBTITLE", margin_x, current_y, font_path, size, usable_w, color)
   ...and so on for every element. Each call returns the next y position.
5. For multiple small items (like program entries), place them VERTICALLY, one per line.
   NEVER place multiple text blocks at the same y position unless they are explicitly in columns.
6. Add geometric/decorative elements in remaining space
7. Final pass: grain noise

CRITICAL RULES:
- EVERY text call must go through safe_text(). No raw draw.text() calls.
- max_w must ALWAYS be usable_w (canvas width minus both margins). Never wider.
- Program entries (performers, times, venues) go ONE PER LINE, stacked vertically.
- current_y must always increase. Nothing is placed above a previous element.
- No decorative filler (ruled lines, dot grids) unless they serve the layout. Empty space is better than noise.
"""


IDEATION_SYSTEM_PROMPT = """You are a creative director. You receive a structured brief and output a visual concept that a Python code renderer can execute.

The brief has CONTENT DATA (text that must appear) and a STRATEGIC BRIEF (brand direction). Read both carefully.

YOUR OUTPUT — exactly 5 sections:

CONCEPT: One sentence. What is the visual idea? Be concrete: "The title fills the top 40% of a deep navy canvas, with a bold vermillion color block behind the program grid in the lower half." Not abstract.

CONTENT MANIFEST: Copy every text string from the Content Data EXACTLY. Format:
  LARGE: [title]
  MEDIUM: [dates, location]
  SMALL: [details — one entry per line]
  CANVAS: [width]x[height]

DESIGN MOVES: Pick 3-4 from this list and describe how they apply:
  - COLOR BLOCK: A bold rectangle of color. State where (top third, left half, bottom strip, etc.) and what color direction.
  - SCALE CONTRAST: How big is the title vs the details? State title as % of canvas height.
  - HORIZONTAL RULES: Thin divider lines between sections. State how many and where.
  - GEOMETRIC ACCENT: One bold shape (circle, vertical bar, diagonal) that creates asymmetry. State what and where.
  - SPATIAL ZONES: How the canvas divides into 2-3 distinct areas by color or density.
  - CONTRAST FLIP: Where light text sits on dark block or vice versa.
  - INFORMATION GRID: How program details are structured (left-aligned, fixed rhythm, etc.)
You must pick at least COLOR BLOCK and SCALE CONTRAST. Describe each in one sentence with proportions.

COLOR + TYPE: Background color direction FIRST (deep navy, warm charcoal, off-white, black, etc.). Then 1-2 accent colors. Map font styles to hierarchy levels (bold geometric sans for title, light sans for details, mono for times, etc.).

IMAGE NEEDED: DALL-E prompt if needed, or "None — purely typographic and geometric."

RULES:
- No hex codes, no pixel coordinates, no font file names
- No poetry or metaphors — direct visual language only
- Every text from Content Data must appear in Content Manifest
- Keep total output under 250 words"""


def extract_code(response_text):
    """Extract Python code from Claude's response."""
    code_match = re.search(r'```python\n(.*?)```', response_text, re.DOTALL)
    if code_match:
        return code_match.group(1)
    return response_text


def execute_code(code, tmpdir):
    """Execute the rendering code and return (success, output_path_or_error)."""
    output_path = os.path.join(tmpdir, "output.png")
    script_path = os.path.join(tmpdir, "render.py")

    with open(script_path, "w") as f:
        f.write(code)

    env = os.environ.copy()
    env["OUTPUT_PATH"] = output_path

    result = subprocess.run(
        ["python", script_path],
        capture_output=True,
        text=True,
        timeout=120,
        env=env
    )

    if result.returncode != 0:
        return False, result.stderr

    if not os.path.exists(output_path):
        return False, "No image file was generated"

    return True, output_path


def compress_for_output(image_data, max_bytes=2_000_000):
    """Compress final image for n8n response. Returns (base64_string, format).
    n8n Cloud has tight memory limits, so keep response under ~3MB base64."""
    from PIL import Image as PILImage
    # Try PNG first — if small enough, keep it
    if len(image_data) <= max_bytes:
        return base64.b64encode(image_data).decode(), "png"
    # Convert to high-quality JPEG
    img = PILImage.open(io.BytesIO(image_data)).convert("RGB")
    for quality in [90, 80, 70, 60]:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= max_bytes:
            return base64.b64encode(buf.getvalue()).decode(), "jpeg"
    # Last resort: scale down + JPEG
    img = img.resize((int(img.width * 0.7), int(img.height * 0.7)), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode(), "jpeg"


def compress_for_review(image_data):
    """Compress image to stay under Anthropic's 5MB base64 limit.
    Base64 adds ~33% overhead, so raw data must stay under ~3.5MB."""
    from PIL import Image as PILImage
    # Base64 inflates by ~4/3, so 3.5MB raw → ~4.7MB base64 (safe under 5MB)
    MAX_RAW_BYTES = 3_500_000
    if len(image_data) <= MAX_RAW_BYTES:
        return image_data
    img = PILImage.open(io.BytesIO(image_data)).convert("RGB")
    # Scale down to 50%
    new_w = int(img.width * 0.5)
    new_h = int(img.height * 0.5)
    img = img.resize((new_w, new_h), PILImage.LANCZOS)
    # Use JPEG for review — much smaller than PNG, quality doesn't matter here
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    # If still too large, compress harder
    if buf.tell() > MAX_RAW_BYTES:
        buf = io.BytesIO()
        img = img.resize((int(new_w * 0.7), int(new_h * 0.7)), PILImage.LANCZOS)
        img.save(buf, format="JPEG", quality=60)
    return buf.getvalue()


def parse_image_request(concept_text):
    """Extract image generation request from creative concept."""
    # Look for IMAGE NEEDED: section
    match = re.search(r'IMAGE NEEDED:\s*(.+?)(?:\n\n|\Z)', concept_text, re.DOTALL)
    if not match:
        return None

    image_desc = match.group(1).strip()

    # Check if it's a "None" response
    if image_desc.lower().startswith("none"):
        return None

    return image_desc


def generate_image_asset(image_prompt, tmpdir):
    """Call DALL-E to generate an image asset. Returns path or None."""
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        print("OPENAI_API_KEY not set, skipping image generation")
        return None

    try:
        response = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "dall-e-3",
                "prompt": image_prompt,
                "n": 1,
                "size": "1024x1024",
                "response_format": "b64_json",
                "quality": "standard"
            },
            timeout=60.0
        )
        response.raise_for_status()
        data = response.json()
        image_b64 = data["data"][0]["b64_json"]

        # Save to temp file
        os.makedirs(ASSETS_DIR, exist_ok=True)
        asset_path = os.path.join(ASSETS_DIR, "generated_asset.png")
        with open(asset_path, "wb") as f:
            f.write(base64.b64decode(image_b64))

        return asset_path

    except Exception as e:
        print(f"Image generation failed: {e}")
        return None


@app.post("/generate")
async def generate_design(request: dict):
    """
    3-pass design generation with optional image generation:
    Pass 0 (optional) — DALL-E: generates imagery if the concept requires it
    Pass 1 — Creative Director: generates the concept/idea
    Pass 2 — Renderer: translates concept into Python/Pillow/Cairo code
    Pass 3 — Art Director Review: looks at the render, critiques, and improves
    """
    prompt = request.get("prompt", "")
    work_type = request.get("work_type", "poster")

    available_fonts = get_font_list()
    font_list = "\n".join(f"    - /app/fonts/{f}" for f in available_fonts)

    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=3,  # auto-retry on 429 (rate limit) and 529 (overloaded)
    )

    # ============================================================
    # PASS 1 — CREATIVE DIRECTOR: Generate the concept
    # ============================================================
    ideation_message = client.messages.create(
        model="claude-opus-4-20250514",
        max_tokens=2048,
        system=IDEATION_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"Here is the design brief:\n\n{prompt}\n\nWork type: {work_type}\n\nGenerate your creative concept."}
        ]
    )

    creative_concept = ideation_message.content[0].text

    # ============================================================
    # PASS 1.5 — IMAGE GENERATION (if needed)
    # ============================================================
    image_request = parse_image_request(creative_concept)
    available_assets = []

    if image_request:
        asset_path = generate_image_asset(image_request, None)
        if asset_path:
            available_assets.append({
                "path": asset_path,
                "description": image_request
            })

    # ============================================================
    # PASS 2 — RENDERER: Turn the concept into code
    # ============================================================
    rendering_prompt = get_rendering_prompt(font_list, available_assets if available_assets else None)

    asset_note = ""
    if available_assets:
        asset_note = f"\n\nIMPORTANT: A generated image asset is available at {available_assets[0]['path']} — load it with Image.open() and composite it into your design. Resize, position, mask, and art-direct it as needed."

    render_message = client.messages.create(
        model="claude-opus-4-20250514",
        max_tokens=8192,
        system=rendering_prompt,
        messages=[
            {"role": "user", "content": f"""Execute this creative concept as Python rendering code.

ORIGINAL BRIEF (contains content data + strategic direction):
{prompt}

WORK TYPE: {work_type}

CREATIVE CONCEPT (from creative director):
{creative_concept}
{asset_note}

CRITICAL REQUIREMENTS:
1. The CONTENT MANIFEST in the concept lists every text string that MUST appear. Render ALL of them. Missing text = failed output.
2. The LAYOUT section describes spatial structure — translate it directly to coordinate math.
3. Measure EVERY text element with textbbox() before placing it. Scale down any text that would exceed its allocated zone.
4. Use margins of at least 5% on all sides. No element touches the canvas edge.
5. Place elements top-to-bottom following the hierarchy: LARGE text first, then MEDIUM, then SMALL.

Write the Python code now. Output ONLY valid Python code."""}
        ]
    )

    code = extract_code(render_message.content[0].text)

    with tempfile.TemporaryDirectory() as tmpdir:
        success, result = execute_code(code, tmpdir)

        if not success:
            return {
                "error": "Code execution failed",
                "stderr": result,
                "code": code,
                "concept": creative_concept
            }

        # Read the rendered image
        with open(result, "rb") as f:
            render_data = f.read()

        review_data = compress_for_review(render_data)
        review_b64 = base64.b64encode(review_data).decode()
        # If compressed, it's JPEG; otherwise original PNG
        review_media_type = "image/jpeg" if len(render_data) > 3_500_000 else "image/png"

        # ============================================================
        # PASS 3 — ART DIRECTOR REVIEW: Critique and improve
        # ============================================================
        review_prompt = f"""Look at the rendered image and the creative concept. Fix every issue you find.

CREATIVE CONCEPT:
{creative_concept}

ORIGINAL BRIEF:
{prompt}

CHECK 1 — CONTENT COMPLETENESS (highest priority):
Compare the image against the CONTENT MANIFEST in the concept. Is every listed text string visible and readable? If ANY text is missing, clipped, or illegible, that is the #1 fix. List what's missing.

CHECK 2 — TECHNICAL ISSUES:
- Text overflowing or clipped at canvas edges
- Elements overlapping unintentionally
- Margins too thin (minimum 5% on all sides)
- Text too small to read at intended viewing distance

CHECK 3 — DESIGN QUALITY:
- Does the layout match what the concept's LAYOUT section described?
- Is hierarchy clear? Can you instantly tell what's most important?
- Is spacing consistent and intentional?
- Does it look finished and professional, not like a draft?

Fix all issues. Keep the same visual concept but improve execution. Write IMPROVED Python code. Output ONLY valid Python code, nothing else."""

        review_message = client.messages.create(
            model="claude-opus-4-20250514",
            max_tokens=8192,
            system=rendering_prompt,
            messages=[
                {"role": "user", "content": f"Execute this creative concept:\n\n{creative_concept}\n\nOriginal brief: {prompt}"},
                {"role": "assistant", "content": f"```python\n{code}\n```"},
                {"role": "user", "content": [
                    {
                        "type": "text",
                        "text": review_prompt
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": review_media_type,
                            "data": review_b64
                        }
                    }
                ]}
            ]
        )

        revised_code = extract_code(review_message.content[0].text)

        # Execute the revised code
        success2, result2 = execute_code(revised_code, tmpdir)

        if not success2:
            # If revision fails, return the first render (compressed)
            out_b64, out_fmt = compress_for_output(render_data)
            return {
                "image": out_b64,
                "format": out_fmt,
                "note": "Review pass failed, returning initial render"
            }

        with open(result2, "rb") as f:
            final_raw = f.read()

        out_b64, out_fmt = compress_for_output(final_raw)
        return {
            "image": out_b64,
            "format": out_fmt
        }


@app.get("/health")
async def health():
    fonts = get_font_list()
    openai_available = bool(os.environ.get("OPENAI_API_KEY"))
    return {
        "status": "ok",
        "fonts_loaded": len(fonts),
        "image_generation": "available" if openai_available else "not configured"
    }
