"""Service layer — business logic, no HTTP.

Routers (FastAPI) call these; they take an SQLAlchemy session + explicit
`org_id`/`firm_id` arguments per CLAUDE.md §"Authentication & RLS". RLS
is set on the session by `app.dependencies.get_db` before the request
reaches the service, so service code reads the implicit `org_id` GUC for
filtering rather than appending `WHERE org_id = …` itself.
"""
