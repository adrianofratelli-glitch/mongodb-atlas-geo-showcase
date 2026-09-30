import re
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import readiness
from routers import geo
from security import ApiHardeningMiddleware, MutationGuardMiddleware
from settings import settings

app = FastAPI(title="MongoDB Atlas Geo Showcase", version="1.0.0")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

app.add_middleware(ApiHardeningMiddleware)
app.add_middleware(MutationGuardMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Demo-Token", "X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    supplied_request_id = request.headers.get("x-request-id", "")
    request_id = supplied_request_id if REQUEST_ID_RE.fullmatch(supplied_request_id) else uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder({"detail": "Parâmetros inválidos.", "errors": exc.errors()}),
    )


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=500,
        content={"detail": "Falha interna na demonstração.", "request_id": request_id},
    )


app.include_router(geo.router)


@app.get("/")
def root():
    return {"status": "ok", "poc": "MongoDB Atlas Geo Showcase", "version": app.version}


@app.get("/health/live")
def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready():
    ok, message = readiness()
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, "message": message})


@app.get("/preflight")
def preflight():
    mongo_ok, mongo_message = readiness()
    checks = {
        "mongo_uri": {"ok": bool(settings.mongo_uri), "message": "configurada" if settings.mongo_uri else "ausente"},
        "mongodb": {"ok": mongo_ok, "message": mongo_message},
        "mutation_guard": {
            "ok": True,
            "message": "token obrigatório" if settings.demo_admin_token else "somente localhost/origens permitidas",
        },
    }
    if mongo_ok:
        checks.update(geo.preflight_checks())

    # geo_search é opcional: a UI mostra "não configurado" e o resto roda.
    opcionais = {"geo_search"}
    ready = all(check["ok"] for key, check in checks.items() if key not in opcionais)
    return JSONResponse(status_code=200 if ready else 503, content={"ready": ready, "checks": checks})
