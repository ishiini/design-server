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

THE MOST IMPORTANT THING: Every design needs a VISUAL SYSTEM — a dominant graphic element that fills 30-50% of the canvas. Without this, the output is just text on a background. The concept will specify which system to use.

VISUAL SYSTEMS — the concept will specify which to use. Code patterns:

GRID MATRIX:
  cell = int(usable_w / cols)
  for row in range(rows):
      for col in range(cols):
          x, y = margin_x + col * cell, grid_y + row * cell
          filled = random.random() > 0.4
          if filled: draw.rectangle([x+2, y+2, x+cell-2, y+cell-2], fill=accent)
          else: draw.rectangle([x+2, y+2, x+cell-2, y+cell-2], outline=line_color, width=1)

CONCENTRIC RINGS:
  cx, cy = int(width * 0.6), int(height * 0.4)
  for i in range(num_rings, 0, -1):
      r = i * spacing
      draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=ring_color, width=2)

STRIPE SYSTEM:
  sw = int(usable_w / n)
  for i in range(n):
      x = margin_x + i * sw
      draw.rectangle([x, sy, x+sw, sy+sh], fill=accent if i%2==0 else bg)

GEOMETRIC CONSTRUCTION (use Cairo for smooth curves):
  ctx.arc(cx, cy, r, start, end); ctx.set_line_width(3); ctx.stroke()

PHOTOGRAPHIC CENTERPIECE (when IMAGE NEEDED is not "None"):
  img_asset = Image.open("/tmp/assets/generated_asset.png").convert("RGBA")
  # Scale image to fill most of the canvas — it IS the design
  target_w = int(usable_w * 0.85)  # or wider for full-bleed
  ratio = target_w / img_asset.width
  target_h = int(img_asset.height * ratio)
  img_asset = img_asset.resize((target_w, target_h), Image.LANCZOS)
  # Position centrally in the visual zone
  img_x = (width - target_w) // 2
  canvas.paste(img_asset, (img_x, current_y), img_asset)
  # Optional: add a colored border/frame, or let it bleed edge-to-edge
  # The image should dominate 40-60% of the poster. Title above, tagline below.

TYPOGRAPHIC WALL:
  Render the title at 25-40% of canvas height. Let it be the visual element itself.

The visual system occupies the MIDDLE zone (y=25% to y=70%). Title ABOVE, details BELOW.

PHOTOGRAPHIC LAYOUTS: When using PHOTOGRAPHIC CENTERPIECE, the image IS the design. Make it large (40-60% of canvas height). Options:
  - Full-bleed: image spans edge-to-edge with title overlaid in white/bold
  - Framed: image centered with colored border, title above, credits below
  - Cinematic: image fills top 60%, dark gradient overlay for title, tagline in lower band
  Do NOT leave the bottom half of the poster empty. Fill it with credits, tagline, or extend the image.

LAYOUT RULES:
- Title: 12-18% of canvas height. Dominates the top.
- Visual system: 30-50% of canvas. The centerpiece.
- Program info: stacked vertically below the visual system, one entry per line.
- Grain/noise as final pass on everything.
- Do NOT add random vertical bars, horizontal lines, or geometric accents unless they serve a clear structural purpose (e.g. dividing columns, separating sections). A stray line at the edge of the poster is visual clutter, not design.

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
- ONLY render text that appears in the CONTENT MANIFEST. Never invent labels, technical data, statistics, measurements, serial numbers, coordinates, or placeholder text. If it's not in the manifest, it does not go on the poster.
- Never render brackets [], placeholder text like "[not specified]", or "TBD". Omit missing information entirely.
- Fill empty space with the VISUAL SYSTEM (bigger, bolder), not with invented text or decorative lines.
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

VISUAL SYSTEM (required): Every design needs a dominant graphic element that fills 30-50% of the canvas. Pick ONE based on the brief. KEY RULE: If the strategic brief says "This design requires a generated photograph/illustration," you MUST pick PHOTOGRAPHIC CENTERPIECE and write a detailed DALL-E prompt in IMAGE NEEDED.
  - PHOTOGRAPHIC CENTERPIECE: A DALL-E generated image composited into the layout. USE THIS when the brief describes a physical scene, object, person, or atmosphere (rain, city, food, product, landscape, etc.).
  - GRID MATRIX: Rows and columns of cells, some filled, some empty. Good for: data, structure, schedules, technology, music.
  - CONCENTRIC RINGS: Circles radiating from a point. Good for: sound, broadcast, impact, growth, focus.
  - STRIPE SYSTEM: Bold parallel bars of alternating color. Good for: rhythm, speed, cinema, fashion, energy.
  - GEOMETRIC CONSTRUCTION: Overlapping arcs, circles, or angular shapes. Good for: architecture, science, precision, luxury.
  - TYPOGRAPHIC WALL: The title at extreme scale becoming the visual itself. Good for: bold statements, editorial, brutalist aesthetics.
