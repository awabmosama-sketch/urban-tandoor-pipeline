from sqlmodel import SQLModel


class Base(SQLModel):
    """Shared base for all SQLModel tables. Reserved for common mixins
    (timestamps, soft-delete) once Phase 2 tables arrive."""

    pass
