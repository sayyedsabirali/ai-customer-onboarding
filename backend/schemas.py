from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, EmailStr, ConfigDict


class CustomerCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    company_name: Optional[str] = None
    customer_type: str


class CustomerResponse(CustomerCreate):
    id: UUID
    status: str

    model_config = ConfigDict(from_attributes=True)


class OnboardingStateUpdate(BaseModel):
    current_step: Optional[str] = None
    collected_info: Optional[Dict[str, Any]] = None
    pending_items: Optional[Dict[str, Any]] = None
    missing_info: Optional[Dict[str, Any]] = None
    documents_status: Optional[Dict[str, Any]] = None


class DocumentUpload(BaseModel):
    document_type: str


class DocumentResponse(BaseModel):
    id: UUID
    customer_id: UUID
    document_type: Optional[str] = None
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class TaskResponse(BaseModel):
    id: UUID
    customer_id: UUID
    task_type: Optional[str] = None
    task_status: str
    retry_count: int
    max_retries: int

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    customer_id: UUID
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    message: str
    session_id: Optional[str] = None
    current_step: Optional[str] = None