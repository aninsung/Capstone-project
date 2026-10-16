"""Contract preview only. Analysis/indexing is scheduled for weeks 2-4."""
import hmac
import os
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import schemas as s

app = FastAPI(title="청년 정책 AI 계약 초안", version="0.1.0", description="1주 차 계약 검토용. 분석·인덱스 API는 501을 반환합니다.")
bearer = HTTPBearer(auto_error=False)


def service_auth(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    token = os.getenv("AI_SERVICE_TOKEN", "")
    if not token:
        raise HTTPException(503, "SERVICE_NOT_CONFIGURED")
    if credentials is None or not hmac.compare_digest(credentials.credentials.encode(), token.encode()):
        raise HTTPException(401, "UNAUTHENTICATED")


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"content_type": "application/json", "result_code": exc.status_code, "result_req": "요청을 처리할 수 없습니다.", "error_code": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Never echo input values or exception context containing personal data.
    return JSONResponse(status_code=400, content={"content_type": "application/json", "result_code": 400, "result_req": "요청값을 확인하세요.", "error_code": "INVALID_REQUEST", "errors": [{"field": ".".join(map(str, e["loc"])), "message": e["type"]} for e in exc.errors()]})


@app.get("/health")
def health():
    return {"status": "ok", "implementation_stage": "week1_contract_preview"}


def pending():
    raise HTTPException(501, "NOT_IMPLEMENTED_WEEK1")


COMMON_RESPONSES = {code: {"description": label} for code, label in [(400, "INVALID_REQUEST"), (401, "UNAUTHENTICATED"), (422, "ANALYSIS_INPUT_INCOMPLETE"), (501, "1주 차 계약만 제공"), (503, "서비스 토큰 미설정")]}


def register(path, request_model, response_model=s.Envelope, method="POST", status=200):
    def endpoint(body):
        pending()
    endpoint.__annotations__["body"] = request_model
    app.add_api_route(path, endpoint, methods=[method], status_code=status, response_model=response_model, dependencies=[Depends(service_auth)], responses=COMMON_RESPONSES, name=path.rsplit("/", 1)[-1])


register("/ai/v1/recommendations", s.RecommendationRequest, s.RecommendationResponse)
register("/ai/v1/eligibility-analyses", s.EligibilityRequest, s.EligibilityResponse)
register("/ai/v1/duplicate-benefit-analyses", s.DuplicateRequest, s.DuplicateResponse)
register("/ai/v1/scenario-analyses", s.ScenarioRequest, s.ScenarioResponse)
register("/ai/v1/consultations", s.SearchRequest | s.QARequest | s.PersonalizedRequest, s.SearchResponse | s.AnswerResponse)
register("/ai/v1/policy-verifications", s.VerificationRequest, s.VerificationResponse)
register("/ai/v1/policy-indexes", s.IndexCreate, s.IndexResponse, status=201)


@app.put("/ai/v1/policy-indexes/{policy_id}", response_model=s.IndexResponse, dependencies=[Depends(service_auth)], responses=COMMON_RESPONSES)
def update_index(policy_id: s.ID, body: s.IndexUpdate):
    pending()


@app.delete("/ai/v1/policy-indexes/{policy_id}", response_model=s.DeleteResponse, dependencies=[Depends(service_auth)], responses=COMMON_RESPONSES)
def delete_index(policy_id: s.ID):
    pending()
