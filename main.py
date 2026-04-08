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

    return f"""You are a Python developer who renders designs using Pillow and Cairo. You receive a creative concept with a CONTENT MANIFEST (exact text to render), a LAYOUT (spatial structure), and COLOR + TYPE direction. Your job: translate these into precise, working Python code that produces a polished design.

MANDATORY VISUAL RULES — violating any of these means the output is rejected:

1. COLOR: Never use only grays. The brief specifies a color direction — follow it. Use at least 2 distinct hue-bearing colors plus a neutral. Background should have a deliberate color, not default white or light gray. Make the dominant color bold, not timid.

2. TITLE SIZE: The primary text (brand name, event name) must be LARGE — at minimum 8% of canvas height as font size. For posters, 10-15% is better. The title is the anchor of the design. If it doesn't dominate, the design fails.

3. CONTRAST: Text must have high contrast against its background. Dark text on light bg OR light text on dark bg. Never dark gray on medium gray. Minimum perceived contrast ratio should be obvious at a glance.

4. FILL THE CANVAS: No more than 40% of the canvas should be empty/background. Use the layout structure from the concept to organize content across the full canvas. Empty space is only acceptable when it's clearly a deliberate compositional choice with elements on multiple sides of it.

5. TEXTURE: Every design gets a grain/noise pass as the final step. Add subtle noise (numpy random, alpha ~15-25) over the entire canvas. This single step transforms flat digital output into something with tactile quality.

6. ALL CONTENT: Every text string in the CONTENT MANIFEST must be rendered and fully visible. No text may be cut off at any edge. No text may be omitted.

RENDERING LIBRARIES:

**Cairo (pycairo)** — USE FOR:
- Complex shapes, silhouettes, organic forms, curves, bezier paths
- Smooth anti-aliased vector rendering at any scale
- Path operations (combine, subtract, clip shapes)
- Gradient fills along complex paths
- Anything that needs smooth, curved, or freeform shapes
- Movie posters, album covers, illustrations with figurative elements
- Import as: import cairo

**Pillow (PIL)** — USE FOR:
- Geometric patterns, grids, dot arrays, parallel lines
- Text rendering with custom fonts (Pillow has better font support)
- Pixel-level textures: grain, noise, scanlines, halftone
- Image compositing and alpha blending
- Simple rectangles, circles, and color fields
- Import as: from PIL import Image, ImageDraw, ImageFont, ImageFilter

**COMBINE BOTH** for best results:
- Render complex shapes with Cairo to a temporary PNG
- Load that PNG into Pillow with Image.open()
- Add text, textures, grain, and fine details with Pillow
- Save final result from Pillow

Example pattern for combining:
```
import cairo
from PIL import Image, ImageDraw, ImageFont
import os

# Phase 1: Cairo for complex shapes
width, height = 3840, 2160
surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
ctx = cairo.Context(surface)
# ... draw complex shapes with ctx ...
surface.write_to_png("/tmp/cairo_layer.png")

# Phase 2: Pillow for text, texture, compositing
img = Image.open("/tmp/cairo_layer.png").convert("RGBA")
draw = ImageDraw.Draw(img)
font = ImageFont.truetype("/app/fonts/WorkSans-Bold.ttf", 120)
# ... add text, grain, finishing touches ...
img.save(os.environ["OUTPUT_PATH"])
```

{asset_section}

TECHNICAL RULES:
- Output ONLY valid Python code, no explanations, no markdown
- Save the final image to the path stored in the OUTPUT_PATH environment variable
- Only use PIL, cairo, numpy, and math — no other graphics libraries
- Canvas sizes (EXACT — do not exceed these, server has limited memory):
  Posters: 2400x3200, Social: 2160x2160, Logos: 2048x2048
  NEVER go above 4000px on any dimension. No 300dpi print calculations.
- Always wrap code in try/except and print errors
- Use high-resolution rendering (no pixelation on text or shapes)
- CRITICAL: Fonts are at /app/fonts/ — NEVER use /System/Library/Fonts/ or any macOS/Windows paths
  Always load fonts like: ImageFont.truetype("/app/fonts/WorkSans-Bold.ttf", 120)
  If a font fails to load, fall back to another /app/fonts/ font, NOT ImageFont.load_default()

AVAILABLE FONTS (use full paths with Pillow's ImageFont.truetype()):
{font_list}

For Cairo text, load fonts with:
ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
But prefer Pillow for text rendering as it supports the custom .ttf fonts above.

Font guidance:
- For elegant/editorial: InstrumentSerif, LibreBaskerville, Lora, CrimsonPro, Italiana
- For modern/clean: WorkSans, Outfit, InstrumentSans, BricolageGrotesque
- For bold/display: BigShoulders, YoungSerif, Gloock, Boldonse, EricaOne
- For mono/technical: JetBrainsMono, IBMPlexMono, GeistMono, RedHatMono, DMMono
- For thin/minimal: PoiretOne, SmoochSans, Jura
- For handwritten: NothingYouCouldDo
- For pixel/retro: PixelifySans, Silkscreen
- For nature/parks: NationalPark
- Mix fonts intentionally — a display font for headlines, a clean sans for labels

CODE STRUCTURE — follow this order:
1. Define canvas size, margins (5% minimum on all sides), and color palette as variables
2. Create background with deliberate color (not white)
3. Place elements top-to-bottom following hierarchy from CONTENT MANIFEST
4. For EACH text element: load font → measure with textbbox → check fits in allocated zone → scale down if needed → draw
5. Add geometric/decorative elements (rules, shapes, blocks) that support the layout
6. Final pass: add grain noise over entire canvas using numpy

COMMON BUGS TO AVOID:
- TEXT CLIPPING (CRITICAL): ALWAYS measure text width before drawing. Use this pattern:
  font = ImageFont.truetype("/app/fonts/SomeFont.ttf", size)
  bbox = draw.textbbox((0, 0), text, font=font)
  text_width = bbox[2] - bbox[0]
  max_width = canvas_width - left_margin - right_margin
  if text_width > max_width:
      # Scale down the font size proportionally
      size = int(size * max_width / text_width)
      font = ImageFont.truetype("/app/fonts/SomeFont.ttf", size)
  NEVER place text without first verifying it fits within canvas_width minus both margins.
  This applies to EVERY text element — titles, subtitles, labels, everything.
- ELEMENT OVERLAP (CRITICAL): Before placing any element, verify its bounding box does not
  intersect with any previously placed element. Keep a running list of occupied rectangles
  and check each new element against all existing ones.
- Cairo uses BGRA byte order — when loading Cairo output into Pillow, the colors
  may be swapped. Fix by splitting channels and recombining:
  r, g, b, a = img.split(); img = Image.merge("RGBA", (b, g, r, a))
  OR just use surface.write_to_png() and Image.open() which handles it correctly
- Always check that shapes don't overflow the canvas
- When overlapping elements, draw back-to-front (background first)
- For Cairo: always call ctx.save() before transforms and ctx.restore() after
- For Pillow transparency: create images with mode 'RGBA' and use Image.alpha_composite()
- Test font loading with try/except and fall back to default if font file not found
- When drawing text with Pillow, use draw.textbbox() to measure text size before positioning
  and SCALE DOWN if it would exceed the available width

FINAL CHECKLIST — verify before outputting code:
1. Every text string from CONTENT MANIFEST is rendered and fully visible
2. No text is clipped at any canvas edge (all text measured before drawing)
3. Title font size is at least 8% of canvas height
4. Background is a deliberate color, not plain white
5. At least 2 distinct hue-bearing colors are used
6. Grain/noise texture is applied as the last step
7. All coordinates are calculated mathematically from canvas dimensions, not hardcoded
"""


