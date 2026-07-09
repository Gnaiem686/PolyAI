import io
import json
import os
import uuid

import boto3
from mcp.server.fastmcp import FastMCP
from PIL import Image, ImageFilter, ImageOps
import random
import numpy as np
from dotenv import load_dotenv
load_dotenv()

mcp = FastMCP("img-proc", host="0.0.0.0", port=8100)

AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")
s3_client = boto3.client("s3")


def _require_bucket() -> str:
    if not AWS_S3_BUCKET:
        raise RuntimeError("AWS_S3_BUCKET environment variable is not set")
    return AWS_S3_BUCKET


def _download_image_from_s3(input_s3_key: str) -> Image.Image:
    bucket = _require_bucket()

    response = s3_client.get_object(
        Bucket=bucket,
        Key=input_s3_key,
    )

    image_bytes = response["Body"].read()
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def _upload_image_to_s3(img: Image.Image, prefix: str = "processed") -> str:
    bucket = _require_bucket()

    output_s3_key = f"{prefix}/{uuid.uuid4()}.png"

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    s3_client.put_object(
        Bucket=bucket,
        Key=output_s3_key,
        Body=buffer.getvalue(),
        ContentType="image/png",
    )

    return output_s3_key


def clamp_box_to_image(
    left: int,
    top: int,
    right: int,
    bottom: int,
    img: Image.Image,
) -> tuple[int, int, int, int]:
    width, height = img.size
    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    return left, top, right, bottom

def resolve_region(
    img: Image.Image,
    left: int | None = None,
    top: int | None = None,
    right: int | None = None,
    bottom: int | None = None,
) -> tuple[int, int, int, int]:
    """
    Resolve optional coordinates.

    If no coordinates are provided, use the whole image.
    If coordinates are provided, clamp them to the image bounds.
    """
    width, height = img.size

    if left is None:
        left = 0
    if top is None:
        top = 0
    if right is None:
        right = width
    if bottom is None:
        bottom = height

    return clamp_box_to_image(left, top, right, bottom, img)

