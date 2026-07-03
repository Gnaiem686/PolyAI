import io
import json
import os
import uuid

import boto3
from mcp.server.fastmcp import FastMCP
from PIL import Image, ImageFilter, ImageOps


mcp = FastMCP("img-proc")

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


@mcp.tool()
def blur(input_s3_key: str, radius: float = 2.0) -> str:
    """
    Apply Gaussian blur to an image stored in S3.

    Args:
        input_s3_key: S3 key of the input image.
        radius: Gaussian blur radius.

    Returns:
        JSON string with output_s3_key.
    """
    img = _download_image_from_s3(input_s3_key)
    blurred_img = img.filter(ImageFilter.GaussianBlur(radius))
    output_s3_key = _upload_image_to_s3(blurred_img, prefix="processed/blur")

    return json.dumps(
        {
            "input_s3_key": input_s3_key,
            "output_s3_key": output_s3_key,
            "operation": "blur",
            "radius": radius,
        }
    )

@mcp.tool()
def rotate(input_s3_key: str, angle: float = 90.0, expand: bool = True) -> str:
    """
    Rotate an image stored in S3.

    Args:
        input_s3_key: S3 key of the input image.
        angle: Rotation angle in degrees.
        expand: If True, expand the output image size to fit the rotated image.

    Returns:
        JSON string with output_s3_key.
    """
    img = _download_image_from_s3(input_s3_key)
    rotated_img = img.rotate(angle, expand=expand)
    output_s3_key = _upload_image_to_s3(rotated_img, prefix="processed/rotate")

    return json.dumps(
        {
            "input_s3_key": input_s3_key,
            "output_s3_key": output_s3_key,
            "operation": "rotate",
            "angle": angle,
            "expand": expand,
        }
    )

@mcp.tool()
def flip(input_s3_key: str, direction: str = "horizontal") -> str:
    """
    Flip an image stored in S3.

    Args:
        input_s3_key: S3 key of the input image.
        direction: "horizontal" or "vertical".

    Returns:
        JSON string with output_s3_key.
    """
    img = _download_image_from_s3(input_s3_key)

    normalized_direction = direction.lower().strip()

    if normalized_direction == "horizontal":
        flipped_img = ImageOps.mirror(img)
    elif normalized_direction == "vertical":
        flipped_img = ImageOps.flip(img)
    else:
        raise ValueError("direction must be either 'horizontal' or 'vertical'")

    output_s3_key = _upload_image_to_s3(flipped_img, prefix="processed/flip")

    return json.dumps(
        {
            "input_s3_key": input_s3_key,
            "output_s3_key": output_s3_key,
            "operation": "flip",
            "direction": normalized_direction,
        }
    )

@mcp.tool()
def resize(input_s3_key: str, width: int, height: int) -> str:
    """
    Resize an image stored in S3.

    Args:
        input_s3_key: S3 key of the input image.
        width: Target width in pixels.
        height: Target height in pixels.

    Returns:
        JSON string with output_s3_key.
    """
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive integers")

    img = _download_image_from_s3(input_s3_key)
    resized_img = img.resize((width, height))

    output_s3_key = _upload_image_to_s3(resized_img, prefix="processed/resize")

    return json.dumps(
        {
            "input_s3_key": input_s3_key,
            "output_s3_key": output_s3_key,
            "operation": "resize",
            "width": width,
            "height": height,
        }
    )


if __name__ == "__main__":
    mcp.run()