import io
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image
from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "fake-key-for-tests-0123456789")

from main import app


def image_bytes(image_format):
    image = Image.new("RGB", (2, 2), "white")
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


@pytest.mark.parametrize(
    ("image_format", "filename", "claimed_mime", "expected_mime"),
    [
        ("JPEG", "sample.jpg", "image/jpeg", "image/jpeg"),
        ("WEBP", "sample.webp", "image/webp", "image/webp"),
        ("PNG", "sample.png", "image/png", "image/png"),
    ],
)
def test_supported_image_formats_reach_solver_with_detected_mime_type(
    image_format, filename, claimed_mime, expected_mime
):
    client = TestClient(app)
    responses = [
        '{"clean_problem":"Read the input and print the result."}',
        '{"chosen_approach":"Direct simulation"}',
        "print(1)",
        '{"verdict":"APPROVE","issues":[]}',
    ]
    completion = AsyncMock(side_effect=[
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=None,
        )
        for content in responses
    ])

    async def unavailable_judge(state):
        state["status"] = "judge_unavailable"
        state["judge_error"] = "mocked Judge0 outage"
        state["final_solution"] = state["generated_code"]
        return state

    with (
        patch("utils.ai_router.acompletion", completion),
        patch("orchestrator.run_judge", unavailable_judge),
        patch("orchestrator.store_episodic"),
    ):
        response = client.post(
            "/solve-image",
            files={"image": (filename, image_bytes(image_format), claimed_mime)},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "judge_unavailable"
    assert completion.await_count == 4
    provider_content = completion.await_args_list[0].kwargs["messages"][-1]["content"]
    assert provider_content[0]["image_url"]["url"].startswith(f"data:{expected_mime};base64,")


def test_fake_png_is_rejected_from_bytes():
    client = TestClient(app)
    response = client.post(
        "/solve-image",
        files={"image": ("renamed.png", b"plain text", "image/png")},
    )
    assert response.status_code == 415
