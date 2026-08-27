import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AIJob, AIRequest, AppToken


class AIRequestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, token_id: uuid.UUID, operation: str, key: str) -> AIRequest | None:
        return self.session.scalar(
            select(AIRequest).where(
                AIRequest.token_id == token_id,
                AIRequest.operation == operation,
                AIRequest.idempotency_key == key,
            )
        )

    def lock_token(self, token_id: uuid.UUID) -> AppToken | None:
        return self.session.scalar(
            select(AppToken).where(AppToken.id == token_id).with_for_update()
        )

    def add(self, request: AIRequest) -> None:
        self.session.add(request)

    def get_job(self, job_id: uuid.UUID, token_id: uuid.UUID) -> AIJob | None:
        return self.session.scalar(
            select(AIJob).where(AIJob.id == job_id, AIJob.token_id == token_id)
        )

    def get_job_by_key(self, token_id: uuid.UUID, key: str) -> AIJob | None:
        return self.session.scalar(
            select(AIJob).where(
                AIJob.token_id == token_id, AIJob.idempotency_key == key
            )
        )

    def add_job(self, job: AIJob) -> None:
        self.session.add(job)

    def count_job_requests(self, job_id: uuid.UUID, operation: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(AIRequest.id)).where(
                    AIRequest.job_id == job_id, AIRequest.operation == operation
                )
            )
            or 0
        )
