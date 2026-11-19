import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.routers import users

logger = logging.getLogger("app")
app = FastAPI()


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info("%s %s", request.method, request.url.path)
    return await call_next(request)


@app.exception_handler(Exception)
async def internal_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(exc)
    return JSONResponse(status_code=500, content={"error": "Internal Server Error"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(users.router)
