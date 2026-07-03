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

        # Create a tiny image with distinct left/right colors to verify horizontal flip.
        img = Image.new("RGB", (2, 1))
        img.putpixel((0, 0), (255, 0, 0))  # left pixel red
        img.putpixel((1, 0), (0, 0, 255))  # right pixel blue

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        input_key = "uploads/test-flip.png"

        app.s3_client.put_object(
            Bucket=bucket,
            Key=input_key,
            Body=buffer.getvalue(),
            ContentType="image/png",
        )

        yield app, input_key, bucket


def test_flip_horizontal_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.flip(input_s3_key=input_key, direction="horizontal")
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "flip"
    assert result["direction"] == "horizontal"
    assert result["output_s3_key"].startswith("processed/flip/")
    assert result["output_s3_key"].endswith(".png")

    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=result["output_s3_key"],
    )

    output_bytes = response["Body"].read()
    output_img = Image.open(io.BytesIO(output_bytes))

    assert output_img.size == (2, 1)
    assert output_img.format == "PNG"

    # After horizontal flip:
    # original left red, right blue
    # flipped left blue, right red
    assert output_img.getpixel((0, 0)) == (0, 0, 255)
    assert output_img.getpixel((1, 0)) == (255, 0, 0)


def test_flip_invalid_direction_raises_value_error(s3_setup):
    app, input_key, _ = s3_setup

    with pytest.raises(ValueError, match="direction must be either 'horizontal' or 'vertical'"):
        app.flip(input_s3_key=input_key, direction="diagonal")

def test_flip_vertical_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    # Replace the uploaded image with a 1x2 image:
    # top pixel red, bottom pixel blue
    img = Image.new("RGB", (1, 2))
    img.putpixel((0, 0), (255, 0, 0))  # top pixel red
    img.putpixel((0, 1), (0, 0, 255))  # bottom pixel blue

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    app.s3_client.put_object(
        Bucket=bucket,
        Key=input_key,
        Body=buffer.getvalue(),
        ContentType="image/png",
    )

    result_json = app.flip(input_s3_key=input_key, direction="vertical")
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "flip"
    assert result["direction"] == "vertical"
    assert result["output_s3_key"].startswith("processed/flip/")
    assert result["output_s3_key"].endswith(".png")

    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=result["output_s3_key"],
    )

    output_bytes = response["Body"].read()
    output_img = Image.open(io.BytesIO(output_bytes))

    assert output_img.size == (1, 2)
    assert output_img.format == "PNG"

    # After vertical flip:
    # original top red, bottom blue
    # flipped top blue, bottom red
    assert output_img.getpixel((0, 0)) == (0, 0, 255)
    assert output_img.getpixel((0, 1)) == (255, 0, 0)