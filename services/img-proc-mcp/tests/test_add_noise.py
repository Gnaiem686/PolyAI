import io
import json
import os

import boto3
import numpy as np
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

        img = Image.new("RGB", (20, 20), color=(128, 128, 128))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        input_key = "uploads/test-noise.png"

        app.s3_client.put_object(
            Bucket=bucket,
            Key=input_key,
            Body=buffer.getvalue(),
            ContentType="image/png",
        )

        yield app, input_key, bucket


def test_add_noise_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.add_noise(input_s3_key=input_key, amount=0.25)
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "add_noise"
    assert result["amount"] == 0.25
    assert result["output_s3_key"].startswith("processed/noise/")
    assert result["output_s3_key"].endswith(".png")

    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=result["output_s3_key"],
    )

    output_bytes = response["Body"].read()
    output_img = Image.open(io.BytesIO(output_bytes))

    assert output_img.size == (20, 20)
    assert output_img.format == "PNG"

    output_arr = np.array(output_img)

    # Original image was all gray. After noise, at least some pixels should be black or white.
    black_pixels = np.sum(np.all(output_arr == [0, 0, 0], axis=-1))
    white_pixels = np.sum(np.all(output_arr == [255, 255, 255], axis=-1))

    assert black_pixels + white_pixels > 0


def test_add_noise_zero_amount_keeps_image_size(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.add_noise(input_s3_key=input_key, amount=0)
    result = json.loads(result_json)

    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=result["output_s3_key"],
    )

    output_img = Image.open(io.BytesIO(response["Body"].read()))

    assert output_img.size == (20, 20)
    assert output_img.format == "PNG"


def test_add_noise_invalid_amount_raises_value_error(s3_setup):
    app, input_key, _ = s3_setup

    with pytest.raises(ValueError, match="amount must be between 0 and 1"):
        app.add_noise(input_s3_key=input_key, amount=-0.1)

    with pytest.raises(ValueError, match="amount must be between 0 and 1"):
        app.add_noise(input_s3_key=input_key, amount=1.5)