"""Prepare positioned text labels without changing the screenshot's layout."""

from __future__ import annotations

from .screenshot import OcrPage, Screenshot


def overlay_payload(shot: Screenshot, page: OcrPage, translations: dict[int, str]) -> dict:
    import numpy as np

    image = np.asarray(shot.image())
    height, width = image.shape[:2]
    blocks = []
    for region in page.regions:
        x0, y0, x1, y1 = region.rect
        left, top = max(0, int(x0) - 1), max(0, int(y0) - 1)
        right, bottom = min(width, int(x1) + 2), min(height, int(y1) + 2)
        patch = image[top:bottom, left:right]
        if patch.size == 0 or right <= left or bottom <= top:
            continue
        edge = np.concatenate((patch[0], patch[-1], patch[:, 0], patch[:, -1]))
        rgb = np.median(edge, axis=0).astype(int)
        background = "rgb(" + ",".join(map(str, rgb)) + ")"
        luminance = sum(float(v) * weight for v, weight in zip(rgb, (0.2126, 0.7152, 0.0722)))
        blocks.append({"id": region.id, "text": translations[region.id], "original": region.text,
                       "left": left / width * 100, "top": top / height * 100,
                       "width": (right - left) / width * 100, "height": (bottom - top) / height * 100,
                       "fontSize": max(10, (bottom - top) * 0.78),
                       "background": background, "color": "#171714" if luminance > 140 else "#f7f7f2"})
    return {"image": shot.data_url, "width": width, "height": height, "blocks": blocks}
