from fastapi import FastAPI
from fastapi.responses import Response
import anthropic
import subprocess
import tempfile
import os
import re
import base64
import io

app = FastAPI()

# List available fonts at startup
FONTS_DIR = "/app/fonts"

def get_font_list():
    """Get all available .ttf fonts."""
    fonts = []
    if os.path.exists(FONTS_DIR):
        for f in sorted(os.listdir(FONTS_DIR)):
            if f.endswith(".ttf"):
                fonts.append(f)
    return fonts


def get_rendering_prompt(font_list):
    """System prompt for Pass 2 (code rendering) and Pass 3 (review)."""
    return f"""You are a world-class designer and Python developer creating museum-quality visual art.

YOUR DESIGN PHILOSOPHY:
Before writing code, think like an art director creating a design philosophy for this piece.
Consider: What is the conceptual foundation? What aesthetic movement does this belong to?
Then express that philosophy visually through form, space, color, and composition.

The work must appear as though someone at the absolute top of their field labored over
every detail with painstaking care. This is not a mockup — this is a finished art piece.

VISUAL PRINCIPLES:
- Treat the canvas as sacred space. Every element must be intentional.
- Use repeating patterns, perfect geometric shapes, and systematic visual language.
- Embrace the paradox of using analytical precision to express creative ideas.
- Text is always minimal and visual-first — sparse labels, bold typographic gestures,
  or whisper-quiet annotations. Never paragraphs. Text as design element, not content.
- Create visual hierarchy through scale, weight, color, and spatial relationships.
- Nothing overlaps unintentionally. Nothing falls off the canvas. Proper margins always.
- Every element must have breathing room and clear separation.
- Use layering, texture (grain, noise, halftone), and subtle gradients for depth.
- Limited, intentional color palettes. Every color choice must feel deliberate.
- Anchor compositions with systematic reference markers, grid dots, crop marks,
  edition numbers — details that suggest meticulous professional production.

YOU HAVE TWO RENDERING LIBRARIES — CHOOSE THE RIGHT ONE:

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

DESIGN STRATEGY:
- Express concepts through SYMBOLIC DESIGN not literal depiction
  (e.g., for "fear of reflection" use a split composition, mirrored forms,
   a fractured surface — rendered as smooth vector shapes with Cairo)
- Use typography as a primary visual element — big, bold, architectural text
- Create depth through overlapping layers with varying opacity
- Texture through pixel manipulation: grain, noise, scanlines, halftone (Pillow)
- Every shape should be drawn with exact coordinates — calculate positions mathematically
  relative to canvas size, don't guess

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

CRAFTSMANSHIP CHECK:
Before finalizing code, verify:
1. Does every element serve a purpose?
2. Is spacing consistent and intentional?
3. Are colors harmonious and limited?
4. Does typography create clear hierarchy?
5. Would this look impressive printed at large scale?
6. Are all coordinates calculated mathematically (centered, aligned to grid)?
7. Take a second pass — refine what exists rather than adding more.
"""


IDEATION_SYSTEM_PROMPT = """You are a world-class creative director — the person who comes up with the big idea before anyone opens a design tool. You have encyclopedic knowledge of design history: Paul Rand, Saul Bass, Josef Müller-Brockmann, Paula Scher, Massimo Vignelli, Stefan Sagmeister, David Carson, Neville Brody, Herb Lubalin, Milton Glaser, and hundreds more.

Your job is to generate ONE brilliant creative concept for a design brief. You are NOT writing code. You are NOT specifying coordinates or hex codes. You are describing a VISUAL IDEA that would make a creative director at Pentagram say "that's clever."

WHAT MAKES A GREAT CONCEPT:
- A TWIST: Something unexpected. Not the first idea that comes to mind, but the third or fourth — the one that makes people look twice.
- DOUBLE MEANING: The best logos and posters have a dual read — you see one thing, then notice another layer of meaning. The FedEx arrow. The Spartan Golf Club golfer. The NBC peacock.
- NEGATIVE SPACE: What you DON'T draw is as important as what you do. Can the empty space between elements form a shape? Can a letter become an object?
- TENSION: Contrast creates interest. Big vs small. Thick vs thin. Geometric vs organic. Dense vs sparse. Dark vs light. Static vs dynamic.
- CONCEPTUAL CONNECTION: The visual form must connect to the meaning. Don't just make something that looks nice — make something that MEANS something related to the brand/subject.
- SIMPLICITY: The best ideas can be described in one sentence. If you need a paragraph to explain why it's clever, it's not clever enough.

YOUR OUTPUT FORMAT:
Write exactly 3 short paragraphs:

CONCEPT: One sentence describing the core visual idea and what makes it clever. What will the viewer see? What's the twist or double meaning?

VISUAL DESCRIPTION: Describe the key visual elements — the main shapes, how they relate to each other, the overall composition structure, the mood. Be specific about what the viewer's eye does: where does it land first, where does it travel? Do NOT use coordinates, pixel sizes, or hex codes. Describe it like you're explaining a painting to someone.

EXECUTION NOTES: What rendering approach will make this concept sing? Should it be stark and minimal or layered and textured? What kind of typography treatment? What's the color strategy — monochrome for drama, complementary for energy, analogous for harmony? What level of detail and craft will elevate this from a sketch to a finished piece?

Do NOT write code. Do NOT use technical specifications. Think like a creative, write like a creative."""


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


