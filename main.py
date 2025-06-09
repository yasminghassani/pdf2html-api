from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import fitz  # PyMuPDF
import base64
import pdfplumber
from io import BytesIO
import re

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello from FastAPI on Render"}

@app.get("/health")
async def health():
    return {"status": "ok"}

def point_to_px(pt):
    return round(pt * 1.333, 2)

def guess_chapter_name(spans):
    if not spans:
        return "Untitled"
    sorted_spans = sorted(spans, key=lambda s: s["size"], reverse=True)
    for span in sorted_spans:
        text = span["text"].strip()
        if len(text) > 3 and re.search(r"(chapter|guide|section|intro|handbook)", text, re.IGNORECASE):
            return text
    return sorted_spans[0]["text"].strip()

def extract_page_data_with_plumber(page_index: int, pdf_bytes: bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    width, height = page.rect.width, page.rect.height

    text_spans = []
    text_blocks = []
    background_shapes = []
    image_blocks = []

    for block in page.get_text("dict")["blocks"]:
        if block["type"] == 0:
            for line in block["lines"]:
                for span in line["spans"]:
                    color = span.get("color", 0)
                    if isinstance(color, int):
                        r = (color >> 16) & 255
                        g = (color >> 8) & 255
                        b = color & 255
                    else:
                        r, g, b = 0, 0, 0

                    text_blocks.append({
                        "text": span["text"],
                        "x": span["bbox"][0],
                        "y": span["bbox"][1],
                        "width": span["bbox"][2] - span["bbox"][0],
                        "height": span["bbox"][3] - span["bbox"][1],
                        "font_size": span["size"],
                        "font": span.get("font", "unknown"),
                        "color": {"r": r, "g": g, "b": b}
                    })

                    text_spans.append({
                        "text": span["text"],
                        "size": span["size"]
                    })

        elif block["type"] == 4:
            bbox = block["bbox"]
            color = block.get("color", 0)
            if isinstance(color, int):
                r = (color >> 16) & 255
                g = (color >> 8) & 255
                b = color & 255
            else:
                r, g, b = 0, 0, 0

            background_shapes.append({
                "x": bbox[0],
                "y": bbox[1],
                "width": bbox[2] - bbox[0],
                "height": bbox[3] - bbox[1],
                "color": {"r": r, "g": g, "b": b}
            })

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        plumber_page = pdf.pages[page_index]
        for img in plumber_page.images:
            try:
                x0, top, x1, bottom = img["x0"], img["top"], img["x1"], img["bottom"]
                width_img = x1 - x0
                height_img = bottom - top

                if width_img <= 1 or height_img <= 1:
                    continue

                image_obj = plumber_page.to_image()
                cropped_image = image_obj.original.crop((x0, top, x1, bottom))

                buffered = BytesIO()
                cropped_image.save(buffered, format="PNG")
                img_b64 = f"data:image/png;base64,{base64.b64encode(buffered.getvalue()).decode()}"

                image_blocks.append({
                    "base64": img_b64,
                    "x": x0,
                    "y": bottom - height_img,
                    "width": width_img,
                    "height": height_img
                })

            except Exception:
                continue

    return {
        "width": width,
        "height": height,
        "text_blocks": text_blocks,
        "image_blocks": image_blocks,
        "background_shapes": background_shapes,
        "titles": guess_chapter_name(text_spans)
    }

def render_tailwind_html(page, page_number=1):
    width = point_to_px(page["width"])
    height = point_to_px(page["height"])
    
    html_parts = [
        f"<div class='relative bg-white dark:bg-gray-900 border shadow-md rounded-md overflow-hidden' style='width:{width}px; height:{height}px;'>"
    ]

    # ✅ Only add background vector to page 1
    if page_number == 1:
        html_parts.append(
            """
            <svg class="absolute" style="bottom: 0; right: 0; width: 50%; height: 50%; z-index: 0;" viewBox="0 0 100 100" preserveAspectRatio="none">
              <defs>
                <linearGradient id="blueGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#2196F3" />
                  <stop offset="100%" stop-color="#9C27B0" />
                </linearGradient>
              </defs>
              <path d="M0,100 Q50,0 100,100 Z" fill="url(#blueGradient)" />
            </svg>
            """
        )

    for block in page["text_blocks"]:
        x = point_to_px(block["x"])
        y = point_to_px(block["y"])
        font_size = point_to_px(block["font_size"])
        color = block["color"]
        r, g, b = color["r"], color["g"], color["b"]

        is_black = r <= 40 and g <= 40 and b <= 40
        is_white = r >= 225 and g >= 225 and b >= 225

        color_class = "text-black dark:text-white"
        if not (is_black or is_white):
            color_str = f"rgb({r},{g},{b})"
            color_class = ""
        else:
            color_str = ""

        gradient_style = ""
        if font_size > 53:
            gradient_style = (
                "bg-gradient-to-r from-blue-500 via-purple-500 to-pink-500 "
                "text-transparent bg-clip-text font-bold"
            )

        text = block["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        style = f"left:{x}px; top:{y}px; font-size:{font_size}px; font-family:{block['font']}; z-index:1;"
        if not color_class:
            style += f" color:{color_str};"

        html_parts.append(
            f"<div class='absolute whitespace-pre font-sans {color_class} {gradient_style}' style='{style}'>{text}</div>"
        )

    for image in page["image_blocks"]:
        x = point_to_px(image["x"])
        y = point_to_px(image["y"])
        w = point_to_px(image["width"])
        h = point_to_px(image["height"])
        html_parts.append(
            f"<img src='{image['base64']}' class='absolute' style='left:{x}px; top:{y}px; width:{w}px; height:{h}px; z-index:1;' />"
        )

    html_parts.append("</div>")
    return "\n".join(html_parts)

@app.post("/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    result = []
    seen_chapters = {}
    chapters = []

    for i, page in enumerate(doc):
        page_data = extract_page_data_with_plumber(i, pdf_bytes)
        page_data["page_number"] = i + 1
        title = page_data["titles"]
        page_number = page_data["page_number"]

        if title not in seen_chapters:
            seen_chapters[title] = page_number
            chapters.append({
                "title": title,
                "start_page": page_number
            })

        html = render_tailwind_html(page_data, page_number)

        result.append({
            "page_number": i + 1,
            "html": html
        })

    return JSONResponse(content={"pages": result, "total_pages": len(doc), "chapters": chapters})
