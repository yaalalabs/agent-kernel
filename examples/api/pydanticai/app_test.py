"""
REST API tests for the Pydantic AI example, mirroring examples/api/openai/app_test.py.

The image/PDF payloads are read from the bundled test_image.jpeg / test_pdf.pdf files rather than
inlined as base64. The expected answers for the LLM- and vision-driven turns are seeded from the
OpenAI example (same model family, same attachments) and compared semantically via
`agentkernel.test.Test`; recalibrate them against a real run if the model's phrasing drifts.
Requires OPENAI_API_KEY (agent model + multimodal vision analysis).
"""

import asyncio
import base64
import subprocess
import sys
import uuid

import httpx
import pytest
import pytest_asyncio
from agentkernel.test import Test

pytestmark = pytest.mark.asyncio(loop_scope="session")  # uses a single session for all tests


def _b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


class APITestClient:
    def __init__(self, url):
        self.url = url
        self.session_id = str(uuid.uuid4())

    async def send(self, prompt, endpoint: str = "/api/v1/chat", additional_context=None, body=None):
        payload = (
            {
                "prompt": prompt,
                "session_id": self.session_id,
                "agent": "support",
                "additional_context": additional_context,
            }
            if body is None
            else body
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.url}{endpoint}", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def http_client():
    proc = subprocess.Popen(
        ["python3", "app.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    await asyncio.sleep(5)
    try:
        yield APITestClient(f"http://localhost:8000")
    finally:
        proc.terminate()
        proc.wait()


@pytest.mark.asyncio
async def test_support_agent(http_client):
    print("test_support_agent")
    response = await http_client.send("I am Andy Dufresne. I did some deposits.")
    Test.compare(
        response,
        ["Hello Andy! I see you made a deposit of $250 over the counter. How satisfied were you with that deposit?"],
        threshold=0.1,
    )

    response = await http_client.send("I was extremely happy")
    Test.compare(
        response, ["That's great to hear! What specifically made the experience enjoyable for you?"], threshold=0.1
    )

    response = await http_client.send(prompt="", endpoint="/custom/deposit", body={"amount": 200})
    Test.compare(response, ["Deposited $200 over the counter"])

    # Test additional_context parameter passed through prehook for RAG
    response = await http_client.send(
        "In which movie my bank agent's name appeared in? Just give me the name of the movie",
        additional_context={"bank_agent": "Ellis Boyd Red Redding"},
    )
    Test.compare(response, ["the movie 'The Shawshank Redemption'."], threshold=0.2)


@pytest.mark.asyncio
async def test_image_support(http_client):
    print("test_image_support")
    body = {
        "session_id": http_client.session_id,
        "prompt": "can you describe this image?",
        "images": [
            {
                "name": "scenary",
                "mime_type": "image/jpeg",
                "image_data": _b64("test_image.jpeg"),
            }
        ],
    }
    response = await http_client.send("", body=body)
    Test.compare(
        response,
        [
            "This image shows a group of illustrated people in grayscale. They are standing together and differ in hairstyle and facial features. It's a stylized representation without distinct identities.",
            "The image is a grayscale illustration of a group of diverse, stylized people. The individuals have different hairstyles and clothing, and they are positioned in a way that creates a sense of depth and variety. It appears to represent a community or gathering of people.",
            "I'm unable to describe or analyze images of people. If there's anything else you'd like to discuss or other types of images you need help with, feel free to let me know!",
        ],
    )


@pytest.mark.asyncio
async def test_pdf_support(http_client):
    print("test_pdf_support")
    body = {
        "session_id": "james",
        "prompt": "what is the new deadline based on this file",
        "files": [
            {
                "name": "news",
                "mime_type": "application/pdf",
                "file_data": _b64("test_pdf.pdf"),
            }
        ],
    }
    response = await http_client.send("", body=body)
    Test.compare(
        response,
        [
            "The new deadline is 12 December 2025.",
            "The new deadline based on the file is 12 December 2025.",
            "The new deadline for submitting Grade 06 applications following the re-survey of the Grade 05 Scholarship Examination results is 12 December 2025.",
        ],
    )


@pytest.mark.asyncio
async def test_image_multipart(http_client):
    print("test_image_multipart")

    # Open and read the test image file
    with open("test_image.jpeg", "rb") as f:
        image_content = f.read()

    # Create multipart form data
    files = {"images": ("test_image.jpeg", image_content, "image/jpeg")}
    data = {"prompt": "can you describe this image?", "session_id": http_client.session_id, "agent": "support"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{http_client.url}/api/v1/chat-multipart", data=data, files=files)
        resp.raise_for_status()
        result = resp.json()
        response = result.get("result", "")

    Test.compare(
        response,
        [
            "This image shows a group of illustrated people in grayscale. They are standing together and differ in hairstyle and facial features. It's a stylized representation without distinct identities.",
            "The image is a grayscale illustration of a group of diverse, stylized people. The individuals have different hairstyles and clothing, and they are positioned in a way that creates a sense of depth and variety. It appears to represent a community or gathering of people.",
            "I'm unable to describe or analyze images of people. If there's anything else you'd like to discuss or other types of images you need help with, feel free to let me know!",
        ],
    )


@pytest.mark.asyncio
async def test_pdf_multipart(http_client):
    print("test_pdf_multipart")

    # Open and read the test PDF file
    with open("test_pdf.pdf", "rb") as f:
        pdf_content = f.read()

    # Create multipart form data
    files = {"files": ("test_pdf.pdf", pdf_content, "application/pdf")}
    data = {"prompt": "what is the new deadline based on this file", "session_id": "james", "agent": "support"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{http_client.url}/api/v1/chat-multipart", data=data, files=files)
        resp.raise_for_status()
        result = resp.json()
        response = result.get("result", "")

    Test.compare(
        response,
        [
            "The new deadline for submitting Grade 06 applications following the re-survey of the Grade 05 Scholarship Examination results is 12 December 2025."
        ],
    )
