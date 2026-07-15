import io
import json
import os

import boto3
import pytest
from moto import mock_aws
from PIL import Image


os.environ.setdefault("AWS_S3_BUCKET", "test-bucket")


@pytest.fixture
def s3_setup(monkeypatch):
    with mock_aws():
        import app

        bucket = "test-bucket"

        monkeypatch.setattr(app, "AWS_S3_BUCKET", bucket)
        monkeypatch.setattr(
            app,
            "s3_client",
            boto3.client("s3", region_name="us-east-1"),
        )

        app.s3_client.create_bucket(Bucket=bucket)

        input_key = "uploads/test-flip.png"

        yield app, input_key, bucket


def upload_test_image(app, bucket: str, key: str, img: Image.Image) -> None:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    app.s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=buffer.getvalue(),
        ContentType="image/png",
    )


def load_s3_image(app, bucket: str, key: str) -> Image.Image:
    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=key,
    )

    output_bytes = response["Body"].read()
    return Image.open(io.BytesIO(output_bytes))


def test_flip_horizontal_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    img = Image.new("RGB", (2, 1))
    img.putpixel((0, 0), (255, 0, 0))  # left red
    img.putpixel((1, 0), (0, 0, 255))  # right blue

    upload_test_image(app, bucket, input_key, img)

    result_json = app.flip(
        input_s3_key=input_key,
        direction="horizontal",
    )
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "flip"
    assert result["direction"] == "horizontal"
    assert result["output_s3_key"].startswith("processed/flip/")
    assert result["output_s3_key"].endswith(".png")

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (2, 1)
    assert output_img.format == "PNG"

    # Original: red, blue
    # Flipped:  blue, red
    assert output_img.getpixel((0, 0)) == (0, 0, 255)
    assert output_img.getpixel((1, 0)) == (255, 0, 0)


def test_flip_vertical_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    img = Image.new("RGB", (1, 2))
    img.putpixel((0, 0), (255, 0, 0))  # top red
    img.putpixel((0, 1), (0, 0, 255))  # bottom blue

    upload_test_image(app, bucket, input_key, img)

    result_json = app.flip(
        input_s3_key=input_key,
        direction="vertical",
    )
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "flip"
    assert result["direction"] == "vertical"
    assert result["output_s3_key"].startswith("processed/flip/")
    assert result["output_s3_key"].endswith(".png")

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (1, 2)
    assert output_img.format == "PNG"

    # Original: top red, bottom blue
    # Flipped:  top blue, bottom red
    assert output_img.getpixel((0, 0)) == (0, 0, 255)
    assert output_img.getpixel((0, 1)) == (255, 0, 0)


def test_flip_uses_default_horizontal_direction(s3_setup):
    app, input_key, bucket = s3_setup

    img = Image.new("RGB", (2, 1))
    img.putpixel((0, 0), (255, 0, 0))  # left red
    img.putpixel((1, 0), (0, 0, 255))  # right blue

    upload_test_image(app, bucket, input_key, img)

    result_json = app.flip(input_s3_key=input_key)
    result = json.loads(result_json)

    assert result["operation"] == "flip"
    assert result["direction"] == "horizontal"

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.getpixel((0, 0)) == (0, 0, 255)
    assert output_img.getpixel((1, 0)) == (255, 0, 0)


def test_flip_invalid_direction_raises_value_error(s3_setup):
    app, input_key, bucket = s3_setup

    img = Image.new("RGB", (2, 1), color="white")
    upload_test_image(app, bucket, input_key, img)

    with pytest.raises(ValueError, match="direction must be either 'horizontal' or 'vertical'"):
        app.flip(
            input_s3_key=input_key,
            direction="diagonal",
        )


def test_flip_fails_when_bucket_is_missing(monkeypatch):
    import app

    monkeypatch.setattr(app, "AWS_S3_BUCKET", None)

    with pytest.raises(RuntimeError, match="AWS_S3_BUCKET environment variable is not set"):
        app.flip(
            input_s3_key="uploads/test-flip.png",
            direction="horizontal",
        )