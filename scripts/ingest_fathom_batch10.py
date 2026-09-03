"""Ingest Fathom transcripts batch 10 (recording 662310775 — POC Proden fugas y derrames)."""
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
        "source_id": "662310775",
        "date": "2026-05-14",
        "title": "POC Proden — Revision Videos Fugas y Derrames, Organizacion del Proyecto",
        "content": (
            "Meeting: POC Proden — Revision de videos de fugas y derrames, organizacion del proyecto\n"
            "Date: 2026-05-14\n"
            "Participants: Sebastian Loizaga, Guillermo Schettino, Paula Vejrup, Mariano Ortega, "
            "Luisina Giorgetti\n\n"
            "Contexto: Reunion de revision del estado de la prueba de concepto (POC) con Proden para "
            "deteccion de fugas y derrames en pozos petroleros mediante Computer Vision (camaras RGB y "
            "termicas). El equipo revisa los videos recibidos del cliente y discute los proximos pasos "
            "del proyecto.\n\n"
            "1. Videos recibidos de Proden — Revision de calidad\n"
            "Proden realizó simulaciones controladas de derrames (purga y uso de pava con agua caliente) "
            "frente a la boca del pozo. Guille mostro los videos en pantalla.\n"
            "- Camara RGB (vigilancia): muy buena calidad, mucho detalle. Util para entrenamiento "
            "del modelo.\n"
            "- Camara termica: calidad mala en comparacion con RGB. Mucho zoom que no estaba en la "
            "documentacion inicial; posiblemente mal configurada.\n"
            "- El derrame simulado se ve como un manchon de agua en el piso, dificil de distinguir de "
            "lluvia o charco comun.\n"
            "- Las pruebas tardaron tres semanas para realizarse (dos botas de agua simuladas).\n"
            "- Limitacion de la camara: sin SD de suficiente capacidad; se borra cada 6-7 horas "
            "(9 GB). Los videos llegan via Drive en tramitos.\n\n"
            "2. Debate sobre el alcance del POC\n"
            "Alcance original acordado: Proden manda imagenes/videos -> Flock genera imagenes sinteticas "
            "y dataset -> entrena modelo de deteccion de fugas y derrames + EPP.\n"
            "Guille: la camara termica se ve muy mal; podria empezarse con RGB y sumar la termica "
            "despues. Pedir mas simulaciones, mas grande y con mejor configuracion de zoom.\n"
            "Seba: quiere conectarse directamente al stream de la camara para no depender de que el "
            "cliente baje y suba los videos. El proceso actual es muy lento.\n"
            "Guille: conectarse al stream requiere que el cliente genere una VPN externa (no probable "
            "sin contrato formal) y ademas habria que gestionar un backend para recibir el video "
            "de manera estable.\n"
            "Mariano: el stream seria un 'extra' fuera del alcance original del POC. Por ahora, "
            "hay que trabajar con lo que se tiene + pedir mas simulaciones. La VPN puede "
            "gestionarse en paralelo, pero no puede bloquear el POC.\n"
            "Conclusion: hacer dos carriles en paralelo:\n"
            "1. Continuar con el alcance original (videos actuales + generacion de imagenes sinteticas "
            "+ entrenamiento de modelo).\n"
            "2. Gestionar en paralelo el acceso al stream via VPN (se plantea como necesidad al cliente, "
            "no como bloqueante).\n\n"
            "3. Organizacion del proyecto y gestion del equipo\n"
            "Mariano propuso organizar el POC como proyecto formal:\n"
            "- Designar un Team Manager. Candidato natural: Agus Villegas "
            "(muy bueno en gestion de proyectos con Jira, habia consultado si habia algo para arrancar).\n"
            "- Hacer un kickoff formal con el cliente (Proden quiere juntarse para ver como siguen): "
            "en ese kickoff presentar el plan validado internamente, mostrar cuales son los "
            "entregables, la planificacion y las expectativas.\n"
            "- Agus debe ponerse al tanto de todo el contexto del POC antes de organizar el kickoff.\n"
            "- Antes del kickoff: alinear internamente si hacen falta mas pruebas/simulaciones del "
            "cliente; si las hay, comunicar concretamente al cliente que pruebas necesitan y por que.\n\n"
            "Decisiones:\n"
            "- Agus Villegas toma el rol de Team Manager del POC con Proden.\n"
            "- Se organiza un kickoff formal con Proden donde se presenta el plan, entregables y "
            "planificacion del proyecto.\n"
            "- Poner en stand-by la reunion que queria organizar Seba hasta que Agus se empape del "
            "contexto y ayude a planificar bien las tareas.\n"
            "- Trabajar con los videos existentes + pedir simulaciones adicionales mas grandes y "
            "con configuracion de camara corregida (especialmente la termica).\n"
            "- Gestionar en paralelo el acceso al stream de la camara (no bloqueante para el POC).\n\n"
            "Accionables:\n"
            "- Mariano: hablar con Agus y Rampa para ponerlos al tanto del contexto del POC.\n"
            "- Guille: contactar al tecnico de Proden (Inaki) para revisar la configuracion de la "
            "camara termica (zoom mal configurado) y pedir acceso a mas videos.\n"
            "- Agus: ponerse al tanto del alcance del POC y ayudar a planificar las tareas con fechas.\n"
            "- Equipo: definir si se necesitan mas simulaciones del cliente y comunicarselo "
            "concretamente antes del kickoff."
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
