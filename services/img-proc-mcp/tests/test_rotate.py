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

        # Use non-square image so rotation size change is easy to verify.
        img = Image.new("RGB", (30, 10), color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        input_key = "uploads/test-rotate.png"

        app.s3_client.put_object(
            Bucket=bucket,
            Key=input_key,
            Body=buffer.getvalue(),
            ContentType="image/png",
        )

        yield app, input_key, bucket


def test_rotate_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.rotate(input_s3_key=input_key, angle=90.0, expand=True)
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "rotate"
    assert result["angle"] == 90.0
    assert result["expand"] is True
    assert result["output_s3_key"].startswith("processed/rotate/")
    assert result["output_s3_key"].endswith(".png")

    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=result["output_s3_key"],
    )

    output_bytes = response["Body"].read()
    output_img = Image.open(io.BytesIO(output_bytes))

    # Original was 30x10. Rotating 90 degrees with expand=True gives 10x30.
    assert output_img.size == (10, 30)
    assert output_img.format == "PNG"