"""Ingest Fathom transcripts batch 17 (recording 577760574)."""
import asyncio
import sys
import uuid

sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()

from app.core.database import get_session_factory
from app.core.config import get_settings
from app.services.ingestion.pipeline import IngestionPipeline
from app.services.ingestion.embedder import Embedder

USER_ID = uuid.UUID("889ff4f4-b782-4e9f-bfb1-e310ae132827")

TRANSCRIPTS = [
    {
        "source_id": "577760574",
        "date": "2026-02-10",
        "title": "Alineacion comercial y tecnica Flock — Contamara, CV Oil & Gas, Vision 360",
        "content": (
            "Meeting: Alineacion comercial y tecnica Flock — Contamara, CV Oil & Gas, Vision 360\n"
            "Date: 2026-02-10\n"
            "Participants: Mariano Ortega, Federico Valentino Lacoste, Sebastian Loizaga, Paula Vejrup\n\n"
            "Contexto: Reunion de alineacion comercial y tecnica entre el equipo de I+D y el equipo "
            "comercial de Flock. Temas principales: coordinacion de la reunion con Contamara, "
            "propuesta tecnica de CV para oil & gas, y alcance del MVP de Vision 360.\n\n"
            "1. Coordinacion Reunion Contamara\n"
            "Problema identificado: reuniones con Contamara se estaban organizando sin notificar "
            "a Flock. Mariano levanta la necesidad de que el equipo de Flock este al tanto y "
            "participe en las reuniones con este cliente. Se acuerda mecanismo de coordinacion "
            "para que esto no vuelva a suceder.\n\n"
            "2. Propuesta Tecnica CV para Oil & Gas\n"
            "Se define una propuesta en 4 etapas:\n"
            "- Etapa 1 — POC: 2 camaras termicas + generacion de imagenes sinteticas. "
            "Duracion estimada: 1 mes. Costo: sin cargo (gratuito para el cliente).\n"
            "- Etapa 2 — MVP: sistema en tiempo real + plataforma Vision 360. "
            "Duracion: 1.5 a 3 meses. Costo: pagado por el cliente.\n"
            "- Etapa 3 — Rollout parcial: despliegue en subset de instalaciones del cliente.\n"
            "- Etapa 4 — Rollout completo: despliegue total en todas las instalaciones.\n\n"
            "3. Alcance MVP Vision 360\n"
            "El MVP de Vision 360 incluye:\n"
            "- Login hardcodeado (sin sistema de autenticacion complejo en esta fase).\n"
            "- Dashboard principal con metricas clave.\n"
            "- Vista de camara en vivo (live camera feed).\n"
            "- Sistema de alertas.\n\n"
            "4. Riesgos Identificados\n"
            "- El producto actual es un 'shell' (carcaza sin funcionalidad completa): riesgo de "
            "mostrar algo incompleto al cliente.\n"
            "- Guille se encuentra de vacaciones: recurso clave no disponible durante el periodo "
            "critico de preparacion de la propuesta.\n"
            "- Falsos positivos en la deteccion de anomalias: riesgo tecnico a gestionar en el POC.\n"
            "- Restricciones de seguridad en las instalaciones del cliente (oil & gas): pueden "
            "limitar el acceso a redes y sistemas para la integracion.\n\n"
            "Accionables:\n"
            "- [Mariano/equipo tecnico] Enviar propuesta tecnica el viernes.\n"
            "- [Federico/equipo comercial] Enviar propuesta economica el martes siguiente.\n"
            "- [Equipo] Establecer mecanismo de coordinacion para reuniones con Contamara."
        ),
    },
]


async def main() -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    pipeline = IngestionPipeline(embedder=Embedder(api_key=settings.openai_api_key))

    async with session_factory() as db:
        for t in TRANSCRIPTS:
            print(f"Ingesting {t['source_id']} — {t['title']}...")
            result = await pipeline.ingest_raw(
                db=db,
                user_id=USER_ID,
                content=t["content"],
                source="fathom",
                source_id=t["source_id"],
                metadata={
                    "title": t["title"],
                    "date": t["date"],
                    "recording_url": f"https://fathom.video/calls/{t['source_id']}",
                },
            )
            print(f"  -> created={result.documents_created} updated={result.documents_updated}")
        await db.commit()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
