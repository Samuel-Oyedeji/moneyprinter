"""Thumbnail design for documentary films.

The thumbnail is designed by an image model (via the documentary provider,
OpenRouter by default): it receives the film's strongest archival image plus
an art brief — cinematic grading, effects, bold integrated title treatment
with the key detail — and returns a finished 16:9 design. If generation
fails, a programmatic PIL composition (graded image, gradient, condensed
title, accent bar) keeps the pipeline moving; the Library tab allows
regenerating or uploading a custom file.
"""

import base64
import io
import os

from loguru import logger

from app.services.documentary import images as images_service
from app.services.documentary import llm_bridge, store
from app.utils import utils

DEFAULT_THUMBNAIL_MODEL = "google/gemini-3.1-flash-image"
THUMB_WIDTH = 1280
THUMB_HEIGHT = 720


def thumbnail_path(project_id: str) -> str:
    return os.path.join(utils.task_dir(project_id), "thumbnail.jpg")


def pick_source_image(project_id: str) -> str:
    """The highest-vision-scored image actually used in the film."""
    images = store.load_images(project_id) or {}
    best_path, best_score = "", -1.0
    for item in images.get("items", []):
        path = images_service.selected_image_path(item)
        if not path:
            continue
        selected = item.get("selected")
        score = 0.0
        if isinstance(selected, int):
            candidates = item.get("candidates", [])
            if 0 <= selected < len(candidates):
                score = float(candidates[selected].get("score", 0) or 0)
        if not best_path or score > best_score:
            best_path, best_score = path, score
    return best_path


def _texts(project: dict) -> tuple[str, str]:
    script = store.load_script(project["project_id"]) or {}
    intro = script.get("intro") or {}
    title = str(intro.get("title", "")).strip() or str(
        script.get("title", "") or project["topic"]
    )
    detail = str(intro.get("date_line", "")).strip()
    return title, detail


def _save_cover(image_bytes: bytes, output_path: str) -> str:
    """Normalize model output to a 1280x720 JPEG."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        scale = max(THUMB_WIDTH / image.width, THUMB_HEIGHT / image.height)
        image = image.resize(
            (round(image.width * scale), round(image.height * scale))
        )
        left = (image.width - THUMB_WIDTH) // 2
        top = (image.height - THUMB_HEIGHT) // 2
        image = image.crop((left, top, left + THUMB_WIDTH, top + THUMB_HEIGHT))
        image.save(output_path, "JPEG", quality=90)
    return output_path


def _extract_generated_image(response) -> bytes | None:
    """Pull the first generated image out of an OpenRouter chat response."""
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError):
        return None

    images = getattr(message, "images", None)
    if not images and getattr(message, "model_extra", None):
        images = message.model_extra.get("images")
    for image in images or []:
        url = ""
        if isinstance(image, dict):
            url = ((image.get("image_url") or {}).get("url", "")) or image.get(
                "url", ""
            )
        else:
            image_url = getattr(image, "image_url", None)
            url = getattr(image_url, "url", "") if image_url else ""
        if url.startswith("data:image"):
            return base64.b64decode(url.split(",", 1)[1])
    return None


def generate_designed_thumbnail(project: dict) -> str | None:
    """Ask the image model to design the thumbnail; None on any failure."""
    project_id = project["project_id"]
    source = pick_source_image(project_id)
    if not source:
        return None
    title, detail = _texts(project)

    setup = llm_bridge._openai_compatible_setup(
        "thumbnail_model", DEFAULT_THUMBNAIL_MODEL
    )
    if setup is None:
        logger.warning("thumbnail model unavailable (provider/key not set)")
        return None
    client, model = setup

    brief = f"""
Design a YouTube thumbnail (16:9, 1280x720) for a serious historical
documentary, using the attached archival photograph as the base image.

Requirements:
- Keep the photograph recognizable as the dominant visual; enhance it with
  cinematic color grading, strong contrast, a dark vignette and subtle film
  grain. Do not fabricate new people or events into the photo.
- Integrate bold, condensed, cinematic typography — NOT plain flat text:
  give the type presence with layering, subtle depth or backing shapes so
  it reads instantly at small sizes.
