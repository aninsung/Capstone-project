from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

ID = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Income = Literal["LE_50", "GT_50_LE_75", "GT_75_LE_100", "GT_100_LE_120", "GT_120_LE_150", "GT_150"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserConditions(Model):
    birth_date: date | None = None
    region_code: Annotated[str, StringConstraints(pattern=r"^\d{2}$")] | None = None
    income_level: Income | None = None
    education_level: Literal["HIGH_SCHOOL_OR_LESS", "COLLEGE", "UNIVERSITY", "GRADUATE_SCHOOL", "OTHER"] | None = None
    employment_status: Literal["UNEMPLOYED", "EMPLOYED", "SELF_EMPLOYED", "STUDENT", "OTHER"] | None = None
    marital_status: Literal["SINGLE", "MARRIED", "OTHER"] | None = None


class Condition(Model):
    eligibility_condition_id: ID | None = None
    condition_type: Text
    operator: Text
    value: str | None = None
    value_min: float | None = None
    value_max: float | None = None
    description: str
    requires_manual_check: bool


class Restriction(Model):
    restriction_id: ID | None = None
    target_policy_id: ID | None = None
    restriction_type: Literal["SPECIFIC_POLICY", "PROGRAM_TYPE", "SIMULTANEOUS"]
    target_program_type: str | None = None
    reason: str
    exception_condition: str | None = None
    source_info: str | None = None


class Policy(Model):
    policy_id: ID
    category_id: ID | None = None
    policy_name: Text
    summary: str | None = None
    support_content: str | None = None
    target_description: str | None = None
    organization: str | None = None
    application_start_date: date | None = None
    application_end_date: date | None = None
    application_method: str | None = None
    application_url: str | None = None
    status: str | None = None
    verification_status: str | None = None
    eligibility_conditions: list[Condition]
    duplicate_restrictions: list[Restriction]


class Benefit(Model):
    benefit_id: ID
    policy_id: ID
    benefit_status: Literal["CURRENT", "PAST"]
    benefit_start_date: date | None = None
    benefit_end_date: date | None = None


class Document(Model):
    document_id: ID
    document_title: Text
    policy_text: Text
    source_name: str | None = None
    source_url: Text
    published_at: date | None = None


class Reference(Model):
    policy_id: ID
    document_id: ID
    evidence_text: Text
    source_url: Text


class EligibilityRequest(Model):
    user_conditions: UserConditions
    policy: Policy


class RecommendationRequest(Model):
    user_conditions: UserConditions
    benefits: list[Benefit]
    policies: list[Policy]
    interest_category_ids: list[ID] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=100)


class DuplicateRequest(Model):
    user_conditions: UserConditions
    benefits: list[Benefit]
    policies: list[Policy]
    target_policy_id: ID


class ScenarioRequest(Model):
    before_conditions: UserConditions
    after_conditions: UserConditions
    benefits: list[Benefit]
    policies: list[Policy]


class SearchRequest(Model):
    stage: Literal["SEARCH"]
    question: Text
    consultation_type: Literal["POLICY_QA", "PERSONALIZED"]


class QARequest(Model):
    stage: Literal["ANSWER"]
    question: Text
    consultation_type: Literal["POLICY_QA"]
    references: list[Reference]


class PersonalizedRequest(Model):
    stage: Literal["ANSWER"]
    question: Text
    consultation_type: Literal["PERSONALIZED"]
    references: list[Reference]
    user_conditions: UserConditions
    benefits: list[Benefit]
    policies: list[Policy]


class IndexUpdate(Model):
    documents: list[Document] = Field(min_length=1)
    source_version: AwareDatetime


class IndexCreate(IndexUpdate):
    policy_id: ID


class VerificationRequest(IndexCreate):
    eligibility_conditions: list[Condition]
    duplicate_restrictions: list[Restriction]


class Envelope(Model):
    content_type: Literal["application/json"] = "application/json"
    result_code: int
    result_req: str = ""


class IndexResponse(Envelope):
    policy_id: ID
    source_version: AwareDatetime
    indexed_document_count: int
    chunk_count: int
    status: Literal["COMPLETED"]


class DeleteResponse(Envelope):
    deleted: bool


class SearchResponse(Envelope):
    policy_ids: list[ID]
    references: list[Reference]


class ConditionResult(Model):
    eligibility_condition_id: ID | None = None
    condition_type: str
    result: Literal["SATISFIED", "UNSATISFIED", "NEEDS_REVIEW"]
    user_value: str | None
    policy_value: str | None
    reason: str


class EligibilityResponse(Envelope):
    final_status: Literal["ELIGIBLE", "INELIGIBLE", "NEEDS_REVIEW"]
    items: list[ConditionResult]


class RecommendationItem(Model):
    policy_id: ID
    rank_order: int
    recommendation_reason: str


class RecommendationResponse(Envelope):
    items: list[RecommendationItem]


class DuplicateItem(Model):
    benefit_id: ID
    policy_id: ID
    result: Literal["AVAILABLE", "RESTRICTED", "NEEDS_REVIEW"]
    reason: str
    source_info: str | None = None


class DuplicateResponse(Envelope):
    final_status: Literal["AVAILABLE", "RESTRICTED", "NEEDS_REVIEW"]
    items: list[DuplicateItem]


class AnalysisSnapshot(Model):
    final_status: Literal["ELIGIBLE", "INELIGIBLE", "NEEDS_REVIEW"]
    items: list[ConditionResult]


class ScenarioResult(AnalysisSnapshot):
    policy_id: ID


class ScenarioResponse(Envelope):
    before_results: list[ScenarioResult]
    after_results: list[ScenarioResult]
    newly_eligible_policy_ids: list[ID]
    no_longer_eligible_policy_ids: list[ID]


class AnswerResponse(Envelope):
    answer: str
    analysis_snapshot: AnalysisSnapshot | None
    references: list[Reference]
    response_time_ms: int
    quality_status: Literal["NORMAL", "NEEDS_REVIEW"]


class VerificationIssue(Model):
    field: str
    condition_type: str | None = None
    issue_type: str
    status: str
    description: str
    evidence: str
    document_id: ID


class VerificationResponse(Envelope):
    policy_id: ID
    source_version: AwareDatetime
    verification_status: Literal["VERIFIED", "PENDING_REVIEW"]
    issues: list[VerificationIssue]
