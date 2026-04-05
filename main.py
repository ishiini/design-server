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

    system_prompt = f"""You are a world-class designer and Python developer creating museum-quality visual art.

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

TECHNICAL RULES:
- Output ONLY valid Python code, no explanations, no markdown
- Save the final image to the path stored in the OUTPUT_PATH environment variable
- Use PIL (from PIL import Image, ImageDraw, ImageFont, ImageFilter)
- Do NOT import cairo, pycairo, or any library besides PIL and standard library
- Default canvas: 3840x2160 (4K) for posters, 2160x2160 for social, 2048x2048 for logos, 3508x4961 for print (A3 at 300dpi)
- ALWAYS use these large sizes. Never go smaller. High resolution is non-negotiable.
- Always wrap code in try/except and print errors
- Use high-resolution rendering (no pixelation on text or shapes)

AVAILABLE FONTS (use full paths):
{font_list}

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

CRAFTSMANSHIP CHECK:
Before finalizing code, verify:
1. Does every element serve a purpose?
2. Is spacing consistent and intentional?
3. Are colors harmonious and limited?
4. Does typography create clear hierarchy?
5. Would this look impressive printed at large scale?
6. Take a second pass — refine what exists rather than adding more.
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"Create this design:\n\n{prompt}"}
        ]
    )

    # Extract the Python code from Claude's response
    response_text = message.content[0].text

    # Try to find code between ```python ``` blocks
    code_match = re.search(r'```python\n(.*?)```', response_text, re.DOTALL)
    if code_match:
        code = code_match.group(1)
    else:
        code = response_text

    # Execute the code in a temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
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
            return {
                "error": "Code execution failed",
                "stderr": result.stderr,
                "code": code
            }

        if not os.path.exists(output_path):
            return {
                "error": "No image was generated",
                "stdout": result.stdout,
                "stderr": result.stderr
            }

        with open(output_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        return {
            "image": image_data,
            "format": "png",
            "code_used": code
        }


@app.get("/health")
async def health():
    fonts = get_font_list()
    return {"status": "ok", "fonts_loaded": len(fonts)}
