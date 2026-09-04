print("[LOAD] backend/database/models.py is being imported")
from sqlalchemy import Column, String, Text, BigInteger, Integer, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .connection import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(20))
    company_name = Column(String(255))
    customer_type = Column(String(50), nullable=False)
    status = Column(String(50), default="onboarding_started")
    sla_hours = Column(Integer, default=24)
    sla_deadline = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class OnboardingState(Base):
    __tablename__ = "onboarding_state"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False
    )
    session_id = Column(String(255))
    current_step = Column(String(100))
    collected_info = Column(JSONB)
    pending_items = Column(JSONB)
    missing_info = Column(JSONB)
    documents_status = Column(JSONB)
    last_interaction_at = Column(DateTime, server_default=func.now())
    follow_up_count = Column(Integer, default=0)
    last_follow_up_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE")
    )
    document_type = Column(String(100))
    file_url = Column(String(500))
    file_name = Column(String(255))
    file_size = Column(BigInteger)
    status = Column(String(50), default="pending")
    verification_notes = Column(Text)
    uploaded_at = Column(DateTime, server_default=func.now())
    verified_at = Column(DateTime)


class OnboardingTask(Base):
    __tablename__ = "onboarding_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE")
    )
    task_type = Column(String(100))
    task_status = Column(String(50), default="pending")
    api_endpoint = Column(String(255))
    api_payload = Column(JSONB)
    api_response = Column(JSONB)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)


class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False
    )
    session_id = Column(String(255), nullable=False)
    reason = Column(Text, nullable=False)
    recommended_action = Column(Text)
    context = Column(JSONB)
    status = Column(String(50), default="pending")  # pending, resolved, rejected
    resolution_notes = Column(Text)
    resolved_by = Column(String(100))
    created_at = Column(DateTime, server_default=func.now())
    resolved_at = Column(DateTime)

    customer = relationship("Customer")