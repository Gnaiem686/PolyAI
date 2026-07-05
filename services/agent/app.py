import base64
import io
import json
import logging
import os
from contextvars import ContextVar
from typing import Optional
from langchain_core.rate_limiters import InMemoryRateLimiter
import uuid
import boto3
import ast
# Redeploy check: harmless comment for CI/CD verification
from PIL import Image
from prometheus_fastapi_instrumentator import Instrumentator
from dotenv import load_dotenv
import time
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("langchain").setLevel(logging.DEBUG)
logging.getLogger("langchain_core").setLevel(logging.DEBUG)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")

s3_client = boto3.client("s3", region_name=AWS_REGION)

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel

YOLO_SERVICE_URL = os.environ.get("YOLO_SERVICE_URL", "http://localhost:8080")
IMG_PROC_MCP_URL = os.getenv("IMG_PROC_MCP_URL", "http://localhost:8100/mcp")
MODEL = os.environ.get("MODEL")

# Text-only models
ALLOWED_MODELS = {
    "openai:gpt-5.4-mini",
    "anthropic:claude-haiku-4-5",
    "google_genai:gemini-2.5-flash",

    "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
    "bedrock/amazon.nova-micro-v1:0",
    "bedrock/amazon.nova-lite-v1:0",
    "bedrock/openai.gpt-oss-20b-1:0",
    "bedrock/meta.llama3-1-8b-instruct-v1:0",
    "bedrock/mistral.mistral-7b-instruct-v0:2",
}

if MODEL not in ALLOWED_MODELS:
    allowed_list = "\n  ".join(sorted(ALLOWED_MODELS))
    raise SystemExit(
        f"\n[ERROR] MODEL='{MODEL}' is not allowed.\n"
        f"Set MODEL in your .env to one of the supported text-only models:\n  {allowed_list}\n"
    )

SYSTEM_PROMPT = (
    "You are an AI vision assistant. You help users understand, analyze, and edit images. "
    "Use the available tools whenever the user asks to detect objects or modify an image. "
    "Never invent, rewrite, copy, or mention image URLs. "
    "Never copy old assistant messages as the answer. "
    "If the user asks for a new image edit, call the correct image tool."
    "When editing a detected object, preserve the user's position words exactly. "
    "If the user says leftmost, call the tool with position='leftmost'. "
    "If the user says rightmost, call the tool with position='rightmost'. "
    "If the user says second from right, call the tool with position='second from right'. "
    "If the user says second from left, call the tool with position='second from left'. "
    "Do not replace leftmost/rightmost with first. "
    "Detected-object edits are only supported for blur, crop, and add noise. "
    "If the user asks to rotate, resize, or flip only a detected object, explain that this is not supported instead of using the whole-image tool. "
)

_current_image_b64: ContextVar[Optional[str]] = ContextVar("current_image_b64", default=None)

def upload_image_to_s3(image_b64: str) -> str:
    if not AWS_S3_BUCKET:
        raise RuntimeError("AWS_S3_BUCKET environment variable is not set")

    image_bytes = base64.b64decode(image_b64)

    chat_id = str(uuid.uuid4())
    prediction_id = str(uuid.uuid4())
    image_s3_key = f"{chat_id}/{prediction_id}/original/image.jpg"

    s3_client.put_object(
        Bucket=AWS_S3_BUCKET,
        Key=image_s3_key,
        Body=image_bytes,
        ContentType="image/jpeg",
    )

    return image_s3_key

def download_image_from_s3(s3_key: str) -> Image.Image:
    if not AWS_S3_BUCKET:
        raise RuntimeError("AWS_S3_BUCKET environment variable is not set")

    response = s3_client.get_object(
        Bucket=AWS_S3_BUCKET,
        Key=s3_key,
    )

    image_bytes = response["Body"].read()
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def upload_pil_image_to_s3(img: Image.Image, prefix: str = "agent-results") -> str:
    if not AWS_S3_BUCKET:
        raise RuntimeError("AWS_S3_BUCKET environment variable is not set")

    output_s3_key = f"{prefix}/{uuid.uuid4()}.png"

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    s3_client.put_object(
        Bucket=AWS_S3_BUCKET,
        Key=output_s3_key,
        Body=buffer.getvalue(),
        ContentType="image/png",
    )

    return output_s3_key


