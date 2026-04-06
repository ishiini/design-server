from fastapi import FastAPI
from fastapi.responses import Response
import anthropic
import subprocess
import tempfile
import os
import re
import base64

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


def get_system_prompt(font_list):
    """Return the system prompt for the design generator."""
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


@app.post("/generate")
async def generate_design(request: dict):
    """
    Accepts a JSON body with:
    - prompt: the design generation prompt from n8n
    - work_type: logo, poster, etc.
    """
    prompt = request.get("prompt", "")
    work_type = request.get("work_type", "poster")

    available_fonts = get_font_list()
    font_list = "\n".join(f"    - /app/fonts/{f}" for f in available_fonts)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = get_system_prompt(font_list)

    # === PASS 1: Generate initial design ===
    message = client.messages.create(
        model="claude-opus-4-20250514",
        max_tokens=8192,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"Create this design:\n\n{prompt}"}
        ]
    )

    code = extract_code(message.content[0].text)

    with tempfile.TemporaryDirectory() as tmpdir:
        success, result = execute_code(code, tmpdir)

        if not success:
            return {
                "error": "Code execution failed",
                "stderr": result,
                "code": code
            }

        # Read the first-pass image
        with open(result, "rb") as f:
            first_pass_data = f.read()
        first_pass_b64 = base64.b64encode(first_pass_data).decode()

        # === PASS 2: Self-review with the rendered image ===
        review_prompt = """Look at the image you just generated. You are now the art director reviewing this piece.

CRITIQUE the design honestly. Check for:
- Text clipping or overflowing the canvas
- Elements overlapping unintentionally
- Visual clutter or density that hurts readability
- Poor spacing, margins, or breathing room
- Color balance — does it match the intended ratio?
- Compositional balance — does the eye flow naturally?
- Typography hierarchy — is it clear what to read first, second, third?
- Does it feel like a professional, finished piece or a rough draft?

Now write IMPROVED Python code that fixes every issue you identified.
Keep what works, fix what doesn't. The goal is museum-quality output.
Output ONLY the Python code, nothing else."""

        review_message = client.messages.create(
            model="claude-opus-4-20250514",
            max_tokens=8192,
            system=system_prompt,
            messages=[
                {"role": "user", "content": f"Create this design:\n\n{prompt}"},
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
                            "data": first_pass_b64
                        }
                    }
                ]}
            ]
        )

        revised_code = extract_code(review_message.content[0].text)

        # Execute the revised code
        success2, result2 = execute_code(revised_code, tmpdir)

        if not success2:
            # If the revision fails, return the first pass instead
            return {
                "image": first_pass_b64,
                "format": "png",
                "code_used": code,
                "note": "Review pass code failed, returning first pass"
            }

        with open(result2, "rb") as f:
            final_data = base64.b64encode(f.read()).decode()

        return {
            "image": final_data,
            "format": "png",
            "code_used": revised_code
        }


@app.get("/health")
async def health():
    fonts = get_font_list()
    return {"status": "ok", "fonts_loaded": len(fonts)}
