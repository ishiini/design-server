from fastapi import FastAPI
import os
import re
import base64
import io
import json
import httpx

app = FastAPI()

FONTS_DIR = "/app/fonts"

# ============================================================
# UTILITIES
# ============================================================

def get_font_list():
    """Get all available .ttf fonts."""
    fonts = []
    if os.path.exists(FONTS_DIR):
        for f in sorted(os.listdir(FONTS_DIR)):
            if f.endswith(".ttf"):
                fonts.append(f)
    return fonts


def compress_for_output(image_data, max_bytes=2_000_000):
    """Compress final image for n8n response. Keeps under ~3MB base64."""
    from PIL import Image as PILImage
    if len(image_data) <= max_bytes:
        return base64.b64encode(image_data).decode(), "png"
    img = PILImage.open(io.BytesIO(image_data)).convert("RGB")
    for quality in [90, 80, 70, 60]:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= max_bytes:
            return base64.b64encode(buf.getvalue()).decode(), "jpeg"
    img = img.resize((int(img.width * 0.7), int(img.height * 0.7)), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode(), "jpeg"


def compress_for_vision(image_bytes, max_bytes=3_000_000):
    """Compress image for sending to GPT-4o Vision API."""
    from PIL import Image as PILImage
    if len(image_bytes) <= max_bytes:
        return base64.b64encode(image_bytes).decode(), "png"
    img = PILImage.open(io.BytesIO(image_bytes)).convert("RGB")
    img = img.resize((int(img.width * 0.5), int(img.height * 0.5)), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode(), "jpeg"


def parse_json_response(text):
    """Extract JSON from a GPT response that might have markdown fences."""
    json_match = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    # Try parsing the whole thing
    # Strip any leading/trailing whitespace or text before {
    brace_start = text.find('{')
    if brace_start >= 0:
        return json.loads(text[brace_start:])
    return json.loads(text)


def openai_headers():
    return {
        "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
        "Content-Type": "application/json"
    }


def extract_content_data(brief):
    """Extract only the text strings from SECTION 1 — CONTENT DATA.
    Returns a clean list of text that should appear on the design.
    The strategic brief (Section 2) is stripped out so GPT-4o can't pull from it."""
    # Try to find Section 1
    section1_match = re.search(
        r'SECTION 1.*?CONTENT DATA\s*\n(.*?)(?:SECTION 2|---|\Z)',
        brief, re.DOTALL | re.IGNORECASE
    )
    if section1_match:
        return section1_match.group(1).strip()
    # Fallback: return the whole brief if we can't parse sections
    return brief


# ============================================================
# PASS 1 — IMAGE GENERATION (gpt-image-1)
# ============================================================

def generate_poster_image(brief, work_type):
    """Generate the poster visual with gpt-image-1. No text in image."""
    size_map = {
        "poster": "1024x1536",
        "social": "1024x1024",
        "logo": "1024x1024"
    }
    size = size_map.get(work_type, "1024x1536")

    image_prompt = f"""Create the visual layer for a {work_type}. No text, no letters, no numbers, no words anywhere in the image. Typography will be added separately.

Leave breathing room at the top and bottom of the canvas for text to be overlaid later.

The brief below contains all the creative direction — follow it closely. If it names an artist, match that artist's visual language. If it specifies a color palette, use those colors. If it describes a mood or style, that is the style.

{brief}"""

    response = httpx.post(
        "https://api.openai.com/v1/images/generations",
        headers=openai_headers(),
        json={
            "model": "gpt-image-1",
            "prompt": image_prompt,
            "n": 1,
            "size": size,
            "quality": "medium"
        },
        timeout=120.0
    )
    response.raise_for_status()
    data = response.json()
    return base64.b64decode(data["data"][0]["b64_json"])


# ============================================================
# PASS 2 — TEXT PLACEMENT (GPT-4o Vision)
# ============================================================

def get_text_placement(image_bytes, content_data, work_type, font_list):
    """GPT-4o sees the generated image and decides exactly where text goes."""
    img_b64, img_fmt = compress_for_vision(image_bytes)
    media_type = f"image/{img_fmt}"

    prompt = f"""You are a typography director. You see a {work_type} background image. Your job: place the text listed below onto this image with the right fonts, colors, and positions.

HERE IS EVERY TEXT STRING THAT MUST APPEAR ON THIS DESIGN. Use these EXACTLY. Do not add, invent, or paraphrase anything:

{content_data}

WORK TYPE: {work_type}

AVAILABLE FONTS (use exact filenames from this list):
{font_list}

Font guidance:
- Bold display titles: BigShoulders, YoungSerif, EricaOne, Boldonse, Gloock
- Clean sans: WorkSans, Outfit, InstrumentSans, BricolageGrotesque
- Elegant serif: InstrumentSerif, LibreBaskerville, Lora, CrimsonPro, Italiana
- Mono/technical: JetBrainsMono, IBMPlexMono, GeistMono
- Thin/minimal: PoiretOne, SmoochSans, Jura

ANALYZE THE IMAGE CAREFULLY BEFORE PLACING ANY TEXT:
- Where are the DARK areas? (place LIGHT text here — white, cream)
- Where are the LIGHT areas? (place DARK text here — black, charcoal)
- Where is the visual focus? (NEVER cover the main graphic element with text)
- Where is breathing room or empty space? (text goes here FIRST)

CONTRAST IS THE #1 PRIORITY. Every text element must have strong contrast against the background directly behind it. If you place white text, the area behind it MUST be dark. If you place dark text, the area behind it MUST be light. If there is no area with clean contrast, you MUST set an overlay (gradient or darken) to create contrast. A poster with unreadable text is a failed poster, period.

PLACEMENT STRATEGY:
- Put text in margins, edges, or dark border areas — NOT on top of the main graphic/illustration
- If the image has a border or frame, place text in that border
- The title can overlap the image IF you add a strong overlay behind it
- Program details (times, performers) should be grouped together in one clean zone, not scattered
- If the image is mostly light, use dark text. If mostly dark, use light text.

OUTPUT this exact JSON structure:
{{
  "overlay": {{
    "type": "none|gradient_top|gradient_bottom|gradient_both|darken_all",
    "opacity": 0.4,
    "color": [0, 0, 0]
  }},
  "texts": [
    {{
      "content": "EXACT TEXT STRING FROM BRIEF",
      "role": "title",
      "x_percent": 8,
      "y_percent": 5,
      "max_width_percent": 84,
      "font_file": "WorkSans-Bold.ttf",
      "size_percent": 12,
      "color_hex": "#FFFFFF",
      "align": "left"
    }}
  ]
}}

RULES:
- size_percent = text height as % of canvas height. Title: 8-15%. Subtitle: 3-5%. Details: 1.5-3%.
- x/y_percent = position from top-left corner as % of canvas dimensions.
- max_width_percent = maximum text width as % of canvas width.
- ONLY place the text strings listed above. Nothing else. No invented credits, taglines, or descriptions.
- If background is busy where text goes, set overlay to improve readability.
- Pick 2-3 fonts maximum. One for titles, one for details.
- Output ONLY valid JSON. No explanations."""

    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers=openai_headers(),
        json={
            "model": "gpt-4o",
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{img_b64}"
                        }
                    },
                    {"type": "text", "text": prompt}
                ]
            }],
            "max_tokens": 2048
        },
        timeout=60.0
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"]
    return parse_json_response(text)


