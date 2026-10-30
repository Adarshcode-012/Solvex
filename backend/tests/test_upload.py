import io
import os
from unittest.mock import AsyncMock, patch

from PIL import Image
from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")

from main import app


def jpeg_bytes():
    image = Image.new("RGB", (2, 2), "white")
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def test_jpeg_uses_detected_provider_mime_type():
    client = TestClient(app)
    with patch("main.solve_problem", new_callable=AsyncMock) as solve:
        solve.return_value = {"status": "unverified"}
        response = client.post(
            "/solve-image",
            files={"image": ("renamed.png", jpeg_bytes(), "image/png")},
        )

    assert response.status_code == 200
    assert solve.await_args.kwargs["image_mime_type"] == "image/jpeg"


def test_fake_png_is_rejected_from_bytes():
    client = TestClient(app)
    response = client.post(
        "/solve-image",
        files={"image": ("renamed.png", b"plain text", "image/png")},
    )
    assert response.status_code == 415