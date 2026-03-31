from .archive import router as archive
from .bot import router as bot
from .channel import router as channel
from .commands import router as commands

routers = [channel, bot, archive, commands]