# ============================================================
# PASS 3 — RENDER TEXT (PIL)
# ============================================================

def render_text_on_image(image_bytes, placement):
    """Composite text onto the poster image using PIL."""
    from PIL import Image as PILImage, ImageDraw, ImageFont
    import numpy as np

    img = PILImage.open(io.BytesIO(image_bytes)).convert("RGBA")
    width, height = img.size

    # --- Apply overlay for text readability ---
    overlay_spec = placement.get("overlay", {})
    overlay_type = overlay_spec.get("type", "none")
    if overlay_type != "none":
        opacity = overlay_spec.get("opacity", 0.3)
        oc = tuple(overlay_spec.get("color", [0, 0, 0]))
        overlay = PILImage.new("RGBA", (width, height), (0, 0, 0, 0))

        if overlay_type == "gradient_top":
            arr = np.zeros((height, width, 4), dtype=np.uint8)
            zone = int(height * 0.35)
            for y in range(zone):
                a = int(255 * opacity * (1 - y / zone))
                arr[y, :] = [oc[0], oc[1], oc[2], a]
            overlay = PILImage.fromarray(arr, "RGBA")

        elif overlay_type == "gradient_bottom":
            arr = np.zeros((height, width, 4), dtype=np.uint8)
            start = int(height * 0.65)
            zone = height - start
            for y in range(start, height):
                a = int(255 * opacity * ((y - start) / zone))
                arr[y, :] = [oc[0], oc[1], oc[2], a]
            overlay = PILImage.fromarray(arr, "RGBA")

        elif overlay_type == "gradient_both":
            arr = np.zeros((height, width, 4), dtype=np.uint8)
            # Top gradient
            zone_top = int(height * 0.35)
            for y in range(zone_top):
                a = int(255 * opacity * (1 - y / zone_top))
                arr[y, :] = [oc[0], oc[1], oc[2], a]
            # Bottom gradient
            start_bot = int(height * 0.65)
            zone_bot = height - start_bot
            for y in range(start_bot, height):
                a = int(255 * opacity * ((y - start_bot) / zone_bot))
                arr[y, :] = [oc[0], oc[1], oc[2], a]
            overlay = PILImage.fromarray(arr, "RGBA")

        elif overlay_type == "darken_all":
            a = int(255 * opacity)
            overlay = PILImage.new("RGBA", (width, height), (oc[0], oc[1], oc[2], a))

        img = PILImage.alpha_composite(img, overlay)

    # --- Place text elements ---
    draw = ImageDraw.Draw(img)

    for text_spec in placement.get("texts", []):
        content = str(text_spec.get("content", ""))
        if not content:
            continue

        x = int(width * text_spec.get("x_percent", 8) / 100)
        y = int(height * text_spec.get("y_percent", 5) / 100)
        max_w = int(width * text_spec.get("max_width_percent", 84) / 100)
        color = text_spec.get("color_hex", "#FFFFFF")
        font_file = text_spec.get("font_file", "WorkSans-Bold.ttf")
        size = int(height * text_spec.get("size_percent", 5) / 100)
        align = text_spec.get("align", "left")

        # Load font with fallback chain
        font = None
        font_path = os.path.join(FONTS_DIR, font_file)
        try:
            font = ImageFont.truetype(font_path, size)
        except Exception:
            try:
                font = ImageFont.truetype(os.path.join(FONTS_DIR, "WorkSans-Bold.ttf"), size)
            except Exception:
                font = ImageFont.load_default()

        # Auto-shrink text if it exceeds max width
        bbox = draw.textbbox((0, 0), content, font=font)
        tw = bbox[2] - bbox[0]
        while tw > max_w and size > 10:
            size = int(size * max_w / tw) - 1
            try:
                font = ImageFont.truetype(font_path, size)
            except Exception:
                font = ImageFont.truetype(os.path.join(FONTS_DIR, "WorkSans-Bold.ttf"), size)
            bbox = draw.textbbox((0, 0), content, font=font)
            tw = bbox[2] - bbox[0]

        # Handle alignment
        draw_x = x
        if align == "center":
            draw_x = x + (max_w - tw) // 2
        elif align == "right":
            draw_x = x + max_w - tw

        draw.text((draw_x, y), content, font=font, fill=color)

    # --- Add subtle grain noise ---
    img_rgb = img.convert("RGB")
    arr = np.array(img_rgb, dtype=np.int16)
    noise = np.random.normal(0, 4, arr.shape).astype(np.int16)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    result = PILImage.fromarray(arr, "RGB")

    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()


