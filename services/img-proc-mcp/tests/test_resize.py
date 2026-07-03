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

        img = Image.new("RGB", (40, 20), color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        input_key = "uploads/test-resize.png"

        app.s3_client.put_object(
            Bucket=bucket,
            Key=input_key,
            Body=buffer.getvalue(),
            ContentType="image/png",
        )

        yield app, input_key, bucket


def test_resize_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.resize(input_s3_key=input_key, width=10, height=5)
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "resize"
    assert result["width"] == 10
    assert result["height"] == 5
    assert result["output_s3_key"].startswith("processed/resize/")
    assert result["output_s3_key"].endswith(".png")

    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=result["output_s3_key"],
    )

    output_bytes = response["Body"].read()
    output_img = Image.open(io.BytesIO(output_bytes))

    assert output_img.size == (10, 5)
    assert output_img.format == "PNG"


def test_resize_invalid_dimensions_raise_value_error(s3_setup):
    app, input_key, _ = s3_setup

    with pytest.raises(ValueError, match="width and height must be positive integers"):
        app.resize(input_s3_key=input_key, width=0, height=5)

    with pytest.raises(ValueError, match="width and height must be positive integers"):
        app.resize(input_s3_key=input_key, width=10, height=-1)