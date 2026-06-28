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

from dotenv import load_dotenv
import time
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("langchain").setLevel(logging.DEBUG)
logging.getLogger("langchain_core").setLevel(logging.DEBUG)

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")

s3_client = boto3.client("s3", region_name=AWS_REGION)

YOLO_SERVICE_URL = os.environ.get("YOLO_SERVICE_URL", "http://localhost:8080")
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
    "You are an AI vision assistant. You help users understand and analyze images. "
    "Use the available tools to extract information from images. "
)

_current_image_b64: ContextVar[Optional[str]] = ContextVar("current_image_b64", default=None)

def upload_image_to_s3(image_b64: str) -> str:
    image_bytes = base64.b64decode(image_b64)

    chat_id = str(uuid.uuid4())
    prediction_id = str(uuid.uuid4())
    key = f"{chat_id}/{prediction_id}/original/image.jpg"

    s3_client.put_object(
        Bucket=AWS_S3_BUCKET,
        Key=key,
        Body=image_bytes,
        ContentType="image/jpeg",
    )

    return key

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


# Registry: map tool name -> tool function
TOOLS = {
    detect_objects.name: detect_objects
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


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    lc_messages = []
    latest_image = None

    for msg in request.messages:
        if msg.role == "user":
            if msg.image_base64:
                latest_image = msg.image_base64          # saved for detect_objects tool
                content = msg.content + "\n[An image was uploaded. Use existing tools to analyze it according to user instructions.]"
            else:
                content = msg.content
            lc_messages.append(HumanMessage(content=content))
        else:
            lc_messages.append(AIMessage(content=msg.content))

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
