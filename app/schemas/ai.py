import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ContentType = Literal["video", "image_text", "article"]
EvidenceLevel = Literal["metadata", "body", "subtitle", "ocr", "asr"]


class Category(BaseModel):
    category_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    parent_id: str | None = Field(default=None, max_length=64)
    level: int = Field(ge=1, le=3)


class ClassificationItem(BaseModel):
    item_id: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=30)
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(default="", max_length=100)
    content_type: ContentType
    source_text: str = Field(default="", max_length=300)
    evidence_level: EvidenceLevel


class ClassificationRequest(BaseModel):
    phase: Literal["candidate", "assign"] = "candidate"
    taxonomy: list[Category] | None = None
    items: list[ClassificationItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_request(self) -> "ClassificationRequest":
        _validate_unique_item_ids([item.item_id for item in self.items])
        if self.taxonomy is not None:
            _validate_categories(self.taxonomy)
        if self.phase == "assign" and self.taxonomy is None:
            raise ValueError("最终分配必须提供分类目录")
        return self


class CategoryAssignment(BaseModel):
    item_id: str
    category_id: str


class ClassificationCandidateOutput(BaseModel):
    categories: list[Category] = Field(min_length=1, max_length=100)


class ClassificationAssignmentOutput(BaseModel):
    assignments: list[CategoryAssignment] = Field(min_length=1, max_length=100)


class Usage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ClassificationResponse(BaseModel):
    categories: list[Category] = Field(min_length=1, max_length=100)
    assignments: list[CategoryAssignment] = Field(default_factory=list, max_length=100)
    phase: Literal["candidate", "assign"]
    mode: Literal["initial", "incremental"]
    provider: str
    model: str
    prompt_version: str
    request_id: uuid.UUID
    usage: Usage


class TaxonomyMergeRequest(BaseModel):
    base_taxonomy: list[Category] | None = None
    candidates: list[list[Category]] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_request(self) -> "TaxonomyMergeRequest":
        if self.base_taxonomy is not None:
            _validate_categories(self.base_taxonomy)
        for candidate in self.candidates:
            _validate_categories(candidate)
        return self


class TaxonomyMergeOutput(BaseModel):
    categories: list[Category] = Field(min_length=1, max_length=100)


class TaxonomyMergeResponse(TaxonomyMergeOutput):
    provider: str
    model: str
    prompt_version: str
    request_id: uuid.UUID
    usage: Usage


class OrganizationJobCreate(BaseModel):
    mode: Literal["all", "selected"]
    organization_instruction: str = Field(default="", max_length=300)
    classification_item_ids: list[str]
    enrichment_item_ids: list[str] = Field(min_length=1)

    @field_validator("organization_instruction", mode="before")
    @classmethod
    def normalize_organization_instruction(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_request(self) -> "OrganizationJobCreate":
        _validate_unique_item_ids(self.classification_item_ids)
        _validate_unique_item_ids(self.enrichment_item_ids)
        if any(not item_id or len(item_id) > 160 for item_id in self.classification_item_ids + self.enrichment_item_ids):
            raise ValueError("收藏 ID 长度无效")
        return self


class OrganizationJobResponse(BaseModel):
    job_id: uuid.UUID
    credits: int = 10
    classification_call_limit: int
    enrichment_call_limit: int


class EnrichmentItem(BaseModel):
    item_id: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=30)
    title: str = Field(min_length=1, max_length=200)
    author: str = Field(default="", max_length=100)
    content_type: ContentType
    source_text: str = Field(default="", max_length=300)
    evidence_level: EvidenceLevel
    assigned_category_id: str = Field(min_length=1, max_length=64)
    content_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class EnrichmentRequest(BaseModel):
    taxonomy: list[Category] = Field(min_length=1, max_length=100)
    items: list[EnrichmentItem] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_request(self) -> "EnrichmentRequest":
        _validate_categories(self.taxonomy)
        _validate_unique_item_ids([item.item_id for item in self.items])
        category_ids = {category.category_id for category in self.taxonomy}
        if any(item.assigned_category_id not in category_ids for item in self.items):
            raise ValueError("assigned_category_id 必须存在于分类目录")
        return self


class EnrichedItem(BaseModel):
    item_id: str
    summary: str = Field(min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=10)
    category_id: str

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        normalized = [tag.strip() for tag in tags]
        if any(not tag or len(tag) > 30 for tag in normalized):
            raise ValueError("标签长度必须为 1～30")
        if len({tag.casefold() for tag in normalized}) != len(normalized):
            raise ValueError("标签不得重复")
        return normalized


class EnrichmentFailure(BaseModel):
    item_id: str
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=200)


