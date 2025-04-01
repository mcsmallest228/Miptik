import cv2
import numpy as np
from PIL import Image, ImageEnhance
from pdf2image import convert_from_bytes
from io import BytesIO


def enhance_handwriting(image, bg_color=(255, 255, 255), ink_color=(0, 0, 0),
                        thickness_level=3, remove_bg=True, contrast=3.0):
    img = np.array(image)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if len(img.shape) == 3 else img

    enhanced = cv2.convertScaleAbs(gray, alpha=contrast, beta=0)
    _, binary = cv2.threshold(enhanced, 220, 255, cv2.THRESH_BINARY_INV)

    kernel = np.ones((thickness_level, thickness_level), np.uint8)
    thickened = cv2.dilate(binary, kernel, iterations=1)
    smoothed = cv2.GaussianBlur(thickened, (3, 3), 0)
    _, smoothed = cv2.threshold(smoothed, 100, 255, cv2.THRESH_BINARY)

    h, w = smoothed.shape
    background = np.full((h, w, 3), bg_color, dtype=np.uint8) if remove_bg else cv2.cvtColor(255 - binary,
                                                                                             cv2.COLOR_GRAY2BGR)
    result = np.where(smoothed[..., None] == 255, ink_color, background)

    return Image.fromarray(result.astype('uint8'))


def process_pdf(pdf_bytes, preview=False):
    images = convert_from_bytes(pdf_bytes.getvalue(), dpi=300)[:5] if preview else convert_from_bytes(
        pdf_bytes.getvalue(), dpi=300)

    processed_images = []
    for img in images:
        processed = enhance_handwriting(img)
        processed_images.append(processed)

    output_bytes = BytesIO()
    if len(processed_images) > 1:
        processed_images[0].save(
            output_bytes, format='PDF',
            save_all=True, append_images=processed_images[1:],
            quality=100
        )
    else:
        processed_images[0].save(output_bytes, format='PDF', quality=100)

    output_bytes.seek(0)
    return output_bytes