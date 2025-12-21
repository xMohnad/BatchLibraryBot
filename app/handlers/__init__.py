from .archive import router as archive
from .bot import router as bot
from .channel import router as channel

routers = [channel, bot, archive]
