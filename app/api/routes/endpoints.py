import fastapi

from api.routes.assistant.assistant import router as chat_builder_router

router = fastapi.APIRouter()

router.include_router(router=chat_builder_router)