def parse_yolo_box(box_value) -> tuple[int, int, int, int]:
    if isinstance(box_value, str):
        box = ast.literal_eval(box_value)
    else:
        box = box_value

    if len(box) != 4:
        raise ValueError("YOLO box must contain four values")

    left, top, right, bottom = box

    return (
        max(0, int(left)),
        max(0, int(top)),
        max(0, int(right)),
        max(0, int(bottom)),
    )


def select_detection(detection_objects: list[dict], label: str, position: str = "first") -> dict:
    target_label = label.lower().strip()
    normalized_position = position.lower().strip()

    matches = [
        obj for obj in detection_objects
        if obj.get("label", "").lower().strip() == target_label
    ]

    if not matches:
        raise ValueError(f"No detected object with label '{label}' was found")

    def center_x(obj: dict) -> float:
        left, _, right, _ = parse_yolo_box(obj["box"])
        return (left + right) / 2

    if normalized_position in ("first", "any"):
        return matches[0]

    if normalized_position in ("left", "leftmost"):
        return sorted(matches, key=center_x)[0]

    if normalized_position in ("right", "rightmost"):
        return sorted(matches, key=center_x, reverse=True)[0]

    if normalized_position in ("second from right", "second right"):
        sorted_matches = sorted(matches, key=center_x, reverse=True)
        if len(sorted_matches) < 2:
            raise ValueError(f"Only found {len(sorted_matches)} object(s) with label '{label}'")
        return sorted_matches[1]

    if normalized_position in ("second from left", "second left"):
        sorted_matches = sorted(matches, key=center_x)
        if len(sorted_matches) < 2:
            raise ValueError(f"Only found {len(sorted_matches)} object(s) with label '{label}'")
        return sorted_matches[1]

    raise ValueError(
        "Unsupported position. Use first, leftmost, rightmost, second from right, or second from left."
    )


def paste_processed_region(
    original_img: Image.Image,
    processed_region: Image.Image,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> Image.Image:
    box_width = right - left
    box_height = bottom - top

    processed_region = processed_region.convert("RGB")
    processed_region = processed_region.resize((box_width, box_height))

    result_img = original_img.copy()
    result_img.paste(processed_region, (left, top))

    return result_img


def clamp_box_to_image(left: int, top: int, right: int, bottom: int, img: Image.Image) -> tuple[int, int, int, int]:
    width, height = img.size
    left = max(0, min(left, width - 1))
    right = max(left + 1, min(right, width))
    top = max(0, min(top, height - 1))
    bottom = max(top + 1, min(bottom, height))
    return left, top, right, bottom


def get_selected_object_crop(
    label: str,
    position: str = "first",
) -> tuple[str, Image.Image, Image.Image, tuple[int, int, int, int], dict]:
    image_b64 = _current_image_b64.get()
    if not image_b64:
        raise RuntimeError("No image was provided by the user.")

    original_s3_key = upload_image_to_s3(image_b64)

    with httpx.Client(timeout=60.0) as client:
        predict_response = client.post(
            f"{YOLO_SERVICE_URL}/predict",
            json={"image_s3_key": original_s3_key},
        )
        predict_response.raise_for_status()
        predict_result = predict_response.json()

        prediction_uid = predict_result["prediction_uid"]

        details_response = client.get(f"{YOLO_SERVICE_URL}/prediction/{prediction_uid}")
        details_response.raise_for_status()
        prediction_details = details_response.json()

    detection_objects = prediction_details.get("detection_objects", [])
    selected_detection = select_detection(detection_objects, label=label, position=position)

    left, top, right, bottom = parse_yolo_box(selected_detection["box"])

    original_img = download_image_from_s3(original_s3_key)
    left, top, right, bottom = clamp_box_to_image(left, top, right, bottom, original_img)

    object_crop = original_img.crop((left, top, right, bottom))

    return original_s3_key, original_img, object_crop, (left, top, right, bottom), selected_detection


def create_presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    if not AWS_S3_BUCKET:
        raise RuntimeError("AWS_S3_BUCKET environment variable is not set")

    return s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": AWS_S3_BUCKET,
            "Key": s3_key,
        },
        ExpiresIn=expires_in,
    )


