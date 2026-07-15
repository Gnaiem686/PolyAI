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
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

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
from langchain_core.tools import tool
from pydantic import BaseModel

YOLO_SERVICE_URL = os.environ.get("YOLO_SERVICE_URL", "http://localhost:8080")
IMG_PROC_MCP_URL = os.getenv("IMG_PROC_MCP_URL", "http://localhost:8100/mcp")
MCP_SERVERS = {
    "img-proc": {
        "url": IMG_PROC_MCP_URL,
        "transport": "streamable_http",
    }
}
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

    "Use only the available MCP tools to modify images. "
    "The MCP tools include blur, rotate, flip, resize, crop, and add_noise. "

    "When calling an MCP image tool, always use the exact current working image S3 key as input_s3_key. "
    "Never invent, rewrite, shorten, or modify the input_s3_key. "

    "When the user asks to edit the whole image, use the full-image coordinates provided in the system messages. "
    "When the user asks to edit a detected object, use the detected-object coordinates provided in the system messages. "

    "For blur requests, always call the MCP tool named blur. "
    "For add-noise requests, always call the MCP tool named add_noise. "
    "For crop requests, always call the MCP tool named crop. "

    "When calling blur or add_noise, always include input_s3_key, left, top, right, and bottom. "
    "When calling crop, always include input_s3_key, left, top, right, and bottom. "

    "For whole-image edit requests, do not call detect_objects. "
    "Use the full-image coordinates provided in the system message. "

    "For object-specific or region-specific edit requests, first call detect_objects. "
    "An object-specific request is any request where the user wants to edit only a subject, object, item, thing, person, region, area, or part of the image instead of the whole image. "
    "Requests with spatial or ordinal descriptions such as leftmost, rightmost, first from left, second from left, nearest, farthest, top, bottom, center, foreground, or background are object-specific or region-specific. "

    "After detect_objects returns objects, choose the detected object whose label and positions best match the user's request. "
    "Then call the correct MCP image tool using that object's exact left, top, right, and bottom coordinates. "

    "For blur requests, call blur. "
    "For crop requests, call crop. "
    "For add-noise requests, call add_noise. "

    "Do not use full-image coordinates for object-specific or region-specific requests. "
    "Do not ask the user for coordinates if detect_objects can provide object coordinates. "

    "Do not ask the user for coordinates if coordinates are already provided in the system messages. "
    "Do not ask the user for the label if the object word already appears in the request. "

    "If an MCP tool returns output_s3_key, that output becomes the new current working image. "
    "Never invent, rewrite, copy, or mention image URLs unless they are returned by the system. "
    "Never copy old assistant messages as the answer. "
    "Never output <thinking> tags or hidden reasoning. Give only the final answer to the user."

    "For object-specific edit requests, first call detect_objects. "
    "After detect_objects returns objects, choose the object whose label and positions match the user request. "
    "Then call the correct MCP image tool using the object's left, top, right, and bottom coordinates. "
    "For example, if the user asks to blur the leftmost person, call detect_objects first, then call blur with the leftmost person coordinates. "
)

_current_image_b64: ContextVar[Optional[str]] = ContextVar("current_image_b64", default=None)
_current_session_id: ContextVar[Optional[str]] = ContextVar("current_session_id", default=None)
_current_image_s3_key: ContextVar[Optional[str]] = ContextVar("current_image_s3_key", default=None)

LATEST_IMAGE_BY_SESSION: dict[str, str] = {}

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

def remember_latest_image(output_s3_key: str) -> None:
    """
    Save the latest processed image for the current chat session.
    """
    session_id = _current_session_id.get()
    if session_id:
        LATEST_IMAGE_BY_SESSION[session_id] = output_s3_key
        logging.info("SESSION_IMAGE_SAVE session=%s key=%s", session_id, output_s3_key)

    _current_image_s3_key.set(output_s3_key)


def get_current_image_s3_key() -> str:
    """
    Resolve which image should be used by tools.

    Priority:
    1. Current request uploaded image, already uploaded to S3
    2. Latest processed image for this session
    3. Error if no image exists
    """
    image_s3_key = _current_image_s3_key.get()

    if image_s3_key:
        logging.info("SESSION_IMAGE_USE contextvar key=%s", image_s3_key)
        return image_s3_key

    session_id = _current_session_id.get()
    if session_id and session_id in LATEST_IMAGE_BY_SESSION:
        image_s3_key = LATEST_IMAGE_BY_SESSION[session_id]
        logging.info("SESSION_IMAGE_USE stored session=%s key=%s", session_id, image_s3_key)
        _current_image_s3_key.set(image_s3_key)
        return image_s3_key

    image_b64 = _current_image_b64.get()
    if image_b64:
        image_s3_key = upload_image_to_s3(image_b64)
        logging.info("SESSION_IMAGE_USE uploaded_new_image key=%s", image_s3_key)
        remember_latest_image(image_s3_key)
        return image_s3_key

    raise RuntimeError(
        "No image was provided and there is no previous processed image in this chat."
    )