# ============================================================
# PASS 4 — CRITIQUE (GPT-4o Vision)
# ============================================================

def critique_design(composed_bytes, brief, work_type):
    """GPT-4o sees the final poster and critiques it."""
    img_b64, img_fmt = compress_for_vision(composed_bytes)
    media_type = f"image/{img_fmt}"

    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers=openai_headers(),
        json={
            "model": "gpt-4o",
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{img_b64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": f"""You are a senior design director. Critique this {work_type}.

Brief: {brief}

Score 1-10 on:
1. TEXT READABILITY: Can all text be clearly read?
2. HIERARCHY: Is the title the most prominent element?
3. COMPOSITION: Does text placement work with the image?
4. COMPLETENESS: Is all required text present?
5. OVERALL QUALITY: Does this look professionally designed?

Output JSON:
{{
  "approved": true/false,
  "score": 7,
  "fixes": [
    {{
      "text_index": 0,
      "field": "y_percent|x_percent|color_hex|size_percent|font_file",
      "new_value": "corrected value",
      "reason": "why"
    }}
  ]
}}

Score 7+ = approved. Only flag real problems. Max 3 fixes.
Output ONLY valid JSON."""
                    }
                ]
            }],
            "max_tokens": 1024
        },
        timeout=60.0
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"]
    return parse_json_response(text)


# ============================================================
# MAIN ENDPOINT
# ============================================================

def generate_logo_svg(brief, content_data):
    """Generate a logo as SVG using GPT-4o to write the SVG code directly."""
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers=openai_headers(),
        json={
            "model": "gpt-4o",
            "messages": [{
                "role": "user",
                "content": f"""You are a logo designer. Create a professional logo as SVG code.

BRAND: {content_data}

CREATIVE DIRECTION:
{brief}

OUTPUT: A complete, valid SVG document. The logo should be:
- Clean vector shapes only — no raster images, no filters, no bitmap effects
- Viewbox 0 0 512 512 (square, scalable)
- Maximum 3 colors plus black/white
- Simple, memorable, and professional
- Include the brand name as text using a clean sans-serif font (font-family: sans-serif)
- The logomark (icon/symbol) should work without the text too

Write ONLY the SVG code. Start with <svg and end with </svg>. No explanations, no markdown fences."""
            }],
            "max_tokens": 4096
        },
        timeout=60.0
    )
    response.raise_for_status()
    svg_text = response.json()["choices"][0]["message"]["content"]

    # Extract SVG from response (strip any surrounding text/fences)
    svg_match = re.search(r'(<svg[\s\S]*?</svg>)', svg_text)
    if svg_match:
        return svg_match.group(1)
    return svg_text


def svg_to_png(svg_string, width=2048, height=2048):
    """Convert SVG to PNG using cairosvg."""
    import cairosvg
    png_bytes = cairosvg.svg2png(
        bytestring=svg_string.encode('utf-8'),
        output_width=width,
        output_height=height
    )
    return png_bytes


@app.post("/generate")
async def generate_design(request: dict):
    """
    Design generation pipeline:
    - Posters/Social: gpt-image-1 visual → GPT-4o text placement → PIL render → GPT-4o critique
    - Logos: GPT-4o generates SVG directly → cairosvg renders to PNG
    """
    prompt = request.get("prompt", "")
    work_type = request.get("work_type", "poster")

    try:
        # === LOGO PIPELINE (SVG) ===
        if work_type == "logo":
            print("LOGO PIPELINE: Generating SVG...")
            content_data = extract_content_data(prompt)
            svg_code = generate_logo_svg(prompt, content_data)
            print(f"SVG generated: {len(svg_code)} chars")

            # Render to PNG for preview
            try:
                png_bytes = svg_to_png(svg_code)
                out_b64, out_fmt = compress_for_output(png_bytes)
                return {
                    "image": out_b64,
                    "format": out_fmt,
                    "svg": svg_code
                }
            except Exception as e:
                print(f"SVG to PNG failed: {e}, returning SVG only")
                # Return SVG as base64 text if rendering fails
                svg_b64 = base64.b64encode(svg_code.encode('utf-8')).decode()
                return {
                    "image": svg_b64,
                    "format": "svg",
                    "svg": svg_code
                }

        # === POSTER / SOCIAL PIPELINE (raster) ===
        # PASS 1 — Generate poster visual
        print("PASS 1: Generating poster image...")
        image_bytes = generate_poster_image(prompt, work_type)
        print(f"PASS 1 complete: {len(image_bytes)} bytes")

        # UPSCALE to target resolution for sharp text rendering
        from PIL import Image as PILImage
        target_sizes = {
            "poster": (2400, 3200),
            "social": (2160, 2160),
            "logo": (2048, 2048)
        }
        target_w, target_h = target_sizes.get(work_type, (2400, 3200))
        img_raw = PILImage.open(io.BytesIO(image_bytes))
        if img_raw.width < target_w or img_raw.height < target_h:
            print(f"Upscaling from {img_raw.width}x{img_raw.height} to {target_w}x{target_h}...")
            img_upscaled = img_raw.resize((target_w, target_h), PILImage.LANCZOS)
            buf = io.BytesIO()
            img_upscaled.save(buf, format="PNG")
            image_bytes = buf.getvalue()
            print(f"Upscale complete: {len(image_bytes)} bytes")

        # PASS 2 — Text placement (only receives content strings, not strategic brief)
        print("PASS 2: Getting text placement...")
        font_list = "\n".join(f"    - {f}" for f in get_font_list())
        content_data = extract_content_data(prompt)
        print(f"Content data extracted: {content_data[:100]}...")
        placement = get_text_placement(image_bytes, content_data, work_type, font_list)
        print(f"PASS 2 complete: {len(placement.get('texts', []))} text elements")

        # PASS 3 — Render text
        print("PASS 3: Rendering text on image...")
        composed = render_text_on_image(image_bytes, placement)
        print(f"PASS 3 complete: {len(composed)} bytes")

        # PASS 4 — Critique
        print("PASS 4: Critiquing design...")
        try:
            critique = critique_design(composed, prompt, work_type)
            score = critique.get("score", 7)
            print(f"PASS 4 complete: score={score}, approved={critique.get('approved', True)}")

            # Apply fixes if not approved (one round only)
            if not critique.get("approved", True) and critique.get("fixes"):
                print(f"Applying {len(critique['fixes'])} fixes...")
                for fix in critique["fixes"]:
                    idx = fix.get("text_index")
                    field = fix.get("field")
                    new_val = fix.get("new_value")
                    texts = placement.get("texts", [])
                    if idx is not None and field and new_val is not None and idx < len(texts):
                        # Convert numeric strings to numbers for numeric fields
                        if field in ("x_percent", "y_percent", "size_percent", "max_width_percent"):
                            try:
                                new_val = float(new_val)
                            except (ValueError, TypeError):
                                continue
                        texts[idx][field] = new_val

                composed = render_text_on_image(image_bytes, placement)
                print("Fix round complete")

        except Exception as e:
            # If critique fails, just use the original composition
            print(f"Critique failed (using original): {e}")

        # Compress and return
        out_b64, out_fmt = compress_for_output(composed)
        return {
            "image": out_b64,
            "format": out_fmt
        }

    except Exception as e:
        import traceback
        print(f"Generation failed: {traceback.format_exc()}")
        return {
            "error": str(e),
            "stderr": traceback.format_exc()
        }


@app.get("/health")
async def health():
    fonts = get_font_list()
    openai_available = bool(os.environ.get("OPENAI_API_KEY"))
    return {
        "status": "ok",
        "fonts_loaded": len(fonts),
        "image_generation": "gpt-image-1" if openai_available else "not configured",
        "architecture": "gpt-image-1 + gpt-4o-vision + PIL"
    }