def build_image_response(message: str, image_url: str) -> str:
    return f"{message}\n\n<img src=\"{image_url}\" alt=\"Processed image\">"

def _extract_mcp_json_response(response_text: str) -> dict:
    """
    MCP Streamable HTTP may return Server-Sent Events lines like:
    event: message
    data: {...}

    This extracts the JSON object from the data line.
    """
    for line in response_text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: "):])

    # Fallback if server returns plain JSON
    return json.loads(response_text)


def _mcp_post(payload: dict, session_id: Optional[str] = None) -> tuple[dict, Optional[str]]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    if session_id:
        headers["mcp-session-id"] = session_id

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            IMG_PROC_MCP_URL,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

    returned_session_id = response.headers.get("mcp-session-id")

    # notifications/initialized usually returns an empty body.
    if not response.text.strip():
        return {}, returned_session_id

    parsed = _extract_mcp_json_response(response.text)
    return parsed, returned_session_id


def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """
    Calls an image-processing MCP tool using the real MCP JSON-RPC protocol:
    initialize -> notifications/initialized -> tools/call.
    """
    initialize_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {
                "name": "polyai-agent",
                "version": "1.0",
            },
        },
    }

    _, session_id = _mcp_post(initialize_payload)

    if not session_id:
        raise RuntimeError("MCP server did not return mcp-session-id")

    initialized_payload = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }

    _mcp_post(initialized_payload, session_id=session_id)

    call_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }

    mcp_response, _ = _mcp_post(call_payload, session_id=session_id)

    if "error" in mcp_response:
        raise RuntimeError(f"MCP tool call failed: {mcp_response['error']}")

    result = mcp_response.get("result", {})

    if result.get("isError"):
        raise RuntimeError(f"MCP tool returned error: {result}")

    structured = result.get("structuredContent")
    if structured is not None:
        return _unwrap_mcp_tool_result(structured)

    content = result.get("content")
    if content is not None:
        return _unwrap_mcp_tool_result(content)

    return _unwrap_mcp_tool_result(result)

def _unwrap_mcp_tool_result(value) -> dict:
    """
    Convert MCP tool output into the actual dict returned by our image tools.

    Handles shapes like:
    - {"output_s3_key": "..."}
    - {"result": "{\"output_s3_key\": \"...\"}"}
    - {"text": "{\"output_s3_key\": \"...\"}"}
    - [{"type": "text", "text": "..."}]
    """
    if isinstance(value, dict):
        if "output_s3_key" in value:
            return value

        if "result" in value:
            return _unwrap_mcp_tool_result(value["result"])

        if "text" in value:
            return _unwrap_mcp_tool_result(value["text"])

        return value

    if isinstance(value, list):
        if not value:
            return {}
        return _unwrap_mcp_tool_result(value[0])

    if isinstance(value, str):
        text = value.strip()
        try:
            return _unwrap_mcp_tool_result(json.loads(text))
        except json.JSONDecodeError:
            return {"result": text}

    return {}

@tool
def detect_objects() -> str:
    """Detect and identify objects in the image provided by the user using YOLO object detection."""
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    image_s3_key = upload_image_to_s3(image_b64)

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{YOLO_SERVICE_URL}/predict",
            json={"image_s3_key": image_s3_key},
        )
        response.raise_for_status()

    return json.dumps(response.json())

