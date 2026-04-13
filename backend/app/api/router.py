from fastapi import APIRouter

from app.api.routes import automation, contacts, email, entities, entity_contact_map, keywords, scrape, tenders

api_router = APIRouter()
api_router.include_router(scrape.router, tags=["scrape"])
api_router.include_router(tenders.router, tags=["tenders"])
api_router.include_router(email.router, tags=["email"])
api_router.include_router(contacts.router, tags=["contacts"])
api_router.include_router(entities.router, tags=["entities"])
api_router.include_router(entity_contact_map.router, tags=["entity-contact-map"])
api_router.include_router(keywords.router, tags=["keywords"])
api_router.include_router(automation.router, tags=["automation"])
