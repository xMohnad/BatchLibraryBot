from contextvars import ContextVar

from audit.models import Actor

current_actor: ContextVar[Actor | None] = ContextVar("current_actor", default=None)
