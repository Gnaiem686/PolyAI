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
        monkeypatch.setattr(app, "s3_client", boto3.client("s3", region_name="us-east-1"))

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

    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=result["output_s3_key"],
    )

    output_bytes = response["Body"].read()
    output_img = Image.open(io.BytesIO(output_bytes))

    # right - left = 50, bottom - top = 30
    assert output_img.size == (50, 30)
    assert output_img.format == "PNG"


def test_crop_invalid_negative_coordinates_raise_value_error(s3_setup):
    app, input_key, _ = s3_setup

    with pytest.raises(ValueError, match="left and top must be non-negative"):
        app.crop(
            input_s3_key=input_key,
            left=-1,
            top=0,
            right=10,
            bottom=10,
        )


def test_crop_invalid_box_order_raises_value_error(s3_setup):
    app, input_key, _ = s3_setup

    with pytest.raises(
        ValueError,
        match="right must be greater than left and bottom must be greater than top",
    ):
        app.crop(
            input_s3_key=input_key,
            left=50,
            top=20,
            right=10,
            bottom=50,
        )


def test_crop_outside_image_bounds_raises_value_error(s3_setup):
    app, input_key, _ = s3_setup

    with pytest.raises(ValueError, match="crop box must be inside image bounds"):
        app.crop(
            input_s3_key=input_key,
            left=10,
            top=20,
            right=200,
            bottom=50,
        )