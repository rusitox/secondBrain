"""Ingest Fathom transcripts batch 4 (recording 729879159 — PAI System demo)."""
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
        "source_id": "729879159",
        "date": "2026-06-30",
        "title": "Demo PI System AVEVA — TECPE / Cristian ACCIONA IT",
        "content": (
            "Meeting: Demo PI System AVEVA\n"
            "Date: 2026-06-30\n"
            "Participants: Cristian (ACCIONA IT), Sebastian Loizaga, Guillermo Schettino, "
            "Santiago Samra, Lucas Mujica, Mariano Ortega\n\n"
            "Contexto: Cristian de ACCIONA IT hace una demo del PI System (by AVEVA) al equipo de Flock. "
            "El objetivo es entender la plataforma de datos industriales usada en TECPE para evaluar "
            "oportunidades de integracion con soluciones de IA (proyecto PAI).\n\n"
            "PI System — Arquitectura general:\n"
            "- Plataforma de datos industriales de AVEVA (ex OSIsoft)\n"
            "- Flujo: adquisicion desde red OT via protocolo OPC -> Data Archive (historizacion) "
            "-> Asset Framework (contextualizacion) -> PI Vision (visualizacion)\n"
            "- PI Points: variables que se historiza. En TECPE: 50.000 PI Points (46.000 activos en uso)\n"
            "- Interfaz PI Vision: dashboards configurables, similar a Grafana pero especifico para industria\n\n"
            "Implementacion en TECPE:\n"
            "- Equipo: 2 personas + 1 interno\n"
            "- Tareas diarias: agregar PADs (puntos de adquisicion de datos), integraciones "
            "(ej: API Enerflex via Node-RED), analitica (ecualizacion de pozos), "
            "stored procedures SQL para Power BI\n"
            "- Integracion con APIs externas: Node-RED como middleware para APIs sin soporte nativo PI\n"
            "- Analytics en PI: motor muy limitado (no soporta loops ni arrays). "
            "Para analitica compleja usan SQL/Power BI\n\n"
            "Limitaciones criticas:\n"
            "- Motor de analytics de PI muy limitado: no soporta loops, arrays, logica compleja\n"
            "- Espacio en disco cerca de capacidad maxima\n"
            "- PI Connect (sucesor cloud): demasiado caro, modelo de creditos por acceso a variable. "
            "Descartado por Tecpetrol\n\n"
            "Evolucion tecnologica:\n"
            "- Tecpetrol integrando Cognite encima de PI (capa de datos moderna sobre infraestructura existente)\n"
            "- Cristian tiene certificaciones PAI/AVEVA\n\n"
            "Oportunidades para Flock / proyecto PAI:\n"
            "- Las limitaciones del motor de analytics de PI abren espacio para soluciones de IA externas\n"
            "- Posibilidad de consumir datos de PI System via API para alimentar modelos de ML/IA\n"
            "- Node-RED ya usado como middleware: punto de integracion natural\n"
            "- Cristian identificado como recurso tecnico clave con conocimiento PI System + contexto TECPE\n\n"
            "Accionables:\n"
            "- Evaluar arquitectura de integracion PI System -> Flock PAI service\n"
            "- Cristian disponible para dimensionar trabajo tecnico de propuestas PAI\n"
            "- Considerar Cognite como capa alternativa de datos si Tecpetrol avanza con esa migracion"
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