@tool
def blur_image(radius: float = 2.0) -> str:
    """Blur the image provided by the user. Returns a temporary URL to the processed image."""
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    input_s3_key = upload_image_to_s3(image_b64)

    result = call_mcp_tool(
        "blur",
        {
            "input_s3_key": input_s3_key,
            "radius": radius,
        },
    )
    output_s3_key = result["output_s3_key"]
    image_url = create_presigned_url(output_s3_key)

    return json.dumps({
        "message": f"I blurred the image with radius {radius}.",
        "image_url": image_url,
    })

@tool
def rotate_image(angle: float = 90.0, expand: bool = True) -> str:
    """
    Rotate the entire image provided by the user.

    Args:
        angle: Rotation angle in degrees.
        expand: If True, expand the output image size to fit the rotated image.

    Returns an HTML image tag with the rotated image.
    """
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    input_s3_key = upload_image_to_s3(image_b64)

    result = call_mcp_tool(
        "rotate",
        {
            "input_s3_key": input_s3_key,
            "angle": angle,
            "expand": expand,
        },
    )
    output_s3_key = result["output_s3_key"]
    image_url = create_presigned_url(output_s3_key)

    return json.dumps({
        "message": f"I rotated the image by {angle} degrees.",
        "image_url": image_url,
    })

@tool
def flip_image(direction: str = "horizontal") -> str:
    """
    Flip the entire image provided by the user.

    Args:
        direction: Flip direction. Use "horizontal" or "vertical".

    Returns a temporary URL to the flipped image.
    """
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    direction = direction.lower().strip()
    if direction not in ("horizontal", "vertical"):
        return json.dumps({"error": "direction must be 'horizontal' or 'vertical'"})

    input_s3_key = upload_image_to_s3(image_b64)

    result = call_mcp_tool(
        "flip",
        {
            "input_s3_key": input_s3_key,
            "direction": direction,
        },
    )
    output_s3_key = result["output_s3_key"]
    image_url = create_presigned_url(output_s3_key)

    return json.dumps({
        "message": f"I flipped the image {direction}ly.",
        "image_url": image_url,
    })

@tool
def resize_image(width: int, height: int) -> str:
    """
    Resize the entire image provided by the user.

    Args:
        width: New image width in pixels.
        height: New image height in pixels.

    Returns a temporary URL to the resized image.
    """
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    if width <= 0 or height <= 0:
        return json.dumps({"error": "width and height must be positive integers"})

    input_s3_key = upload_image_to_s3(image_b64)

    result = call_mcp_tool(
        "resize",
        {
            "input_s3_key": input_s3_key,
            "width": width,
            "height": height,
        },
    )
    output_s3_key = result["output_s3_key"]
    image_url = create_presigned_url(output_s3_key)

    return json.dumps({
        "message": f"I resized the image to {width}x{height}.",
        "image_url": image_url,
    })

@tool
def crop_image(left: int, top: int, right: int, bottom: int) -> str:
    """
    Crop the entire image using pixel coordinates.

    Args:
        left: Left x-coordinate of the crop box.
        top: Top y-coordinate of the crop box.
        right: Right x-coordinate of the crop box.
        bottom: Bottom y-coordinate of the crop box.

    Returns a temporary URL to the cropped image.
    """
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    if right <= left or bottom <= top:
        return json.dumps({
            "error": "Invalid crop box. right must be greater than left, and bottom must be greater than top."
        })

    input_s3_key = upload_image_to_s3(image_b64)

    result = call_mcp_tool(
        "crop",
        {
            "input_s3_key": input_s3_key,
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
        },
    )
    output_s3_key = result["output_s3_key"]
    image_url = create_presigned_url(output_s3_key)

    return json.dumps({
        "message": f"I cropped the image using box ({left}, {top}, {right}, {bottom}).",
        "image_url": image_url,
    })