def download_image_from_s3(s3_key: str) -> Image.Image:
    if not AWS_S3_BUCKET:
        raise RuntimeError("AWS_S3_BUCKET environment variable is not set")

    response = s3_client.get_object(
        Bucket=AWS_S3_BUCKET,
        Key=s3_key,
    )

    image_bytes = response["Body"].read()
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")

def get_full_image_context_for_prompt(input_s3_key: str) -> str:
    img = download_image_from_s3(input_s3_key)
    width, height = img.size

    return (
        "Current working image S3 key:\n"
        f"{input_s3_key}\n\n"
        "Full image coordinates:\n"
        f"- left=0; top=0; right={width}; bottom={height}\n\n"
        "Use these full-image coordinates when the user asks to edit the whole image. "
        "When calling MCP tools, use the exact input_s3_key shown above."
    )

def parse_yolo_box(box_value) -> tuple[int, int, int, int]:
    if isinstance(box_value, str):
        box_value = box_value.strip()

        try:
            box = ast.literal_eval(box_value)
        except (ValueError, SyntaxError):
            box = [part.strip() for part in box_value.split(",")]
    else:
        box = box_value

    if not isinstance(box, (list, tuple)):
        raise ValueError(f"YOLO box must be a list or tuple, got: {type(box)}")

    if len(box) != 4:
        raise ValueError(f"YOLO box must contain four values, got: {box}")

    left, top, right, bottom = box

    return (
        max(0, int(float(left))),
        max(0, int(float(top))),
        max(0, int(float(right))),
        max(0, int(float(bottom))),
    )


def clamp_box_to_image(left: int, top: int, right: int, bottom: int, img: Image.Image) -> tuple[int, int, int, int]:
    width, height = img.size
    left = max(0, min(left, width - 1))
    right = max(left + 1, min(right, width))
    top = max(0, min(top, height - 1))
    bottom = max(top + 1, min(bottom, height))
    return left, top, right, bottom

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

@tool
def detect_objects() -> str:
    """
    Detect objects in the current image using YOLO.

    Use this tool before any object-specific or region-specific edit request.
    Examples of object-specific requests include editing only:
    - one subject/object/item/thing in the image
    - something described by position
    - something described by ordinal order
    - something described as foreground/background/center/top/bottom

    This tool does not modify the image.
    It returns detected objects with labels, positions, and ready-to-use MCP coordinates.
    """
    try:
        image_s3_key = get_current_image_s3_key()
    except RuntimeError as exc:
        return json.dumps({"error": str(exc)})

    with httpx.Client(timeout=60.0) as client:
        predict_response = client.post(
            f"{YOLO_SERVICE_URL}/predict",
            json={"image_s3_key": image_s3_key},
        )
        predict_response.raise_for_status()
        predict_result = predict_response.json()

        prediction_uid = predict_result["prediction_uid"]

        details_response = client.get(f"{YOLO_SERVICE_URL}/prediction/{prediction_uid}")
        details_response.raise_for_status()
        prediction_details = details_response.json()

    detection_objects = prediction_details.get("detection_objects", [])

    if not detection_objects:
        return json.dumps({
            "message": "No objects were detected in the current image.",
            "prediction_uid": prediction_uid,
            "detection_count": 0,
            "objects": [],
        })

    img = download_image_from_s3(image_s3_key)

    grouped: dict[str, list[dict]] = {}

    for obj in detection_objects:
        label = obj.get("label", "").lower().strip()
        if not label:
            continue

        left, top, right, bottom = parse_yolo_box(obj["box"])
        left, top, right, bottom = clamp_box_to_image(
            left,
            top,
            right,
            bottom,
            img,
        )

        grouped.setdefault(label, []).append({
            "label": label,
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "score": obj.get("score"),
            "original_detection": obj,
        })

    ready_objects = []

    for label, objects in grouped.items():
        objects_sorted = sorted(
            objects,
            key=lambda o: (o["left"] + o["right"]) / 2,
        )

        n = len(objects_sorted)

        for index, obj in enumerate(objects_sorted):
            positions = []

            if index == 0:
                positions.extend(["leftmost", "first from left"])

            if index == n - 1:
                positions.extend(["rightmost", "first from right"])

            if index == 1:
                positions.append("second from left")

            if index == n - 2:
                positions.append("second from right")

            positions.append(f"#{index + 1} from left")

            ready_objects.append({
                "label": label,
                "positions": positions,
                "left": obj["left"],
                "top": obj["top"],
                "right": obj["right"],
                "bottom": obj["bottom"],
                "score": obj["score"],
            })

    return json.dumps({
        "message": (
            "Detected objects in the current image. "
            "Use left/top/right/bottom exactly when calling MCP blur, crop, or add_noise."
        ),
        "input_s3_key": image_s3_key,
        "prediction_uid": prediction_uid,
        "detection_count": len(ready_objects),
        "objects": ready_objects,
    })

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

