"""Jobs API router — exposes deploy job status."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_bearer_token
from app.database import get_db
from app.models import DeployJob
from app.schemas import DeployJobOut

log = logging.getLogger(__name__)
router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_bearer_token)],
)


@router.get("/{job_id}", response_model=DeployJobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(DeployJob).filter(DeployJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("", response_model=list[DeployJobOut])
def list_jobs(db: Session = Depends(get_db)):
    return db.query(DeployJob).order_by(DeployJob.id.desc()).limit(100).all()
