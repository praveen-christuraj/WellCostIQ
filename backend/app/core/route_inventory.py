"""Mounted dependency evidence, not proof of object-level tenant scoping.

Run from backend: python -m app.core.route_inventory > ../docs/SECURITY_ROUTE_INVENTORY.json
Importing the app does not enter its lifespan or start the backup scheduler.
"""
import inspect
import json

from fastapi.routing import APIRoute, iter_route_contexts

from app.api.deps import current_user

PUBLIC_ROUTES = frozenset({
    ("GET", "/"), ("GET", "/api/health"),
    ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/reset-password"),
})
DOC_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})


def _dependencies(dependency):
    yield dependency
    for child in dependency.dependencies:
        yield from _dependencies(child)


def inventory(app):
    rows = []
    violations = []
    for route in iter_route_contexts(app.routes):
        if not isinstance(route.original_route, APIRoute):
            if getattr(route, "path", None) not in DOC_PATHS:
                violations.append(f"Unclassified non-API route: {getattr(route, 'path', type(route).__name__)}")
            continue
        dependencies = list(_dependencies(route.dependant))
        authenticated = any(item.call is current_user for item in dependencies)
        capabilities = [
            {"mode": item.call.security_capability_mode, "keys": list(item.call.security_capabilities)}
            for item in dependencies if hasattr(item.call, "security_capabilities")
        ]
        for method in sorted(route.methods):
            public = (method, route.path) in PUBLIC_ROUTES
            if not authenticated and not public:
                violations.append(f"Missing authentication: {method} {route.path}")
            rows.append({
                "method": method, "path": route.path, "public_allowlisted": public,
                "authenticated_dependency": authenticated, "capabilities": capabilities,
                "handler": f"{route.endpoint.__module__}.{route.endpoint.__name__}",
                "source_line": inspect.getsourcelines(route.endpoint)[1],
                "tenant_owner_audit_review": "manual review required; dependencies alone are not proof",
            })
    return {"routes": sorted(rows, key=lambda row: (row["path"], row["method"])), "violations": violations}


def main():
    from app.main import app
    result = inventory(app)
    print(json.dumps(result, indent=2))
    if result["violations"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
