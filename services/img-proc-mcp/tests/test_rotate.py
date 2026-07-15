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

        input_key = "uploads/test-rotate.png"

        # Non-square image so rotation effect is easy to verify
        img = Image.new("RGB", (30, 10), color="white")
        upload_test_image(app, bucket, input_key, img)

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


def test_rotate_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.rotate(
        input_s3_key=input_key,
        angle=90.0,
        expand=True,
    )
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "rotate"
    assert result["angle"] == 90.0
    assert result["expand"] is True
    assert result["output_s3_key"].startswith("processed/rotate/")
    assert result["output_s3_key"].endswith(".png")

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    # Original: 30x10
    # Rotated 90 degrees with expand=True => 10x30
    assert output_img.size == (10, 30)
    assert output_img.format == "PNG"


def test_rotate_with_expand_false_keeps_same_canvas_size(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.rotate(
        input_s3_key=input_key,
        angle=90.0,
        expand=False,
    )
    result = json.loads(result_json)

    assert result["operation"] == "rotate"
    assert result["angle"] == 90.0
    assert result["expand"] is False

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    # With expand=False, PIL keeps the original canvas size
    assert output_img.size == (30, 10)
    assert output_img.format == "PNG"


def test_rotate_zero_degrees_keeps_same_size(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.rotate(
        input_s3_key=input_key,
        angle=0.0,
        expand=True,
    )
    result = json.loads(result_json)

    assert result["operation"] == "rotate"
    assert result["angle"] == 0.0
    assert result["expand"] is True

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (30, 10)
    assert output_img.format == "PNG"


def test_rotate_180_degrees_keeps_same_size(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.rotate(
        input_s3_key=input_key,
        angle=180.0,
        expand=True,
    )
    result = json.loads(result_json)

    assert result["operation"] == "rotate"
    assert result["angle"] == 180.0
    assert result["expand"] is True

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (30, 10)
    assert output_img.format == "PNG"


def test_rotate_fails_when_bucket_is_missing(monkeypatch):
    import app

    monkeypatch.setattr(app, "AWS_S3_BUCKET", None)

    with pytest.raises(RuntimeError, match="AWS_S3_BUCKET environment variable is not set"):
        app.rotate(
            input_s3_key="uploads/test-rotate.png",
            angle=90.0,
            expand=True,
        )