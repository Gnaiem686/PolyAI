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

        img = Image.new("RGB", (100, 80), color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        input_key = "uploads/test-crop.png"

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


def test_crop_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.crop(
        input_s3_key=input_key,
        left=10,
        top=20,
        right=60,
        bottom=50,
    )
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "crop"
    assert result["left"] == 10
    assert result["top"] == 20
    assert result["right"] == 60
    assert result["bottom"] == 50

    assert result["output_s3_key"].startswith("processed/crop/")
    assert result["output_s3_key"].endswith(".png")

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (50, 30)
    assert output_img.format == "PNG"


def test_crop_whole_image_uploads_full_size_image(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.crop(
        input_s3_key=input_key,
        left=0,
        top=0,
        right=100,
        bottom=80,
    )
    result = json.loads(result_json)

    assert result["operation"] == "crop"
    assert result["left"] == 0
    assert result["top"] == 0
    assert result["right"] == 100
    assert result["bottom"] == 80

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (100, 80)
    assert output_img.format == "PNG"


def test_crop_clamps_negative_coordinates(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.crop(
        input_s3_key=input_key,
        left=-10,
        top=-20,
        right=50,
        bottom=40,
    )
    result = json.loads(result_json)

    assert result["operation"] == "crop"
    assert result["left"] == 0
    assert result["top"] == 0
    assert result["right"] == 50
    assert result["bottom"] == 40

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (50, 40)
    assert output_img.format == "PNG"


def test_crop_clamps_outside_image_bounds(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.crop(
        input_s3_key=input_key,
        left=10,
        top=20,
        right=200,
        bottom=200,
    )
    result = json.loads(result_json)

    assert result["operation"] == "crop"
    assert result["left"] == 10
    assert result["top"] == 20
    assert result["right"] == 100
    assert result["bottom"] == 80

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (90, 60)
    assert output_img.format == "PNG"


def test_crop_invalid_box_order_is_clamped_to_minimum_region(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.crop(
        input_s3_key=input_key,
        left=50,
        top=20,
        right=10,
        bottom=10,
    )
    result = json.loads(result_json)

    assert result["operation"] == "crop"

    assert result["left"] == 50
    assert result["top"] == 20
    assert result["right"] == 51
    assert result["bottom"] == 21

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (1, 1)
    assert output_img.format == "PNG"


def test_crop_fails_when_bucket_is_missing(monkeypatch):
    import app

    monkeypatch.setattr(app, "AWS_S3_BUCKET", None)

    with pytest.raises(RuntimeError, match="AWS_S3_BUCKET environment variable is not set"):
        app.crop(
            input_s3_key="uploads/test-crop.png",
            left=0,
            top=0,
            right=10,
            bottom=10,
        )