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


def test_blur_uploads_processed_image_to_s3(s3_setup):
    app, input_key, bucket = s3_setup

    result_json = app.blur(input_s3_key=input_key, radius=2.0)
    result = json.loads(result_json)

    assert result["input_s3_key"] == input_key
    assert result["operation"] == "blur"
    assert result["radius"] == 2.0
    assert result["output_s3_key"].startswith("processed/blur/")
    assert result["output_s3_key"].endswith(".png")

    response = app.s3_client.get_object(
        Bucket=bucket,
        Key=result["output_s3_key"],
    )

    output_bytes = response["Body"].read()
    output_img = Image.open(io.BytesIO(output_bytes))

    assert output_img.size == (20, 20)
    assert output_img.format == "PNG"