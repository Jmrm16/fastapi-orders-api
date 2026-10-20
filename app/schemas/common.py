from typing import Generic, TypeVar, List
from pydantic import BaseModel

T = TypeVar("T")

class PageMetadata(BaseModel):
    page: int
    per_page: int
    total_items: int
    total_pages: int

class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    metadata: PageMetadata