class EnrichmentModelOutput(BaseModel):
    items: list[EnrichedItem] = Field(default_factory=list)
    failures: list[EnrichmentFailure] = Field(default_factory=list)


class EnrichedItemResponse(EnrichedItem):
    content_fingerprint: str
    provider: str
    model: str
    prompt_version: str
    request_id: uuid.UUID


class EnrichmentResponse(BaseModel):
    items: list[EnrichedItemResponse]
    failures: list[EnrichmentFailure]
    provider: str
    model: str
    prompt_version: str
    request_id: uuid.UUID
    usage: Usage


def validate_classification_output(
    request: ClassificationRequest,
    output: ClassificationCandidateOutput | ClassificationAssignmentOutput,
) -> None:
    if request.phase == "candidate":
        if not isinstance(output, ClassificationCandidateOutput):
            raise ValueError("候选分类阶段必须返回分类目录")
        _validate_categories(output.categories)
    else:
        if not isinstance(output, ClassificationAssignmentOutput):
            raise ValueError("最终归类阶段必须返回收藏映射")
        expected = [item.item_id for item in request.items]
        actual = [assignment.item_id for assignment in output.assignments]
        _validate_exact_item_ids(expected, actual)
        category_ids = {category.category_id for category in request.taxonomy or []}
        if any(assignment.category_id not in category_ids for assignment in output.assignments):
            raise ValueError("分类结果引用了不存在的分类")

    if request.phase == "candidate" and request.taxonomy is not None:
        existing = {category.category_id: category for category in request.taxonomy}
        returned = {category.category_id: category for category in output.categories}
        if any(
            category_id not in returned or returned[category_id] != category
            for category_id, category in existing.items()
        ):
            raise ValueError("增量分类不得删除或修改现有分类")


def validate_taxonomy_merge_output(
    request: TaxonomyMergeRequest, output: TaxonomyMergeOutput
) -> None:
    _validate_categories(output.categories)
    if request.base_taxonomy is None:
        return
    existing = {category.category_id: category for category in request.base_taxonomy}
    returned = {category.category_id: category for category in output.categories}
    if any(returned.get(category_id) != category for category_id, category in existing.items()):
        raise ValueError("目录合并不得删除或修改现有分类")


def validate_enrichment_output(
    request: EnrichmentRequest, output: EnrichmentModelOutput
) -> None:
    expected = [item.item_id for item in request.items]
    actual = [item.item_id for item in output.items] + [item.item_id for item in output.failures]
    _validate_exact_item_ids(expected, actual)
    request_items = {item.item_id: item for item in request.items}
    for item in output.items:
        if item.category_id != request_items[item.item_id].assigned_category_id:
            raise ValueError("整理阶段不得修改分类")


def _validate_unique_item_ids(item_ids: list[str]) -> None:
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("item_id 不得重复")


def _validate_exact_item_ids(expected: list[str], actual: list[str]) -> None:
    _validate_unique_item_ids(actual)
    if set(expected) != set(actual):
        raise ValueError("模型结果必须完整覆盖输入 item_id，且不得增加额外 ID")


def _validate_categories(categories: list[Category]) -> None:
    by_id = {category.category_id: category for category in categories}
    if len(by_id) != len(categories):
        raise ValueError("category_id 不得重复")

    sibling_names: set[tuple[str | None, str]] = set()
    for category in categories:
        if category.parent_id == category.category_id:
            raise ValueError("分类不能以自身作为父级")
        if category.parent_id is not None and category.parent_id not in by_id:
            raise ValueError("父分类不存在")
        sibling = (category.parent_id, category.name.strip().casefold())
        if sibling in sibling_names:
            raise ValueError("同级分类名称不得重复")
        sibling_names.add(sibling)

    for category in categories:
        depth = 1
        seen = {category.category_id}
        parent_id = category.parent_id
        while parent_id is not None:
            if parent_id in seen:
                raise ValueError("分类目录不能包含环")
            seen.add(parent_id)
            depth += 1
            parent_id = by_id[parent_id].parent_id
        if depth != category.level or depth > 3:
            raise ValueError("分类层级必须与父子关系一致，且最多三层")