@tool
def add_noise_image(amount: float = 0.05) -> str:
    """
    Add salt-and-pepper noise to the entire image provided by the user.

    Args:
        amount: Fraction of pixels to modify. Example: 0.05.

    Returns a temporary URL to the noisy image.
    """
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    if amount <= 0 or amount > 1:
        return json.dumps({"error": "amount must be greater than 0 and less than or equal to 1"})

    input_s3_key = upload_image_to_s3(image_b64)

    result = call_mcp_tool(
        "add_noise",
        {
            "input_s3_key": input_s3_key,
            "amount": amount,
        },
    )
    output_s3_key = result["output_s3_key"]
    image_url = create_presigned_url(output_s3_key)

    return json.dumps({
        "message": f"I added salt-and-pepper noise to the image with amount {amount}.",
        "image_url": image_url,
    })

@tool
def blur_detected_object(label: str, position: str = "first", radius: float = 2.0) -> str:
    """
    Blur a detected object in the image provided by the user.

    Args:
        label: Object label to edit, for example "dog", "car", "person".
        position: Which matching object to edit.
        Use "leftmost" when the user says leftmost, far left, first from left, or on the left.
        Use "rightmost" when the user says rightmost, far right, first from right, or on the right.
        Use "second from right" when the user says second from the right.
        Use "second from left" when the user says second from the left.
        Use "first" only when the user does not specify a position.
        radius: Gaussian blur radius.

    Returns an HTML image tag with the final full image, where only the selected object is blurred.
    """
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    _, original_img, object_crop, (left, top, right, bottom), _ = get_selected_object_crop(label=label, position=position)
    crop_s3_key = upload_pil_image_to_s3(object_crop, prefix="agent-crops")

    blur_result = call_mcp_tool(
        "blur",
        {
            "input_s3_key": crop_s3_key,
            "radius": radius,
        },
    )

    processed_crop_s3_key = blur_result["output_s3_key"]
    processed_crop = download_image_from_s3(processed_crop_s3_key)

    final_img = paste_processed_region(
        original_img=original_img,
        processed_region=processed_crop,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
    )

    final_s3_key = upload_pil_image_to_s3(final_img, prefix="agent-results/blur-detected-object")
    final_image_url = create_presigned_url(final_s3_key)

    return json.dumps({
        "message": f"I blurred the {position} {label} in the image.",
        "image_url": final_image_url,
    })

@tool
def crop_detected_object(label: str, position: str = "first") -> str:
    """
    Crop a detected object from the image provided by the user.

    Args:
        label: Object label to crop, for example "dog", "car", "person".
        position: Which matching object to edit.
        Use "leftmost" when the user says leftmost, far left, first from left, or on the left.
        Use "rightmost" when the user says rightmost, far right, first from right, or on the right.
        Use "second from right" when the user says second from the right.
        Use "second from left" when the user says second from the left.
        Use "first" only when the user does not specify a position.

    Returns a temporary URL to the cropped detected object.
    """
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    _, _, object_crop, _, _ = get_selected_object_crop(label=label, position=position)

    crop_s3_key = upload_pil_image_to_s3(
        object_crop,
        prefix="agent-results/crop-detected-object",
    )
    crop_image_url = create_presigned_url(crop_s3_key)

    return json.dumps({
        "message": f"I cropped the {position} {label} from the image.",
        "image_url": crop_image_url,
    })