def compress_for_review(image_data):
    """Compress image if it exceeds Anthropic's 5MB limit."""
    from PIL import Image as PILImage
    if len(image_data) > 4_500_000:
        img = PILImage.open(io.BytesIO(image_data))
        new_w = int(img.width * 0.6)
        new_h = int(img.height * 0.6)
        img = img.resize((new_w, new_h), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    return image_data


@app.post("/generate")
async def generate_design(request: dict):
    """
    3-pass design generation:
    Pass 1 — Creative Director: generates the concept/idea
    Pass 2 — Renderer: translates concept into Python/Pillow/Cairo code
    Pass 3 — Art Director Review: looks at the render, critiques, and improves
    """
    prompt = request.get("prompt", "")
    work_type = request.get("work_type", "poster")

    available_fonts = get_font_list()
    font_list = "\n".join(f"    - /app/fonts/{f}" for f in available_fonts)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    rendering_prompt = get_rendering_prompt(font_list)

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
    # PASS 2 — RENDERER: Turn the concept into code
    # ============================================================
    render_message = client.messages.create(
        model="claude-opus-4-20250514",
        max_tokens=8192,
        system=rendering_prompt,
        messages=[
            {"role": "user", "content": f"A creative director has developed the following concept for this design brief. Your job is to execute this concept with exceptional craft and precision.\n\nORIGINAL BRIEF:\n{prompt}\n\nWORK TYPE: {work_type}\n\nCREATIVE CONCEPT:\n{creative_concept}\n\nNow write the Python code to render this concept. Execute the creative director's vision faithfully — do not simplify or water down their idea. Every element they described must be present and executed beautifully."}
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

        render_b64 = base64.b64encode(render_data).decode()
        review_b64 = base64.b64encode(compress_for_review(render_data)).decode()

        # ============================================================
        # PASS 3 — ART DIRECTOR REVIEW: Critique and improve
        # ============================================================
        review_prompt = f"""Look at the rendered image. You are a world-class creative director at Pentagram reviewing this piece.

The original creative concept was:
{creative_concept}

TECHNICAL CHECK (fix any issues):
- Text clipping or overflowing the canvas
- Elements overlapping unintentionally
- Poor spacing, margins, or breathing room
- Color balance and compositional balance

DESIGN QUALITY CHECK (this is the important part):
- Does the render FAITHFULLY execute the creative concept above? If the concept described a clever twist or double meaning, is it actually visible in the image? If not, that's the #1 priority to fix.
- Is this BORING? If a client saw this, would they be excited or underwhelmed? Be brutally honest.
- Does the mark have TENSION and CONTRAST? Thick vs thin, geometric vs organic, solid vs open? Or is everything the same visual weight?
- Is there CRAFT in the details? Are curves smooth and intentional? Are proportions based on a clear system?
- Would this win an award? Would Pentagram put this in their portfolio? If not, it's not good enough.

Your job is to make this piece live up to the creative concept. If the renderer simplified or watered down the idea, bring back the full vision. If technical issues are hiding the concept, fix them.

Write IMPROVED Python code. Output ONLY the Python code, nothing else."""

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
                            "media_type": "image/png",
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
            # If revision fails, return the first render
            return {
                "image": render_b64,
                "format": "png",
                "code_used": code,
                "concept": creative_concept,
                "note": "Review pass failed, returning initial render"
            }

        with open(result2, "rb") as f:
            final_data = base64.b64encode(f.read()).decode()

        return {
            "image": final_data,
            "format": "png",
            "code_used": revised_code,
            "concept": creative_concept
        }


@app.get("/health")
async def health():
    fonts = get_font_list()
    return {"status": "ok", "fonts_loaded": len(fonts)}
