import base64
import html
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents import KernelEngine
from .documents import MAX_BYTES, extract_isolated
from .jobs import Jobs
from .middleware import BodyLimit
from .models import Match
from .retrieval import chunk_pages, index_document, search_chunks
from .sample import seed_sample
from .security import Auth
from .service import CourseService
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    data_dir: Path = ROOT / "data"
    invitation: str = "scopewise-local"
    production: bool = False
    public_url: str = "http://127.0.0.1:8080"
    semantic_index: bool = True

    def __post_init__(self):
        if self.production and (len(self.invitation) < 24 or not self.public_url.startswith("https://") or self.invitation == "scopewise-local"):
            raise ValueError("Production requires a random invitation of at least 24 characters and an HTTPS public URL.")

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        return cls(
            data_dir=Path(os.getenv("SCOPEWISE_DATA", str(ROOT / "data"))),
            invitation=os.getenv("SCOPEWISE_INVITATION", "scopewise-local"),
            production=os.getenv("SCOPEWISE_PRODUCTION", "false").lower() == "true",
            public_url=os.getenv("SCOPEWISE_PUBLIC_URL", "http://127.0.0.1:8080"),
            semantic_index=os.getenv("SCOPEWISE_SEMANTIC_INDEX", "true").lower() == "true",
        )


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=128)
    invitation: str = Field(default="", max_length=256)


class CourseInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    lecturer: str = Field(default="", max_length=120)


class CoursePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    lecturer: str | None = Field(default=None, max_length=120)


class Approval(BaseModel):
    approved: bool


class Acknowledgement(BaseModel):
    acknowledged: bool


class PackInput(BaseModel):
    limit: int = Field(default=8, ge=1, le=30)


class GeneratedPackInput(PackInput):
    difficulty: Literal["easy", "medium", "difficult"] = "medium"


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class PrepareInput(BaseModel):
    document_ids: list[str] = Field(min_length=2, max_length=3)


class BatchReviewInput(BaseModel):
    confirmed: Literal[True]