IDEATION_SYSTEM_PROMPT = """You are a creative director. You receive a structured brief with two sections: CONTENT DATA (the actual text that must appear on the design) and a STRATEGIC BRIEF (brand direction and design principles).

Your job: generate ONE clear visual concept that the renderer can execute in Python code.

THE BRIEF FORMAT YOU WILL RECEIVE:
The brief contains a CONTENT DATA section listing every text element by hierarchy (Primary, Secondary, Tertiary) plus canvas dimensions, followed by a STRATEGIC BRIEF with brand direction. Read both carefully.

YOUR OUTPUT — exactly 5 short sections:

CONCEPT: One sentence. The core visual idea. What's clever about it? Keep it concrete and executable — no metaphors.

CONTENT MANIFEST: List every text string that must appear on the final design, grouped by visual hierarchy. Copy these EXACTLY from the Content Data — do not paraphrase, abbreviate, or add text that wasn't in the brief. Format:
  LARGE: [festival name or brand name]
  MEDIUM: [dates, tagline, location]
  SMALL: [artist names, times, venues, details]
  CANVAS: [width]x[height]

LAYOUT: Describe the spatial structure in concrete terms the renderer can follow. Use proportional language: "top 15% is date bar," "left column 60% width holds program info," "title centered in upper third." State the grid logic: how many columns, how content blocks relate. State alignment: flush left, centered, justified. State margins as percentage of canvas.

COLOR + TYPE: State the background color direction FIRST (dark, light, off-white, black, deep blue, etc. — never "white" or "light gray" unless the concept demands it). Then state 2-3 accent/text color directions. Map font style directions (geometric sans, humanist serif, etc.) to hierarchy levels. State the color harmony type.

IMAGE NEEDED: If the concept needs a real photograph or illustration that can't be drawn with geometry, write a DALL-E prompt. Otherwise: "None — purely typographic and geometric."

RULES:
- No hex codes, no pixel coordinates, no font file names
- No poetry, no metaphors, no similes — direct language only
- The CONTENT MANIFEST must include every text element from the brief's Content Data. Missing text = failed output.
- LAYOUT must be specific enough that a coder can translate it to coordinates using math. "Centered" is not enough — say where on the canvas.
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

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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
