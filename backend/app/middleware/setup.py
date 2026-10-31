from fastapi import FastAPI


def register_middleware(app: FastAPI) -> None:
    """Register future ASGI middleware here before the app starts serving.

    Example: app.add_middleware(YourAuthenticationMiddleware, ...)
    Middleware can attach verified identity to request.state. Resource-level
    permissions should then be checked by dependencies/services, not trusted IDs.
    """