def create_app(settings=None, engine_factory=KernelEngine):
    settings = settings or Settings.from_env()
    store = Store(settings.data_dir / "scopewise.sqlite3")
    auth = Auth(store, settings.invitation)
    service = CourseService(store)
    jobs = Jobs(store, engine_factory)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await jobs.close()

    app = FastAPI(title="ScopeWise", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(BodyLimit)
    app.state.store, app.state.auth, app.state.jobs, app.state.settings = store, auth, jobs, settings

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse({"detail": "Resource not found."}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)[:500]}, status_code=400)

    @app.middleware("http")
    async def protection(request, call_next):
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            expected = settings.public_url.rstrip("/") if settings.production else str(request.base_url).rstrip("/")
            if origin and origin.rstrip("/") != expected:
                return JSONResponse({"detail": "Cross-origin requests are not allowed."}, status_code=403)
            content_length = request.headers.get("content-length")
            limit = MAX_BYTES + 65536 if "multipart/form-data" in request.headers.get("content-type", "") else 128000
            if content_length is None and request.headers.get("transfer-encoding"):
                return JSONResponse({"detail": "A Content-Length header is required."}, status_code=411)
            if content_length:
                try:
                    length = int(content_length)
                except ValueError:
                    return JSONResponse({"detail": "Invalid content length."}, status_code=400)
                if not 0 <= length <= limit:
                    return JSONResponse({"detail": "Request exceeds the upload limit."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src "
            "'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        if settings.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def user(request: Request):
        token = request.cookies.get("scopewise_session")
        found = auth.resolve(token)
        if not found:
            raise HTTPException(401, "Please sign in.")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not auth.check_csrf(token, request.headers.get("x-csrf-token")):
            raise HTTPException(403, "Session verification failed. Refresh the page and try again.")
        if not store.allow(f"request:{found['id']}", 180):
            raise HTTPException(429, "Too many requests. Please pause briefly.")
        return found

    def auth_limit(request):
        ip = request.client.host if request.client else "unknown"
        if not store.allow(f"auth:{ip}", 12, 300):
            raise HTTPException(429, "Too many sign-in attempts. Try again in five minutes.")

    @app.get("/health")
    def health():
        with store.connect() as db:
            db.execute("SELECT 1")
        return {"status": "ok"}

    @app.get("/api/status")
    def status():
        return {
            "name": "ScopeWise",
            "development": not settings.production,
            "development_invitation": "scopewise-local" if not settings.production and settings.invitation == "scopewise-local" else None,
            "model": os.getenv("SCOPEWISE_MODEL", "llama3.1:latest"),
            "model_mode": "local Ollama; no cloud fallback",
            "telegram": bool(os.getenv("AK_TELEGRAM__BOT_TOKEN")),
            "notice": "Private pilot. Text PDFs and PPTX files are supported. Evidence and human review are required; no exam predictions.",
        }

    if os.getenv("AK_TELEGRAM__BOT_TOKEN"):
        from .telegram import ScopeWiseTelegram

        telegram = ScopeWiseTelegram(store, jobs, os.getenv("AK_TELEGRAM__WEBHOOK_SECRET", ""))
        app.state.telegram = telegram
        app.include_router(telegram.get_router())

        @app.post("/api/telegram/link")
        def link_telegram(identity=Depends(user)):
            return {"code": telegram.links.issue(identity["id"]), "expires_in": 600}

        @app.delete("/api/telegram/link")
        def unlink_telegram(identity=Depends(user)):
            telegram.links.unlink(identity["id"])
            return {"ok": True}

    @app.post("/api/auth/register")
    def register(body: Credentials, request: Request):
        auth_limit(request)
        return auth.register(body.username, body.password, body.invitation)

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request):
        auth_limit(request)
        token, csrf, identity = auth.login(body.username, body.password)
        response = JSONResponse({**identity, "csrf": csrf})
        response.set_cookie("scopewise_session", token, max_age=86400, httponly=True, secure=settings.production, samesite="strict")
        return response

    @app.post("/api/auth/logout")
    def logout(request: Request, identity=Depends(user)):
        auth.logout(request.cookies.get("scopewise_session"))
        response = JSONResponse({"ok": True})
        response.delete_cookie("scopewise_session")
        return response

    @app.get("/api/me")
    def me(identity=Depends(user)):
        return identity

    @app.get("/api/courses")
    def courses(identity=Depends(user)):
        return store.list(identity["id"], "course")

    @app.post("/api/courses")
    def create_course(body: CourseInput, identity=Depends(user)):
        return store.create_course(identity["id"], body.title.strip(), body.lecturer.strip())

    @app.get("/api/courses/{course_id}")
    def course(course_id: str, identity=Depends(user)):
        return service.bundle(identity["id"], course_id)

    @app.patch("/api/courses/{course_id}")
    def edit_course(course_id: str, body: CoursePatch, identity=Depends(user)):
        return service.edit_course(identity["id"], course_id, **body.model_dump(exclude_unset=True))

    @app.delete("/api/courses/{course_id}")
    def delete_course(course_id: str, identity=Depends(user)):
        store.delete_course(identity["id"], course_id)
        return {"ok": True}

    @app.post("/api/sample")
    def sample(identity=Depends(user)):
        return seed_sample(store, identity["id"])

    @app.post("/api/courses/{course_id}/documents")
    async def upload(
        course_id: str,
        file: UploadFile = File(...),
        role: Literal["syllabus", "notes", "paper", "guidance"] = Form(...),
        lecturer: str = Form("", max_length=120),
        year: str = Form("", max_length=20),
        identity=Depends(user),
    ):
        owner = identity["id"]
        store.get(owner, "course", course_id)
        if len(store.list(owner, "document", course_id)) >= 12:
            raise ValueError("This pilot supports up to 12 documents per course.")
        raw = await file.read(MAX_BYTES + 1)
        await file.close()
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "Files must be no larger than 8 MB.")
        filename = Path(file.filename or "document.txt").name[:180]
        pages = await extract_isolated(raw, filename)
        document = store.put(
            owner,
            "document",
            course_id,
            {
                "name": filename,
                "role": role,
                "lecturer": lecturer,
                "year": year,
                "approved": False,
                "pages": pages,
                "content": base64.b64encode(raw).decode(),
                "mime": (
                    "application/pdf"
                    if filename.lower().endswith(".pdf")
                    else "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                    if filename.lower().endswith(".pptx")
                    else "text/markdown"
                    if filename.lower().endswith(".md")
                    else "text/plain"
                ),
            },
        )
        document = await index_document(store, owner, course_id, document, semantic=settings.semantic_index)
        store.update_course(owner, course_id)
        return {k: v for k, v in document.items() if k != "content"}

    @app.get("/api/courses/{course_id}/source-search")
    async def source_search(
        course_id: str,
        q: str = Query(min_length=2, max_length=300),
        identity=Depends(user),
    ):
        owner = identity["id"]
        documents = store.list(owner, "document", course_id)
        # Existing pilot data is upgraded lazily; no re-upload is required.
        for document in documents:
            if not store.list_chunks(owner, course_id, document_ids={document["id"]}):
                chunks = chunk_pages(document["pages"])
                store.replace_chunks(owner, course_id, document["id"], chunks)
                document.update(index_status="lexical", chunk_count=len(chunks), embedding_model=None)
                store.put(owner, "document", course_id, document, document["id"])
        result = await search_chunks(store, owner, course_id, q, limit=6, semantic=settings.semantic_index)
        names = {document["id"]: document["name"] for document in documents}
        result["results"] = [{**item, "document_name": names.get(item["document_id"], "Source")} for item in result["results"]]
        return result

    @app.patch("/api/documents/{document_id}")
    def approve_document(document_id: str, body: Approval, identity=Depends(user)):
        return service.approve_document(identity["id"], document_id, body.approved)

    @app.patch("/api/jobs/{job_id}")
    def acknowledge_job(job_id: str, body: Acknowledgement, identity=Depends(user)):
        job = store.get(identity["id"], "job", job_id)
        job["acknowledged"] = body.acknowledged
        return store.put(identity["id"], "job", job["course_id"], job, job_id)

    @app.get("/api/documents/{document_id}/download")
    def download(document_id: str, identity=Depends(user)):
        document = store.get(identity["id"], "document", document_id)
        content = base64.b64decode(document["content"]) if document.get("content") else "\f".join(document["pages"]).encode()
        return Response(
            content, media_type=document["mime"], headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(document['name'])}"}
        )

    @app.post("/api/courses/{course_id}/extract/{document_id}")
    async def extract(course_id: str, document_id: str, identity=Depends(user)):
        return jobs.submit(identity["id"], course_id, "extract", document_id)

    @app.post("/api/courses/{course_id}/items/{kind}")
    def add_item(course_id: str, kind: str, body: dict, identity=Depends(user)):
        return service.save_item(identity["id"], course_id, kind, body)

    @app.patch("/api/items/{kind}/{item_id}")
    def update_item(kind: str, item_id: str, body: dict, identity=Depends(user)):
        if kind not in {"objective", "question"}:
            raise HTTPException(404, "Resource not found.")
        current = store.get(identity["id"], kind, item_id)
        return service.save_item(identity["id"], current["course_id"], kind, body, item_id)

    @app.post("/api/courses/{course_id}/analyze")
    async def analyze(course_id: str, identity=Depends(user)):
        return jobs.submit(identity["id"], course_id, "analyze")

    @app.post("/api/courses/{course_id}/prepare")
    async def prepare(course_id: str, body: PrepareInput, identity=Depends(user)):
        return jobs.submit(identity["id"], course_id, "prepare", document_ids=body.document_ids)

    @app.post("/api/courses/{course_id}/manual-review")
    def manual_review(course_id: str, identity=Depends(user)):
        return service.manual_review(identity["id"], course_id)

    @app.patch("/api/analyses/{analysis_id}/matches")
    def review(analysis_id: str, body: Match, identity=Depends(user)):
        return service.review_match(identity["id"], analysis_id, body.model_dump())

    @app.patch("/api/analyses/{analysis_id}/matches/review-suitable")
    def review_suitable(analysis_id: str, body: BatchReviewInput, identity=Depends(user)):
        return service.review_suitable_matches(identity["id"], analysis_id)

    @app.post("/api/courses/{course_id}/packs")
    def pack(course_id: str, body: PackInput, identity=Depends(user)):
        return service.prepare_pack(identity["id"], course_id, body.limit)

    @app.post("/api/courses/{course_id}/packs/generate")
    async def generated_pack(course_id: str, body: GeneratedPackInput, identity=Depends(user)):
        return jobs.submit(identity["id"], course_id, "generate_pack", limit=body.limit, difficulty=body.difficulty)

    @app.get("/api/packs/{pack_id}/export")
    def export(pack_id: str, identity=Depends(user)):
        pack = store.get(identity["id"], "pack", pack_id)
        if service.pack_stale(identity["id"], pack):
            raise HTTPException(409, "This pack is stale. Build a new pack after reviewing the current analysis.")
        docs = {d["id"]: d for d in store.list(identity["id"], "document", pack["course_id"])}
        esc = html.escape
        lines = [
            "<!doctype html><html lang='en'><meta charset='utf-8'><title>ScopeWise practice pack</title><body>",
            f"<h1>{esc(pack['title'])} — practice pack</h1>",
            f"<p>Scope v{pack['scope_version']} · Assessment v{pack['assessment_version']}</p>",
            f"<p>{esc(pack['origin'])}</p>",
            f"<p>{esc(pack['notice'])}</p>",
        ]
        for index, question in enumerate(pack["questions"], 1):
            evidence = question["evidence"]
            name = docs.get(evidence["document_id"], {}).get("name", "Source")
            generated = question.get("generated", False)
            lines.extend(
                [
                    f"<h2>{index}. {esc(question['label'] or 'Practice question')}</h2>",
                    (
                        f"<p><strong>AI-generated {esc(question.get('difficulty', 'medium'))} practice question.</strong> "
                        "Inspect before studying; this is not an exam prediction.</p>"
                        if generated
                        else ""
                    ),
                    f"<p>{esc(question['text'])}</p>",
                    f"<p>{'Grounding source' if generated else 'Source'}: {esc(name)}, page {evidence['page']}</p>",
                    f"<p>Syllabus fit: {esc(question['match']['scope_status'])}. Assessment fit: {esc(question['match']['assessment_status'])}.</p>",
                    f"<p>{esc(question['match']['reason'])}</p>",
                ]
            )
        uncovered = [o["text"] for o in pack["objectives"] if o["id"] in pack["uncovered_objective_ids"]]
        lines.append("<h2>Coverage gaps</h2><ul>" + "".join(f"<li>{esc(text)}</li>" for text in uncovered) + "</ul></body></html>")
        return HTMLResponse("\n".join(lines), headers={"Content-Disposition": 'attachment; filename="scopewise-practice-pack.html"'})

    @app.post("/api/courses/{course_id}/chat")
    async def chat(course_id: str, body: ChatInput, identity=Depends(user)):
        store.get(identity["id"], "course", course_id)
        if jobs.lock.locked() or len(jobs.tasks):
            raise HTTPException(409, "The local model is processing a document. Please wait for it to finish.")
        if not store.allow(f"chat:{identity['id']}", 30, 3600):
            raise HTTPException(429, "Hourly assistant limit reached.")
        async with jobs.lock:
            try:
                reply = await jobs.model().chat(identity["id"], course_id, body.message)
            except Exception:
                raise HTTPException(503, "Local assistant unavailable. Check that Ollama and the configured model are running.") from None
        return {"reply": reply}

    # The UI and API share one origin; no wildcard CORS or unauthenticated Kernel routes.
    app.mount("/static", StaticFiles(directory=ROOT / "static", check_dir=False), name="static")

    @app.get("/")
    def index():
        return HTMLResponse((ROOT / "static" / "index.html").read_text())

    return app
