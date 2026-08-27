import uuid

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.ai import Usage


class SearchDocumentInput(BaseModel):
    item_id: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=30)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=10)
    category_path: list[str] = Field(default_factory=list, max_length=3)
    content_fingerprint: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        normalized = [tag.strip() for tag in tags]
        if any(not tag or len(tag) > 30 for tag in normalized):
            raise ValueError("标签长度必须为 1～30")
        return normalized

    @field_validator("category_path")
    @classmethod
    def validate_category_path(cls, path: list[str]) -> list[str]:
        normalized = [name.strip() for name in path]
        if any(not name or len(name) > 60 for name in normalized):
            raise ValueError("分类路径名称长度必须为 1～60")
        return normalized


class SearchIndexReplace(BaseModel):
    items: list[SearchDocumentInput] = Field(max_length=5000)

    @model_validator(mode="after")
    def validate_unique_items(self) -> "SearchIndexReplace":
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("item_id 不得重复")
        return self


class SearchIndexResponse(BaseModel):
    indexed: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    source: str | None = Field(default=None, min_length=1, max_length=30)
    limit: int = Field(default=20, ge=1, le=20)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, query: str) -> str:
        return query.strip() if isinstance(query, str) else query


class SearchModelRequest(BaseModel):
    query: str
    documents: list[SearchDocumentInput] = Field(min_length=1, max_length=100)
    limit: int = Field(ge=1, le=20)


class SearchResultItem(BaseModel):
    item_id: str = Field(min_length=1, max_length=160)
    score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=200)


class SearchModelOutput(BaseModel):
    results: list[SearchResultItem] = Field(default_factory=list, max_length=20)


class SearchResponse(SearchModelOutput):
    provider: str
    model: str
    prompt_version: str
    request_id: uuid.UUID
    usage: Usage
    credits: int = 2
