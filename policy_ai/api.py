"""Week 2 policy indexing and search API, with later analysis stages pending."""
import hmac
import os
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import schemas as s
from .rag import grounded_answer
from .vector_store import IndexConflict, VectorStore

app = FastAPI(title="청년 정책 AI", version="0.3.0", description="12주 계획 8주차: 정책 검색·RAG 응답·추천")
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
    return {"status": "ok", "implementation_stage": "week8_rag_answer"}


@app.get("/tmp/chat", response_class=HTMLResponse, include_in_schema=False)
def temporary_chat():
    return HTMLResponse("""<!doctype html><meta charset='utf-8'><title>정책 AI 임시 채팅</title>
<style>body{font-family:system-ui;max-width:820px;margin:32px auto;padding:0 18px;background:#effaf6;color:#243b53}main{background:white;padding:28px;border-radius:20px;box-shadow:0 4px 18px #1769aa22}h1{color:#62cdb0;margin:0 0 6px}header{border-bottom:1px solid #e6f2ef;padding-bottom:16px}#log{min-height:300px;max-height:560px;overflow:auto;padding:18px;border-radius:14px;background:#fbfefd;margin:18px 0}.q{max-width:70%;margin:12px 0 12px auto;color:white;background:#306b98;padding:12px 16px;border-radius:16px 16px 4px 16px;line-height:1.5}.a{max-width:90%;color:#17324d;line-height:1.7;white-space:pre-wrap;background:#f3f8f7;padding:16px;border-radius:4px 16px 16px 16px}.refs{margin-top:14px;display:grid;gap:10px}.ref{border:1px solid #bfe8db;border-radius:10px;padding:10px;font-size:14px;background:#fff}.ref a{color:#1769aa}.muted{color:#627d98;font-size:13px}.quick{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.quick button{background:#e5f7f1;color:#238b72;border:1px solid #bfe8db;padding:8px 12px;margin:0;border-radius:20px}input{width:78%;padding:13px;border:1px solid #bfe8db;border-radius:22px;box-sizing:border-box}form button{padding:13px 18px;margin-left:8px;border:0;border-radius:22px;background:#62cdb0;color:white}</style>
<main><header><h1>AI 정책 상담</h1><p>청년 정책을 검색하고 근거와 함께 안내합니다.</p></header><div class='quick'><button onclick="q.value='청년 월세 지원 정책을 알려줘'">청년 월세 지원</button><button onclick="q.value='청년 취업 지원 정책을 알려줘'">취업 지원</button><button onclick="q.value='중복 수혜가 가능한지 알려줘'">중복 수혜</button></div><div id='log'><div class='a'><b>안녕하세요!</b><br>궁금한 청년 정책을 입력하면 관련 근거와 출처를 함께 찾아드릴게요.</div></div><form><input id='q' placeholder='메시지를 입력하세요' required><button>전송</button></form></main>
<script>const log=document.querySelector('#log'); const form=document.querySelector('form'); const q=document.querySelector('#q'); const esc=x=>String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
form.onsubmit=async e=>{e.preventDefault(); const question=q.value.trim(); if(!question)return; log.innerHTML+=`<div class=q>질문: ${esc(question)}</div>`; q.value=''; try{const r=await fetch('/tmp/chat/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})}); const ar=await r.json(); if(!r.ok)throw Error(ar.error_code||'질의 실패'); const refs=(ar.references||[]).map((x,i)=>`<div class=ref><b>[${i+1}] ${esc(x.document_id)}</b><br><span>${esc(x.evidence_text).slice(0,240)}${x.evidence_text.length>240?'…':''}</span><br><a href='${esc(x.source_url)}' target='_blank'>원문 출처 열기</a></div>`).join(''); log.innerHTML+=`<div class=a><b>답변</b><br>${esc(ar.answer)}<div class=muted>응답 시간 ${ar.response_time_ms}ms · 품질 ${esc(ar.quality_status)}</div><div class=refs><b>참고 문서</b>${refs||'<span class=muted>관련 문서를 찾지 못했습니다.</span>'}</div></div>`}catch(err){log.innerHTML+=`<div class=a>오류: ${esc(err.message)}</div>`}};</script>""")


@app.post("/tmp/chat/ask", include_in_schema=False)
def temporary_chat_ask(body: dict):
    question = str(body.get("question", "")).strip()
    if not question:
        raise HTTPException(400, "QUESTION_REQUIRED")
    hits = VectorStore(os.getenv("VECTOR_DB_PATH", "data/week2/vector.sqlite3")).search(question, top_k=5)
    references = [{"policy_id": h.policy_id, "document_id": h.document_id, "evidence_text": h.text, "source_url": h.source_url} for h in hits]
    answer, quality, elapsed = grounded_answer(question, references)
    return {"answer": answer, "quality_status": quality, "response_time_ms": elapsed, "references": references}


