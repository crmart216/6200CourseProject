from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.middleware.setup import register_middleware
from app.routes.chat import router
from app.services.chat import DomainError


def create_app() -> FastAPI:
    app = FastAPI(
        title=get_settings().app_name,
        version="0.1.0",
        description=(
            "Group chat REST API with optional RSA-OAEP-SHA256 group key escrow. "
            "Deliberately no authentication or authorization; identities are untrusted. "
            "Message content is not encrypted by the backend."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    register_middleware(app)
    app.include_router(router)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.get("/health", tags=["Health"])
    def health() -> dict[str, str]:
        """Process liveness only; does not check the database."""
        return {"status": "ok"}

    return app


app = create_app()
