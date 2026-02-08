from .archive import router as archive
from .bot import router as bot
from .channel import router as channel
from .commands import router as commands
from .inline_query import router as inline_query

routers = [channel, bot, archive, commands, inline_query]