- Main title: "{title}"
- Smaller key detail line: "{detail}"
- Muted, moody palette with one warm accent. No watermarks, no logos, no
  channel name, no extra text beyond the title and detail line.
Return the finished thumbnail image.
""".strip()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": brief},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": llm_bridge._image_data_url(source)
                            },
                        },
                    ],
                }
            ],
            extra_body={
                "modalities": ["image", "text"],
                **llm_bridge._usage_extra_body(client),
            },
        )
        llm_bridge._record_usage("thumbnail", model, response)
        image_bytes = _extract_generated_image(response)
        if not image_bytes:
            logger.warning("thumbnail model returned no image")
            return None
        return _save_cover(image_bytes, thumbnail_path(project_id))
    except Exception as exc:
        logger.warning(f"thumbnail generation failed: {exc}")
        return None


def compose_fallback_thumbnail(project: dict) -> str | None:
    """Programmatic composition when the image model is unavailable."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont

    project_id = project["project_id"]
    source = pick_source_image(project_id)
    if not source:
        return None
    title, detail = _texts(project)

    with Image.open(source) as base:
        base = base.convert("RGB")
        scale = max(THUMB_WIDTH / base.width, THUMB_HEIGHT / base.height)
        base = base.resize((round(base.width * scale), round(base.height * scale)))
        left = (base.width - THUMB_WIDTH) // 2
        top = (base.height - THUMB_HEIGHT) // 2
        canvas = base.crop((left, top, left + THUMB_WIDTH, top + THUMB_HEIGHT))

    canvas = ImageEnhance.Contrast(canvas).enhance(1.15)
    canvas = ImageEnhance.Color(canvas).enhance(0.75)

    # Bottom gradient so the type always sits on a readable ground.
    gradient = Image.new("L", (1, THUMB_HEIGHT))
    for y in range(THUMB_HEIGHT):
        gradient.putpixel(
            (0, y), min(255, max(0, int((y / THUMB_HEIGHT) ** 2 * 460)))
        )
    shade = Image.new("RGB", canvas.size, (8, 8, 10))
    canvas = Image.composite(shade, canvas, gradient.resize(canvas.size))

    draw = ImageDraw.Draw(canvas)
    font_file = os.path.join(
        utils.root_dir(), "resource", "fonts", "BeVietnamPro-Bold.ttf"
    )

    def fitted_font(text: str, max_width: int, start_size: int):
        size = start_size
        while size > 24:
            font = ImageFont.truetype(font_file, size)
            if draw.textlength(text, font=font) <= max_width:
                return font
            size -= 4
        return ImageFont.truetype(font_file, 24)

    margin = 64
    title_text = title.upper()
    title_font = fitted_font(title_text, THUMB_WIDTH - 2 * margin, 110)
    title_y = THUMB_HEIGHT - 220
    # Accent bar above the title gives the flat text some structure.
    draw.rectangle(
        (margin, title_y - 26, margin + 120, title_y - 14), fill=(224, 122, 45)
    )
    draw.text(
        (margin + 3, title_y + 3), title_text, font=title_font, fill=(0, 0, 0)
    )
    draw.text((margin, title_y), title_text, font=title_font, fill=(245, 243, 238))
    if detail:
        detail_font = fitted_font(detail, THUMB_WIDTH - 2 * margin, 40)
        draw.text(
            (margin, title_y + title_font.size + 18),
            detail,
            font=detail_font,
            fill=(200, 198, 192),
        )

    output = thumbnail_path(project_id)
    canvas.save(output, "JPEG", quality=90)
    return output


def ensure_thumbnail(project: dict, regenerate: bool = False) -> str | None:
    """Return the project's thumbnail path, designing one if needed."""
    path = thumbnail_path(project["project_id"])
    if os.path.isfile(path) and not regenerate:
        return path
    result = generate_designed_thumbnail(project)
    if result:
        logger.success(f"designed thumbnail: {result}")
        return result
    result = compose_fallback_thumbnail(project)
    if result:
        logger.info(f"fallback thumbnail composed: {result}")
    return result