def pending():
    raise HTTPException(501, "NOT_IMPLEMENTED_WEEK1")


COMMON_RESPONSES = {code: {"description": label} for code, label in [(400, "INVALID_REQUEST"), (401, "UNAUTHENTICATED"), (422, "ANALYSIS_INPUT_INCOMPLETE"), (501, "1주 차 계약만 제공"), (503, "서비스 토큰 미설정")]}


def register(path, request_model, response_model=s.Envelope, method="POST", status=200, handler=None):
    def endpoint(body):
        return handler(body) if handler else pending()
    endpoint.__annotations__["body"] = request_model
    app.add_api_route(path, endpoint, methods=[method], status_code=status, response_model=response_model, dependencies=[Depends(service_auth)], responses=COMMON_RESPONSES, name=path.rsplit("/", 1)[-1])


def recommend(body):
    interests = set(body.interest_category_ids)
    ranked = []
    for policy in body.policies:
        score = 2 if policy.category_id and policy.category_id in interests else 0
        score += 1 if policy.verification_status == "VERIFIED" else 0
        ranked.append((score, policy))
    ranked.sort(key=lambda item: (-item[0], item[1].policy_id))
    return {"result_code": 200, "result_req": "추천이 완료되었습니다.", "items": [{"policy_id": p.policy_id, "rank_order": i + 1, "recommendation_reason": "관심 분야와 검증 상태를 기준으로 정렬했습니다." if score else "추가 자격 확인이 필요합니다."} for i, (score, p) in enumerate(ranked[:body.limit])]}


register("/ai/v1/recommendations", s.RecommendationRequest, s.RecommendationResponse, handler=recommend)
register("/ai/v1/eligibility-analyses", s.EligibilityRequest, s.EligibilityResponse)
register("/ai/v1/duplicate-benefit-analyses", s.DuplicateRequest, s.DuplicateResponse)
register("/ai/v1/scenario-analyses", s.ScenarioRequest, s.ScenarioResponse)
def search_consultation(body):
    if body.stage == "SEARCH":
        store = VectorStore(os.getenv("VECTOR_DB_PATH", "data/week2/vector.sqlite3"))
        hits = store.search(body.question, top_k=5)
        return {"result_code": 200, "result_req": "검색이 완료되었습니다.", "policy_ids": [h.policy_id for h in hits], "references": [{"policy_id": h.policy_id, "document_id": h.document_id, "evidence_text": h.text, "source_url": h.source_url} for h in hits]}
    references = [r.model_dump(mode="json") for r in body.references]
    answer, quality, elapsed = grounded_answer(body.question, references)
    snapshot = {"final_status": "NEEDS_REVIEW", "items": []} if body.consultation_type == "PERSONALIZED" else None
    return {"result_code": 200, "result_req": "답변이 생성되었습니다.", "answer": answer, "analysis_snapshot": snapshot, "references": body.references, "response_time_ms": elapsed, "quality_status": quality}


def create_index(body):
    store = VectorStore(os.getenv("VECTOR_DB_PATH", "data/week2/vector.sqlite3"))
    try:
        result = store.upsert_policy(body.policy_id, body.source_version.isoformat(), [d.model_dump(mode="json") for d in body.documents])
    except IndexConflict as exc:
        raise HTTPException(409, str(exc))
    return {"result_code": 201, "result_req": "인덱스가 생성되었습니다.", **result}


register("/ai/v1/consultations", s.SearchRequest | s.QARequest | s.PersonalizedRequest, s.SearchResponse | s.AnswerResponse, handler=search_consultation)
register("/ai/v1/policy-verifications", s.VerificationRequest, s.VerificationResponse)
register("/ai/v1/policy-indexes", s.IndexCreate, s.IndexResponse, status=201, handler=create_index)


@app.put("/ai/v1/policy-indexes/{policy_id}", response_model=s.IndexResponse, dependencies=[Depends(service_auth)], responses=COMMON_RESPONSES)
def update_index(policy_id: s.ID, body: s.IndexUpdate):
    store = VectorStore(os.getenv("VECTOR_DB_PATH", "data/week2/vector.sqlite3"))
    try:
        result = store.upsert_policy(policy_id, body.source_version.isoformat(), [d.model_dump(mode="json") for d in body.documents])
    except IndexConflict as exc:
        raise HTTPException(409, str(exc))
    return {"result_code": 200, "result_req": "인덱스가 갱신되었습니다.", **result}


@app.delete("/ai/v1/policy-indexes/{policy_id}", response_model=s.DeleteResponse, dependencies=[Depends(service_auth)], responses=COMMON_RESPONSES)
def delete_index(policy_id: s.ID):
    deleted = VectorStore(os.getenv("VECTOR_DB_PATH", "data/week2/vector.sqlite3")).delete_policy(policy_id)
    return {"result_code": 200, "result_req": "인덱스가 삭제되었습니다.", "deleted": deleted}