State which system, where it sits on the canvas, and ONE sentence explaining why.

LAYOUT MOVES: Pick 2-3:
  - SCALE CONTRAST: Title as % of canvas height (12-18% for posters). Details at 2-3%.
  - SPATIAL ZONES: How the canvas divides (title zone, visual system zone, info zone).
  - GEOMETRIC ACCENT (optional, only if it serves structure): A shape that divides or frames content. Do NOT add random lines or bars just for decoration.
  - INFORMATION GRID: How program details are structured below the visual system.

COLOR + TYPE: Background color direction FIRST (deep navy, warm charcoal, off-white, black, etc.). Then 1-2 accent colors. Map font styles to hierarchy levels (bold geometric sans for title, light sans for details, mono for times, etc.).

IMAGE NEEDED: DALL-E prompt if needed, or "None — purely typographic and geometric."

VARIETY RULE: Do NOT always pick GRID MATRIX. Read the brief and match the visual system to the content:
  - Music/data/schedules → GRID MATRIX or CONCENTRIC RINGS (alternate between them)
  - Film/photography/products/food/scenes → PHOTOGRAPHIC CENTERPIECE
  - Bold editorial/manifestos/single-word titles → TYPOGRAPHIC WALL
  - Architecture/science/luxury → GEOMETRIC CONSTRUCTION
  - Fashion/cinema/speed/rhythm → STRIPE SYSTEM
  If the last 3 briefs all got the same system, pick a different one.

RULES:
- No hex codes, no pixel coordinates, no font file names
- No poetry or metaphors — direct visual language only
- Every text from Content Data must appear in Content Manifest
- NEVER invent content that is not in the brief. If a director name, venue, or detail is not provided, OMIT it. Never write "[not specified]" or any placeholder.
- NEVER add fake technical data, statistics, measurements, or labels. Only real content from the brief.
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
    """Call Ideogram to generate an image asset. Returns path or None."""
    ideogram_key = os.environ.get("IDEOGRAM_API_KEY")
    if not ideogram_key:
        print("IDEOGRAM_API_KEY not set, skipping image generation")
        return None

    try:
        response = httpx.post(
            "https://api.ideogram.ai/generate",
            headers={
                "Api-Key": ideogram_key,
                "Content-Type": "application/json"
            },
            json={
                "image_request": {
                    "prompt": image_prompt,
                    "model": "V_2",
                    "aspect_ratio": "ASPECT_10_16",
                    "style_type": "DESIGN",
                    "magic_prompt_option": "OFF",
                    "negative_prompt": "text, letters, words, watermark, blurry, low quality, distorted"
                }
            },
            timeout=90.0
        )
        response.raise_for_status()
        data = response.json()
        image_url = data["data"][0]["url"]

        # Download the image from Ideogram's URL (links expire)
        img_response = httpx.get(image_url, timeout=60.0)
        img_response.raise_for_status()

        os.makedirs(ASSETS_DIR, exist_ok=True)
        asset_path = os.path.join(ASSETS_DIR, "generated_asset.png")
        with open(asset_path, "wb") as f:
            f.write(img_response.content)

        return asset_path

    except Exception as e:
        print(f"Image generation failed: {e}")
        return None


@app.post("/generate")
async def generate_design(request: dict):
    """
    2-pass design generation with optional image generation:
    Pass 0 (optional) — DALL-E: generates imagery if the concept requires it
    Pass 1 — Creative Director (Sonnet): generates the concept/idea
    Pass 2 — Renderer (Sonnet): translates concept into Python/Pillow/Cairo code
    """
    prompt = request.get("prompt", "")
    work_type = request.get("work_type", "poster")

    available_fonts = get_font_list()
    font_list = "\n".join(f"    - /app/fonts/{f}" for f in available_fonts)

    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=3,
    )

    MODEL = "claude-sonnet-4-20250514"

    # ============================================================
    # PASS 1 — CREATIVE DIRECTOR: Generate the concept
    # ============================================================
    ideation_message = client.messages.create(
        model=MODEL,
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
        model=MODEL,
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
2. Use the safe_text() helper for EVERY text element. No raw draw.text() calls.
3. Use margins of at least 5% on all sides. No element touches the canvas edge.
4. Use at least 3 DESIGN MOVES: color block, scale contrast, and one more.
5. Place elements top-to-bottom, tracking current_y after each element.

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

        with open(result, "rb") as f:
            render_data = f.read()

        out_b64, out_fmt = compress_for_output(render_data)
        return {
            "image": out_b64,
            "format": out_fmt
        }


@app.get("/health")
async def health():
    fonts = get_font_list()
    ideogram_available = bool(os.environ.get("IDEOGRAM_API_KEY"))
    return {
        "status": "ok",
        "fonts_loaded": len(fonts),
        "image_generation": "ideogram available" if ideogram_available else "not configured"
    }
