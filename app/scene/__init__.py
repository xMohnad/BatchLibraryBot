from typing import Any

from aiogram.dispatcher.event.bases import NextMiddlewareType
from aiogram.filters import Command
from aiogram.fsm.scene import Scene
from aiogram.fsm.scene import SceneRegistry as _SceneRegistry
from aiogram.types import TelegramObject

from app.scene.browse import BrowseScene
from app.scene.img2pdf import Img2PdfScene

SCENES: dict[str, dict[type[Scene], str]] = {
    "bot": {
        BrowseScene: "browse",
        Img2PdfScene: "img2pdf",
    }
}


class SceneRegistry(_SceneRegistry):
    async def _middleware(
        self,
        handler: NextMiddlewareType[TelegramObject],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # we don't need aiogram Scene handle all events issues/1743
        if "state" in data:
            return await super()._middleware(handler, event, data)

        return await handler(event, data)


def register_scene(registry: SceneRegistry):
    for scene, command in SCENES[registry.router.name].items():
        registry.add(scene)
        registry.router.message.register(scene.as_handler(), Command(command))


__all__ = ["SceneRegistry", "register_scene"]
