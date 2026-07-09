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

        input_key = "uploads/test-resize.png"

        img = Image.new("RGB", (40, 20), color="white")
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


def test_resize_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.resize(
        input_s3_key=input_key,
        width=10,
        height=5,
    )
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "resize"
    assert result["width"] == 10
    assert result["height"] == 5
    assert result["output_s3_key"].startswith("processed/resize/")
    assert result["output_s3_key"].endswith(".png")

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (10, 5)
    assert output_img.format == "PNG"


def test_resize_can_make_image_larger(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.resize(
        input_s3_key=input_key,
        width=80,
        height=40,
    )
    result = json.loads(result_json)

    assert result["operation"] == "resize"
    assert result["width"] == 80
    assert result["height"] == 40

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (80, 40)
    assert output_img.format == "PNG"


def test_resize_same_size_keeps_same_dimensions(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.resize(
        input_s3_key=input_key,
        width=40,
        height=20,
    )
    result = json.loads(result_json)

    assert result["operation"] == "resize"
    assert result["width"] == 40
    assert result["height"] == 20

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (40, 20)
    assert output_img.format == "PNG"


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (0, 5),
        (10, 0),
        (-1, 5),
        (10, -1),
    ],
)
def test_resize_invalid_dimensions_raise_value_error(s3_setup, width, height):
    app, input_key, _ = s3_setup

    with pytest.raises(ValueError, match="width and height must be positive integers"):
        app.resize(
            input_s3_key=input_key,
            width=width,
            height=height,
        )


def test_resize_fails_when_bucket_is_missing(monkeypatch):
    import app

    monkeypatch.setattr(app, "AWS_S3_BUCKET", None)

    with pytest.raises(RuntimeError, match="AWS_S3_BUCKET environment variable is not set"):
        app.resize(
            input_s3_key="uploads/test-resize.png",
            width=10,
            height=5,
        )