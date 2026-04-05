from fastapi import FastAPI
from fastapi.responses import Response
import anthropic
import subprocess
import tempfile
import os
import re
import base64

app = FastAPI()

@app.post("/generate")
async def generate_design(request: dict):
    """
    Accepts a JSON body with:
    - prompt: the design generation prompt from n8n
    - work_type: logo, poster, etc.
    """
    prompt = request.get("prompt", "")
    work_type = request.get("work_type", "poster")

    # Step 1: Ask Claude to write Python rendering code
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    system_prompt = """You are an expert designer and Python developer.
    Given a design brief, write Python code using Pillow (PIL) and/or
    Cairo (pycairo) to render the design as an image.

    Rules:
    - Output ONLY valid Python code, no explanations
    - Save the final image to the path stored in the OUTPUT_PATH environment variable
    - Use PIL (from PIL import Image, ImageDraw, ImageFont, ImageFilter)
    - For vector work, you may also use cairo
    - Create production-quality designs, not mockups
    - Use proper typography, spacing, and composition
    - Default canvas size: 1080x1080 for social, 1920x1080 for posters,
      1024x1024 for logos unless specified otherwise
    - Be creative with shapes, gradients, textures, and layering
    - Always wrap code in try/except and print errors
    """

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"Create this design:\n\n{prompt}"}
        ]
    )

    # Step 2: Extract the Python code from Claude's response
    response_text = message.content[0].text

    # Try to find code between ```python ``` blocks
    code_match = re.search(r'```python\n(.*?)```', response_text, re.DOTALL)
    if code_match:
        code = code_match.group(1)
    else:
        # If no code blocks, assume the whole response is code
        code = response_text

    # Step 3: Execute the code in a temp directory
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
            timeout=30,
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

        # Step 4: Return the image as base64
        with open(output_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        return {
            "image": image_data,
            "format": "png",
            "code_used": code
        }


@app.get("/health")
async def health():
    return {"status": "ok"}