# In direct MCP mode, tools are discovered inside run_agent()
# using MultiServerMCPClient. Do not bind local TOOLS globally.

def _tool_result_to_text(result) -> str:
    """
    Convert MCP tool result into text for ToolMessage.
    """
    if isinstance(result, str):
        return result

    if isinstance(result, (dict, list)):
        return json.dumps(result)

    if hasattr(result, "content"):
        return _tool_result_to_text(result.content)

    return str(result)


def _extract_dict_from_tool_result(result) -> dict:
    """
    Try to extract the actual dict returned by an MCP tool.

    Handles shapes like:
    - {"output_s3_key": "..."}
    - "{\"output_s3_key\": \"...\"}"
    - [{"type": "text", "text": "{\"output_s3_key\": \"...\"}"}]
    - {"content": [...]}
    - {"structuredContent": {...}}
    """
    if hasattr(result, "content"):
        return _extract_dict_from_tool_result(result.content)

    if isinstance(result, dict):
        if "output_s3_key" in result:
            return result

        if "structuredContent" in result:
            return _extract_dict_from_tool_result(result["structuredContent"])

        if "content" in result:
            return _extract_dict_from_tool_result(result["content"])

        if "result" in result:
            return _extract_dict_from_tool_result(result["result"])

        if "text" in result:
            return _extract_dict_from_tool_result(result["text"])

        return result

    if isinstance(result, list):
        if not result:
            return {}
        for item in result:
            data = _extract_dict_from_tool_result(item)
            if data:
                return data

        return {}
    if isinstance(result, str):
        text = result.strip()
        try:
            return _extract_dict_from_tool_result(json.loads(text))
        except json.JSONDecodeError:
            return {}

    return {}
    
