from contextvars import ContextVar

from core.audit import Actor

current_actor: ContextVar[Actor | None] = ContextVar("current_actor", default=None)
