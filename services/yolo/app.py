from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse, Response
from prometheus_fastapi_instrumentator import Instrumentator
from ultralytics import YOLO
from PIL import Image
import logging
import os
import uuid
import shutil
import time
import signal
import sys
from sqlalchemy.orm import joinedload
import boto3
from pydantic import BaseModel

from db import init_db, get_db
from models import PredictionSession, DetectionObject
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")

s3_client = boto3.client("s3", region_name=AWS_REGION)

# Disable GPU usage
import torch
torch.cuda.is_available = lambda: False

app = FastAPI()

@app.on_event("startup")
def startup_event():
    init_db()

@app.on_event("shutdown")
def shutdown_event():
    print("Yolo service is shutting down gracefully", flush=True)
    logger.info("Yolo service is shutting down gracefully")

is_shutting_down = False


def handle_sigterm(signum, frame):
    global is_shutting_down
    is_shutting_down = True

    logger.info("Received SIGTERM. Shutting down gracefully...")

    # simulate cleanup (DB close, etc.)
    logger.info("Cleanup done. Exiting.")

    sys.exit(0)


signal.signal(signal.SIGTERM, handle_sigterm)

## ready end point 
@app.get("/ready")
def ready():
    if is_shutting_down:
        raise HTTPException(status_code=503, detail="Service is shutting down")

    return {"status": "ready"}

@app.get("/ready2")
def ready2():
    if is_shutting_down:
        raise HTTPException(status_code=503, detail="Service is shutting down")

    return {"status": "ready2"}


# Expose /metrics endpoint with default process metrics + FastAPI HTTP metrics
Instrumentator().instrument(app).expose(app)

# Confidence threshold for object detection (0.0 - 1.0).
# Detections below this score are discarded.
# Override with: export CONFIDENCE_THRESHOLD=0.7

#########################################################
# _raw_threshold = os.environ.get("CONFIDENCE_THRESHOLD")
# if _raw_threshold is not None:
#     CONFIDENCE_THRESHOLD = float(_raw_threshold)
#     logging.info(f"CONFIDENCE_THRESHOLD set to {CONFIDENCE_THRESHOLD} (from environment)")
# else:
#     CONFIDENCE_THRESHOLD = 0.5
#     logging.info(f"CONFIDENCE_THRESHOLD not set, using default: {CONFIDENCE_THRESHOLD}")
def get_confidence_threshold():
    raw_threshold = os.environ.get("CONFIDENCE_THRESHOLD")

    if raw_threshold is not None:
        threshold = float(raw_threshold)
        logging.info(f"CONFIDENCE_THRESHOLD set to {threshold} (from environment)")
        return threshold

    logging.info("CONFIDENCE_THRESHOLD not set, using default: 0.5")
    return 0.5

CONFIDENCE_THRESHOLD = get_confidence_threshold()
#######################################################

TEMP_DIR = "/tmp/yolo"
os.makedirs(TEMP_DIR, exist_ok=True)

# Download the AI model (tiny model ~6MB)
model = YOLO("yolov8n.pt")


def save_prediction_session(db, uid, original_image, predicted_image):
    prediction_session = PredictionSession(
        uid=uid,
        original_image=original_image,
        predicted_image=predicted_image,
    )
    db.add(prediction_session)
    return prediction_session


def save_detection_object(db, prediction_session, label, score, box):
    detection_object = DetectionObject(
        prediction_uid=prediction_session.uid,
        label=label,
        score=score,
        box=str(box),
    )
    db.add(detection_object)
    return detection_object

class S3PredictRequest(BaseModel):
    image_s3_key: str