async def run_agent(history: list, user_text: str | None = None, max_iterations: int = 10) -> dict:
    """
    Direct MCP ReAct loop:
      1. Discover MCP tools from img-proc-mcp.
      2. Bind those MCP tools directly to the LLM.
      3. If the LLM requests an MCP tool call, execute that MCP tool.
      4. If the MCP tool returns output_s3_key, save it as the latest session image.
    """
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + history
    iterations = 0
    tools_called = []
    prediction_id = None
    annotated_image = None
    context_limit_exceeded = False
    client = MultiServerMCPClient(MCP_SERVERS)
    mcp_tools = await client.get_tools()
    local_tools = [detect_objects]
    all_tools = local_tools + mcp_tools
    tool_map = {tool.name: tool for tool in all_tools}
    logging.info("TOOLS_BOUND_TO_LLM %s", list(tool_map.keys()))
    llm_with_tools = llm.bind_tools(all_tools)

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
        response: AIMessage = await llm_with_tools.ainvoke(messages)
        messages.append(response)
        if response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call.get("args", {})
                tool_call_id = tool_call["id"]
                tools_called.append(tool_name)
                if tool_name not in tool_map:
                    tool_message_content = json.dumps({
                        "error": f"MCP tool not found: {tool_name}",
                        "available_tools": list(tool_map.keys()),
                    })
                    messages.append(
                        ToolMessage(
                            content=tool_message_content,
                            tool_call_id=tool_call_id,
                        )
                    )
                    continue
                try:
                    logging.info("TOOL_CALL name=%s args=%s", tool_name, tool_args)

                    tool_obj = tool_map[tool_name]
                    raw_tool_result = await tool_obj.ainvoke(tool_args)
                    parsed = _extract_dict_from_tool_result(raw_tool_result)
                    output_s3_key = parsed.get("output_s3_key") if isinstance(parsed, dict) else None
                    if output_s3_key:
                        remember_latest_image(output_s3_key)
                        image_url = create_presigned_url(output_s3_key)
                        parsed["image_url"] = image_url
                        messages.append(
                            ToolMessage(
                                content=json.dumps(parsed),
                                tool_call_id=tool_call_id,
                            )
                        )
                        operation_messages = {
                            "blur": "I blurred the image.",
                            "add_noise": "I added noise to the image.",
                            "crop": "I cropped the image.",
                            "rotate": "I rotated the image.",
                            "flip": "I flipped the image.",
                            "resize": "I resized the image.",
                        }
                        message = operation_messages.get(tool_name, f"I applied {tool_name} to the image.")

                        return {
                            "response": build_image_response(message, image_url),
                            "prediction_id": prediction_id,
                            "annotated_image": annotated_image,
                            "agent_loop_time_s": 0.0,
                            "iterations": iterations,
                            "tools_called": tools_called,
                            "context_limit_exceeded": context_limit_exceeded,
                        }
                    messages.append(
                        ToolMessage(
                            content=_tool_result_to_text(raw_tool_result),
                            tool_call_id=tool_call_id,
                        )
                    )
                except Exception as exc:
                    logging.exception("TOOL_CALL_FAILED name=%s", tool_name)
                    messages.append(
                        ToolMessage(
                            content=json.dumps({"error": str(exc)}),
                            tool_call_id=tool_call_id,
                        )
                    )

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
    allow_origins=["http://localhost:3000", "http://gnaiem-dev.fursa.click:3000", "http://gnaiem-prod.fursa.click:3000", "http://54.91.9.69:3000"],
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
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: Optional[str] = None
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
async def chat(request: ChatRequest):
    latest_user_msg = None

    # Find only the latest user message
    for msg in request.messages:
        if msg.role == "user":
            latest_user_msg = msg
    if latest_user_msg is None:
        return ChatResponse(
            response="No user message was provided.",
            session_id=request.session_id,
            prediction_id=None,
            annotated_image=None,
            agent_loop_time_s=0.0,
            iterations=0,
            tools_called=[],
            context_limit_exceeded=False,
        )
    session_id = request.session_id or str(uuid.uuid4())
    latest_image = latest_user_msg.image_base64
    content = latest_user_msg.content
    original_user_text = latest_user_msg.content
    unsupported_message = get_unsupported_detected_object_edit_message(content)
    if unsupported_message:
        return ChatResponse(
            response=unsupported_message,
            session_id=session_id,
            prediction_id=None,
            annotated_image=None,
            agent_loop_time_s=0.0,
            iterations=0,
            tools_called=[],
            context_limit_exceeded=False,
        )
    uploaded_image_s3_key = None
    if latest_image:
        uploaded_image_s3_key = upload_image_to_s3(latest_image)
        LATEST_IMAGE_BY_SESSION[session_id] = uploaded_image_s3_key

        content += (
            "\n[An image was uploaded with this message. "
            "Use the available MCP image tools to edit this uploaded image according to the user instructions.]"
        )
    active_image_s3_key = None
    if uploaded_image_s3_key:
        active_image_s3_key = uploaded_image_s3_key
    elif session_id in LATEST_IMAGE_BY_SESSION:
        active_image_s3_key = LATEST_IMAGE_BY_SESSION[session_id]

    lc_messages = []

    if active_image_s3_key:
        full_image_context = get_full_image_context_for_prompt(active_image_s3_key)
        logging.info("FULL_IMAGE_CONTEXT_FOR_PROMPT:\n%s", full_image_context)

        lc_messages.append(SystemMessage(content=full_image_context))
    else:
        lc_messages.append(
            SystemMessage(
                content=(
                    "No current working image S3 key is available. "
                    "If the user asks for image editing, ask them to upload an image."
                )
            )
        )

    lc_messages.append(HumanMessage(content=content))
    image_token = _current_image_b64.set(latest_image)
    session_token = _current_session_id.set(session_id)
    s3_key_token = _current_image_s3_key.set(active_image_s3_key)

    try:
        start_time = time.time()

        result = await run_agent(lc_messages, user_text=original_user_text)

        result["agent_loop_time_s"] = round(time.time() - start_time, 2)
        result["session_id"] = session_id

        return ChatResponse(**result)

    finally:
        _current_image_b64.reset(image_token)
        _current_session_id.reset(session_token)
        _current_image_s3_key.reset(s3_key_token)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
