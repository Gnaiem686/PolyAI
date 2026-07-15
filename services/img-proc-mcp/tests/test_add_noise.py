# services/img-proc-mcp/tests/test_add_noise.py

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
        monkeypatch.setattr(
            app,
            "s3_client",
            boto3.client("s3", region_name="us-east-1"),
        )

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


def load_s3_image(app, bucket: str, key: str) -> Image.Image:
    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=key,
    )
    output_bytes = response["Body"].read()
    return Image.open(io.BytesIO(output_bytes))


def test_add_noise_whole_image_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.add_noise(
        input_s3_key=input_key,
        amount=0.25,
    )
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "add_noise"
    assert result["amount"] == 0.25

    assert result["left"] == 0
    assert result["top"] == 0
    assert result["right"] == 20
    assert result["bottom"] == 20

    assert result["output_s3_key"].startswith("processed/noise/")
    assert result["output_s3_key"].endswith(".png")

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (20, 20)
    assert output_img.format == "PNG"

    output_arr = np.array(output_img)

    black_pixels = np.sum(np.all(output_arr == [0, 0, 0], axis=-1))
    white_pixels = np.sum(np.all(output_arr == [255, 255, 255], axis=-1))

    assert black_pixels + white_pixels > 0


def test_add_noise_region_keeps_full_image_size_and_only_changes_region(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.add_noise(
        input_s3_key=input_key,
        amount=0.25,
        left=5,
        top=5,
        right=15,
        bottom=15,
    )
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "add_noise"
    assert result["amount"] == 0.25

    assert result["left"] == 5
    assert result["top"] == 5
    assert result["right"] == 15
    assert result["bottom"] == 15

    assert result["output_s3_key"].startswith("processed/noise/")
    assert result["output_s3_key"].endswith(".png")

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )

    assert output_img.size == (20, 20)
    assert output_img.format == "PNG"

    output_arr = np.array(output_img)

    # Outside region should stay gray
    outside_mask = np.ones((20, 20), dtype=bool)
    outside_mask[5:15, 5:15] = False
    outside_pixels = output_arr[outside_mask]

    assert np.all(outside_pixels == [128, 128, 128])

    # Inside region should contain at least some noisy pixels
    region_pixels = output_arr[5:15, 5:15]
    black_pixels = np.sum(np.all(region_pixels == [0, 0, 0], axis=-1))
    white_pixels = np.sum(np.all(region_pixels == [255, 255, 255], axis=-1))

    assert black_pixels + white_pixels > 0


def test_add_noise_clamps_out_of_bounds_coordinates(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.add_noise(
        input_s3_key=input_key,
        amount=0.25,
        left=-10,
        top=-5,
        right=100,
        bottom=50,
    )
    result = json.loads(result_json)

    assert result["operation"] == "add_noise"
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


def test_add_noise_zero_amount_keeps_image_unchanged(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.add_noise(
        input_s3_key=input_key,
        amount=0.0,
    )
    result = json.loads(result_json)

    output_img = load_s3_image(
        app=app,
        bucket=bucket,
        key=result["output_s3_key"],
    )
    output_arr = np.array(output_img)

    assert output_img.size == (20, 20)
    assert output_img.format == "PNG"
    assert np.all(output_arr == [128, 128, 128])


def test_add_noise_uses_default_amount(s3_setup):
    app, input_key, _ = s3_setup

    result_json = app.add_noise(input_s3_key=input_key)
    result = json.loads(result_json)

    assert result["operation"] == "add_noise"
    assert result["amount"] == 0.05


def test_add_noise_invalid_amount_raises_value_error(s3_setup):
    app, input_key, _ = s3_setup

    with pytest.raises(ValueError, match="amount must be between 0 and 1"):
        app.add_noise(input_s3_key=input_key, amount=-0.1)

    with pytest.raises(ValueError, match="amount must be between 0 and 1"):
        app.add_noise(input_s3_key=input_key, amount=1.5)


def test_add_noise_fails_when_bucket_is_missing(monkeypatch):
    import app

    monkeypatch.setattr(app, "AWS_S3_BUCKET", None)

    with pytest.raises(RuntimeError, match="AWS_S3_BUCKET environment variable is not set"):
        app.add_noise(input_s3_key="uploads/test-noise.png", amount=0.25)