@tool
def add_noise_to_detected_object(label: str, position: str = "first", amount: float = 0.05) -> str:
    """
    Add salt-and-pepper noise to a detected object in the image provided by the user.

    Args:
        label: Object label to edit, for example "dog", "car", "person".
        position: Which matching object to edit.
        Use "leftmost" when the user says leftmost, far left, first from left, or on the left.
        Use "rightmost" when the user says rightmost, far right, first from right, or on the right.
        Use "second from right" when the user says second from the right.
        Use "second from left" when the user says second from the left.
        Use "first" only when the user does not specify a position.
        amount: Fraction of pixels to modify with salt-and-pepper noise. Example: 0.05.

    Returns an HTML image tag with the final full image, where only the selected object has noise.
    """
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    _, original_img, object_crop, (left, top, right, bottom), _ = get_selected_object_crop(label=label, position=position)
    crop_s3_key = upload_pil_image_to_s3(object_crop, prefix="agent-crops")

    noise_result = call_mcp_tool(
        "add_noise",
        {
            "input_s3_key": crop_s3_key,
            "amount": amount,
        },
    )

    processed_crop_s3_key = noise_result["output_s3_key"]
    processed_crop = download_image_from_s3(processed_crop_s3_key)

    final_img = paste_processed_region(
        original_img=original_img,
        processed_region=processed_crop,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
    )

    final_s3_key = upload_pil_image_to_s3(final_img, prefix="agent-results/noise-detected-object")
    final_image_url = create_presigned_url(final_s3_key)

    return json.dumps({
        "message": f"I added salt-and-pepper noise to the {position} {label} in the image.",
        "image_url": final_image_url,
    })


# Registry: map tool name -> tool function
TOOLS = {
    detect_objects.name: detect_objects,
    blur_image.name: blur_image,
    rotate_image.name: rotate_image,
    flip_image.name: flip_image,
    resize_image.name: resize_image,
    crop_image.name: crop_image,
    add_noise_image.name: add_noise_image,
    crop_detected_object.name: crop_detected_object,
    blur_detected_object.name: blur_detected_object,
    add_noise_to_detected_object.name: add_noise_to_detected_object,
}

rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.2,  # 1 request every 5 seconds
    check_every_n_seconds=0.1,
    max_bucket_size=2,
)

if MODEL.startswith("bedrock/"):
    llm = init_chat_model(
        MODEL.replace("bedrock/", ""),
        model_provider="bedrock",
        temperature=0,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        rate_limiter=rate_limiter,
    )
else:
    llm = init_chat_model(
        MODEL,
        temperature=0,
        rate_limiter=rate_limiter,
    )

llm_with_tools = llm.bind_tools(list(TOOLS.values()))

def run_agent(history: list, max_iterations: int = 10) -> str:
    """
    Simple ReAct loop:
      1. Send messages to the LLM.
      2. If the LLM requests tool calls, execute them and append results.
      3. Repeat until the LLM returns a plain text response.
      4. Stop after max_iterations to guard against infinite loops.
    """
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + history
    iterations = 0
    tools_called = []
    prediction_id = None
    annotated_image = None
    context_limit_exceeded = False

    while True:
        if iterations >= max_iterations:
                return {
                    "response": "I reached the maximum number of reasoning steps. Please try again with a simpler request.",
                    "prediction_id": prediction_id,
                    "annotated_image": annotated_image,
                    "agent_loop_time_s": 0.0,
                    "iterations": iterations,
                    "tools_called": tools_called,
                    "context_limit_exceeded": True,
                }

        iterations += 1
        response: AIMessage = llm_with_tools.invoke(messages)
        messages.append(response)

        if response.tool_calls:
            for tool_call in response.tool_calls:
                tools_called.append(tool_call["name"])
                tool_fn = TOOLS[tool_call["name"]]
                tool_result = tool_fn.invoke(tool_call)          # returns a ToolMessage
                messages.append(tool_result)

                try:
                    parsed = json.loads(tool_result.content)
                    if isinstance(parsed, dict):
                        prediction_id = parsed.get("uid") or parsed.get("prediction_uid") or prediction_id
                        annotated_image = parsed.get("annotated_image", annotated_image)

                        image_url = parsed.get("image_url")
                        if isinstance(image_url, str) and image_url:
                            return {
                                "response": build_image_response(
                                    parsed.get("message", ""),
                                    image_url,
                                ),
                                "prediction_id": prediction_id,
                                "annotated_image": annotated_image,
                                "agent_loop_time_s": 0.0,
                                "iterations": iterations,
                                "tools_called": tools_called,
                                "context_limit_exceeded": context_limit_exceeded,
                            }
                except Exception:
                    pass

            continue

        if isinstance(response.content, str):
            final_response = response.content
        elif isinstance(response.content, list):
            final_response = "\n".join(
                part.get("text", str(part)) if isinstance(part, dict) else str(part)
                for part in response.content
            )
        else:
            final_response = str(response.content)

        return {
            "response": final_response,
            "prediction_id": prediction_id,
            "annotated_image": annotated_image,
            "agent_loop_time_s": 0.0,
            "iterations": iterations,
            "tools_called": tools_called,
            "context_limit_exceeded": context_limit_exceeded,
        }