def paste_processed_region(
    original_img: Image.Image,
    processed_region: Image.Image,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> Image.Image:
    final_img = original_img.copy()
    region_width = right - left
    region_height = bottom - top

    if processed_region.size != (region_width, region_height):
        processed_region = processed_region.resize((region_width, region_height))

    final_img.paste(processed_region, (left, top))
    return final_img

############################################----- blur -----###################################################
def _blur_image(
    input_s3_key: str,
    radius: float = 2.0,
    left: int | None = None,
    top: int | None = None,
    right: int | None = None,
    bottom: int | None = None,
) -> dict:
    img = _download_image_from_s3(input_s3_key)

    left, top, right, bottom = resolve_region(
        img=img,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
    )

    region = img.crop((left, top, right, bottom))
    blurred_region = region.filter(ImageFilter.GaussianBlur(radius))

    final_img = paste_processed_region(
        original_img=img,
        processed_region=blurred_region,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
    )

    output_s3_key = _upload_image_to_s3(final_img, prefix="processed/blur")

    return {
        "input_s3_key": input_s3_key,
        "output_s3_key": output_s3_key,
        "operation": "blur",
        "radius": radius,
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
    }


@mcp.tool()
def blur(
    input_s3_key: str,
    radius: float = 2.0,
    left: int | None = None,
    top: int | None = None,
    right: int | None = None,
    bottom: int | None = None,
) -> str:
    """
    Apply Gaussian blur to an image or a rectangular region inside it.

    If left/top/right/bottom are omitted, blur the whole image.
    If coordinates are provided, blur only that region.
    """
    return json.dumps(
        _blur_image(
            input_s3_key=input_s3_key,
            radius=radius,
            left=left,
            top=top,
            right=right,
            bottom=bottom,
        )
    )

############################################----- rotate -----###################################################
def _rotate_image(input_s3_key: str, angle: float = 90.0, expand: bool = True) -> dict:
    img = _download_image_from_s3(input_s3_key)
    rotated_img = img.rotate(angle, expand=expand)
    output_s3_key = _upload_image_to_s3(rotated_img, prefix="processed/rotate")

    return {
        "input_s3_key": input_s3_key,
        "output_s3_key": output_s3_key,
        "operation": "rotate",
        "angle": angle,
        "expand": expand,
    }

@mcp.tool()
def rotate(input_s3_key: str, angle: float = 90.0, expand: bool = True) -> str:
    """Rotate an image stored in S3."""
    return json.dumps(_rotate_image(input_s3_key, angle, expand))

############################################----- flip -----###################################################
def _flip_image(input_s3_key: str, direction: str = "horizontal") -> dict:
    img = _download_image_from_s3(input_s3_key)

    normalized_direction = direction.lower().strip()

    if normalized_direction == "horizontal":
        flipped_img = ImageOps.mirror(img)
    elif normalized_direction == "vertical":
        flipped_img = ImageOps.flip(img)
    else:
        raise ValueError("direction must be either 'horizontal' or 'vertical'")

    output_s3_key = _upload_image_to_s3(flipped_img, prefix="processed/flip")

    return {
        "input_s3_key": input_s3_key,
        "output_s3_key": output_s3_key,
        "operation": "flip",
        "direction": normalized_direction,
    }

@mcp.tool()
def flip(input_s3_key: str, direction: str = "horizontal") -> str:
    """Flip an image stored in S3."""
    return json.dumps(_flip_image(input_s3_key, direction))

############################################----- resize -----###################################################
def _resize_image(input_s3_key: str, width: int, height: int) -> dict:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive integers")

    img = _download_image_from_s3(input_s3_key)
    resized_img = img.resize((width, height))
    output_s3_key = _upload_image_to_s3(resized_img, prefix="processed/resize")

    return {
        "input_s3_key": input_s3_key,
        "output_s3_key": output_s3_key,
        "operation": "resize",
        "width": width,
        "height": height,
    }


@mcp.tool()
def resize(input_s3_key: str, width: int, height: int) -> str:
    """Resize an image stored in S3."""
    return json.dumps(_resize_image(input_s3_key, width, height))

############################################----- add noise -----###################################################
def _add_noise_to_image(
    input_s3_key: str,
    amount: float = 0.05,
    left: int | None = None,
    top: int | None = None,
    right: int | None = None,
    bottom: int | None = None,
) -> dict:
    if amount < 0 or amount > 1:
        raise ValueError("amount must be between 0 and 1")

    img = _download_image_from_s3(input_s3_key)

    left, top, right, bottom = resolve_region(
        img=img,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
    )

    region = img.crop((left, top, right, bottom))
    arr = np.array(region).copy()

    height, width = arr.shape[:2]
    total_pixels = height * width
    noisy_pixels = int(total_pixels * amount)

    for _ in range(noisy_pixels):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)

        if random.random() < 0.5:
            arr[y, x] = [0, 0, 0]
        else:
            arr[y, x] = [255, 255, 255]

    noisy_region = Image.fromarray(arr.astype("uint8"), "RGB")

    final_img = paste_processed_region(
        original_img=img,
        processed_region=noisy_region,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
    )

    output_s3_key = _upload_image_to_s3(final_img, prefix="processed/noise")

    return {
        "input_s3_key": input_s3_key,
        "output_s3_key": output_s3_key,
        "operation": "add_noise",
        "amount": amount,
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
    }


@mcp.tool()
def add_noise(
    input_s3_key: str,
    amount: float = 0.05,
    left: int | None = None,
    top: int | None = None,
    right: int | None = None,
    bottom: int | None = None,
) -> str:
    """
    Add salt-and-pepper noise to an image or a rectangular region.

    If left/top/right/bottom are omitted, add noise to the whole image.
    If coordinates are provided, add noise only to that region.
    """
    return json.dumps(
        _add_noise_to_image(
            input_s3_key=input_s3_key,
            amount=amount,
            left=left,
            top=top,
            right=right,
            bottom=bottom,
        )
    )

############################################----- crop -----###################################################
def _crop_image(input_s3_key: str, left: int, top: int, right: int, bottom: int) -> dict:
    img = _download_image_from_s3(input_s3_key)

    left, top, right, bottom = resolve_region(
        img=img,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
    )

    cropped_img = img.crop((left, top, right, bottom))
    output_s3_key = _upload_image_to_s3(cropped_img, prefix="processed/crop")

    return {
        "input_s3_key": input_s3_key,
        "output_s3_key": output_s3_key,
        "operation": "crop",
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
    }

@mcp.tool()
def crop(input_s3_key: str, left: int, top: int, right: int, bottom: int) -> str:
    """
    Crop a rectangular region from an image stored in S3.

    Use the full image bounds to crop the whole image.
    Use detected object coordinates to crop a detected object.
    """
    return json.dumps(_crop_image(input_s3_key, left, top, right, bottom))

if __name__ == "__main__":
    try:
        mcp.run(transport="streamable-http")
    except KeyboardInterrupt:
        print("MCP server stopped.")