@app.post("/predict")
def predict(request: S3PredictRequest, db=Depends(get_db)):
    """
    Predict objects in an image
    """
    start_time = time.time()
    if not AWS_S3_BUCKET:
        raise HTTPException(status_code=500, detail="AWS_S3_BUCKET is not configured")

    image_s3_key = request.image_s3_key
    ext = os.path.splitext(image_s3_key)[1] or ".jpg"

    uid = str(uuid.uuid4())
    original_path = os.path.join(TEMP_DIR, f"{uid}_original{ext}")
    predicted_path = os.path.join(TEMP_DIR, f"{uid}_predicted{ext}")

    s3_client.download_file(AWS_S3_BUCKET, image_s3_key, original_path)

    results = model(original_path, device="cpu", conf=CONFIDENCE_THRESHOLD)

    annotated_frame = results[0].plot()  # NumPy image with boxes
    annotated_image = Image.fromarray(annotated_frame)
    annotated_image.save(predicted_path)
    if "/original/" in image_s3_key:
        predicted_s3_key = image_s3_key.replace("/original/", "/predicted/")
    else:
        predicted_s3_key = f"predictions/{uid}/predicted{ext}"

    s3_client.upload_file(
        predicted_path,
        AWS_S3_BUCKET,
        predicted_s3_key,
        ExtraArgs={"ContentType": "image/jpeg"},
    )

    prediction_session = save_prediction_session(db, uid, image_s3_key, predicted_s3_key)

    detected_labels = []
    for box in results[0].boxes:
        label_idx = int(box.cls[0].item())
        label = model.names[label_idx]
        score = float(box.conf[0])
        bbox = box.xyxy[0].tolist()
        save_detection_object(db, prediction_session, label, score, bbox)
        detected_labels.append(label)

    db.commit()

    for path in (original_path, predicted_path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    processing_time = round(time.time() - start_time, 2)

    return {
        "prediction_uid": uid,
        "detection_count": len(results[0].boxes),
        "labels": detected_labels,
        "time_took": processing_time,
        "original_image_s3_key": image_s3_key,
        "predicted_image_s3_key": predicted_s3_key,
    }


@app.get("/prediction/{uid}")
def get_prediction_by_uid(uid: str, db=Depends(get_db)):
    """
    Get prediction session by uid with all detected objects
    """
    session_obj = (
        db.query(PredictionSession)
        .options(joinedload(PredictionSession.detection_objects))
        .filter(PredictionSession.uid == uid)
        .first()
    )

    if not session_obj:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return {
        "uid": session_obj.uid,
        "timestamp": session_obj.timestamp,
        "original_image": session_obj.original_image,
        "predicted_image": session_obj.predicted_image,
        "detection_objects": [
            {
                "id": obj.id,
                "label": obj.label,
                "score": obj.score,
                "box": obj.box,
            }
            for obj in session_obj.detection_objects
        ],
    }


@app.get("/prediction/{uid}/image")
def get_prediction_image(uid: str, db=Depends(get_db)):
    session_obj = db.query(PredictionSession).filter(PredictionSession.uid == uid).first()

    if not session_obj:
        raise HTTPException(status_code=404, detail="Image not found")

    try:
        obj = s3_client.get_object(
            Bucket=AWS_S3_BUCKET,
            Key=session_obj.predicted_image,
        )
        return Response(content=obj["Body"].read(), media_type="image/jpeg")
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")

@app.get("/health")
def health():
    """
    Health check endpoint
    """
    return {"status": "ok"}

@app.get("/version")
def get_version():
    return {
        "service": "yolo",
        "version": "1.0.0",
        "environment": os.getenv("APP_ENV", "unknown")
    }

@app.get("/ping")
def ping():
    return {"message": "pong"}

@app.get("/predictions/label/")
def get_predictions_by_empty_label():
    raise HTTPException(status_code=400, detail="Label cannot be empty")


@app.get("/predictions/label/{label}")
def get_predictions_by_label(label: str, db=Depends(get_db)):
    """
    Return all prediction sessions that contain at least one detected object
    with the given label.
    """

    sessions = (
        db.query(PredictionSession)
        .join(PredictionSession.detection_objects)
        .options(joinedload(PredictionSession.detection_objects))
        .filter(DetectionObject.label == label)
        .distinct()
        .all()
    )

    return [
        {
            "uid": session_obj.uid,
            "timestamp": session_obj.timestamp,
            "detection_objects": [
                {
                    "id": obj.id,
                    "label": obj.label,
                    "score": obj.score,
                    "box": obj.box,
                }
                for obj in session_obj.detection_objects
                if obj.label == label
            ],
        }
        for session_obj in sessions
    ]
    
@app.get("/predictions/score/")
def get_predictions_by_empty_score():
    raise HTTPException(status_code=400, detail="score cannot be empty")

@app.get("/predictions/score/{min_score}")
def get_predictions_by_score(min_score: float, db=Depends(get_db)):
    """
    Return all detection objects whose confidence score is greater than
    or equal to min_score.
    """
    if min_score < 0.0 or min_score > 1.0:
        raise HTTPException(
            status_code=400,
            detail="min_score must be between 0.0 and 1.0"
        )

    objects = db.query(DetectionObject).filter(DetectionObject.score >= min_score).all()

    return [
        {
            "id": obj.id,
            "prediction_uid": obj.prediction_uid,
            "label": obj.label,
            "score": obj.score,
            "box": obj.box,
        }
        for obj in objects
    ]

if __name__ == "__main__": #pragma: no cover
    import uvicorn

    init_db()
    
    uvicorn.run(app, host="0.0.0.0", port=8080)
