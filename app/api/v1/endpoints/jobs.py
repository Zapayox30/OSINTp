"""Background job endpoints (submit a deep graph build, poll for the result)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CorrelationEngineDep, JobManagerDep
from app.schemas.graph import GraphQuery
from app.schemas.jobs import JobInfo

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobInfo, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(
    engine: CorrelationEngineDep, manager: JobManagerDep, query: GraphQuery
) -> JobInfo:
    """Queue a correlation-graph build and return immediately with a job id."""

    async def factory() -> dict:
        result = await engine.build(query)
        return result.model_dump(mode="json")

    return manager.submit("graph", factory).info()


@router.get("", response_model=list[JobInfo])
async def list_jobs(manager: JobManagerDep) -> list[JobInfo]:
    return [j.info() for j in manager.list()]


@router.get("/{job_id}", response_model=JobInfo)
async def get_job(manager: JobManagerDep, job_id: str) -> JobInfo:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Job not found: {job_id}")
    return job.info()