app = FastAPI(title="Vision Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://gnaiem-dev.fursa.click:3000", "http://gnaiem-prod.fursa.click:3000"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type"],
)

Instrumentator().instrument(app).expose(app)

class ChatMessage(BaseModel):
    role: str                           # "user" or "assistant"
    content: str
    image_base64: Optional[str] = None  # only on user messages that carry an image


class ChatRequest(BaseModel):
    messages: list[ChatMessage]         # full conversation thread, oldest first


class ChatResponse(BaseModel):
    response: str
    prediction_id: Optional[str] = None
    annotated_image: Optional[str] = None
    agent_loop_time_s: float
    iterations: int
    tools_called: list[str]
    context_limit_exceeded: bool = False

def get_unsupported_detected_object_edit_message(user_text: str) -> Optional[str]:
    """
    Detect requests like:
    - rotate the detected person
    - resize detected laptop
    - flip the car

    These are object-specific edits we do not currently support.
    """
    text = user_text.lower()

    detected_object_words = [
        "detected", "object", "person", "people", "dog", "cat", "car", "laptop", "chair", "bottle", "bus", "truck", "bike","bicycle",
    ]

    unsupported_operations = {
        "rotate": ["rotate", "turn"],
        "resize": ["resize", "make bigger", "make smaller", "scale"],
        "flip": ["flip", "mirror"],
    }

    mentions_object = any(word in text for word in detected_object_words)

    if not mentions_object:
        return None

    for operation, keywords in unsupported_operations.items():
        if any(keyword in text for keyword in keywords):
            return (
                f"I can {operation} the whole image, but I currently cannot {operation} only a detected object. "
                "For detected objects, I can blur, crop, or add noise. "
            )

    return None

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    latest_user_msg = None
    latest_image = None

    # Find the latest user message and latest uploaded image
    for msg in request.messages:
        if msg.role == "user":
            latest_user_msg = msg
            if msg.image_base64:
                latest_image = msg.image_base64

    if latest_user_msg is None:
        return ChatResponse(
            response="No user message was provided.",
            prediction_id=None,
            annotated_image=None,
            agent_loop_time_s=0.0,
            iterations=0,
            tools_called=[],
            context_limit_exceeded=False,
        )

    content = latest_user_msg.content

    unsupported_message = get_unsupported_detected_object_edit_message(content)
    if unsupported_message:
        return ChatResponse(
            response=unsupported_message,
            prediction_id=None,
            annotated_image=None,
            agent_loop_time_s=0.0,
            iterations=0,
            tools_called=[],
            context_limit_exceeded=False,
        )

    if latest_image:
        content += (
            "\n[An image was uploaded with this message. "
            "Use the available tools to analyze or edit this uploaded image according to the user instructions.]"
        )

    lc_messages = [HumanMessage(content=content)]

    token = _current_image_b64.set(latest_image)
    try:
        start_time = time.time()
        result = run_agent(lc_messages)
        result["agent_loop_time_s"] = round(time.time() - start_time, 2)
        return ChatResponse(**result)
    finally:
        _current_image_b64.reset(token)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
