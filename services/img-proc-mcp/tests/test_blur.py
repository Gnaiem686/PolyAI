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

        img = Image.new("RGB", (20, 20), color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        input_key = "uploads/test.png"

        app.s3_client.put_object(
            Bucket=bucket,
            Key=input_key,
            Body=buffer.getvalue(),
            ContentType="image/png",
        )

        yield app, input_key, bucket


def load_s3_image(app, bucket: str, key: str) -> Image.Image:
    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=key,
    )

    output_bytes = response["Body"].read()
    return Image.open(io.BytesIO(output_bytes))


def test_blur_whole_image_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.blur(
        input_s3_key=input_key,
        radius=2.0,
    )

    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "blur"
    assert result["radius"] == 2.0

    assert result["left"] == 0
    assert result["top"] == 0
    assert result["right"] == 20
    assert result["bottom"] == 20

    assert result["output_s3_key"].startswith("processed/blur/")
    assert result["output_s3_key"].endswith(".png")

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (20, 20)
    assert output_img.format == "PNG"


def test_blur_region_uploads_full_size_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.blur(
        input_s3_key=input_key,
        radius=2.0,
        left=5,
        top=5,
        right=15,
        bottom=15,
    )

    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "blur"
    assert result["radius"] == 2.0

    assert result["left"] == 5
    assert result["top"] == 5
    assert result["right"] == 15
    assert result["bottom"] == 15

    assert result["output_s3_key"].startswith("processed/blur/")
    assert result["output_s3_key"].endswith(".png")

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    # Region blur should keep the original full image size.
    assert output_img.size == (20, 20)
    assert output_img.format == "PNG"


def test_blur_clamps_out_of_bounds_coordinates(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.blur(
        input_s3_key=input_key,
        radius=2.0,
        left=-10,
        top=-5,
        right=100,
        bottom=50,
    )

    result = json.loads(result_json)

    assert result["operation"] == "blur"

    assert result["left"] == 0
    assert result["top"] == 0
    assert result["right"] == 20
    assert result["bottom"] == 20

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (20, 20)
    assert output_img.format == "PNG"


def test_blur_uses_default_radius(s3_setup):
    app, input_key, _ = s3_setup

    result_json = app.blur(input_s3_key=input_key)
    result = json.loads(result_json)

    assert result["operation"] == "blur"
    assert result["radius"] == 2.0


def test_blur_fails_when_bucket_is_missing(monkeypatch):
    import app

    monkeypatch.setattr(app, "AWS_S3_BUCKET", None)

    with pytest.raises(RuntimeError, match="AWS_S3_BUCKET environment variable is not set"):
        app.blur(input_s3_key="uploads/test.png", radius=2.0)