"""Ingest Fathom transcripts batch 6 (recording 726577749 — Checkpoint Mariano + Marilyn pre-vacaciones)."""
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
        "source_id": "726577749",
        "date": "2026-06-29",
        "title": "Checkpoint Mariano + Marilyn — Pre-Vacaciones, Gestion del Equipo I+D",
        "content": (
            "Meeting: Checkpoint Mariano Ortega + Marilyn Botheatoz (pre-vacaciones de Marilyn)\n"
            "Date: 2026-06-29\n"
            "Participants: Mariano Ortega, Marilyn Botheatoz\n\n"
            "Contexto: Reunion de traspaso antes de que Marilyn se vaya de vacaciones ~15 dias "
            "(Amsterdam + Madrid). Fran queda como lead temporal del equipo I+D.\n\n"
            "1. Lista de pendientes para los proximos 15 dias\n"
            "- Reuniones con comerciales sobre aprobacion de iniciativa y definicion del modulo 1 (Agora).\n"
            "- Ronnie: setear compu en oficina, disponibilizar acceso a camaras (Vision 360 / Freegate).\n"
            "- Dennis y Matias: finalizar documentacion de sus POCs y dar reunion comercial con conclusiones.\n"
            "- Mike y Tommy: armar PPT de propuesta e iniciativa para VIA.\n"
            "- Mike: documentacion de meta formas terminadas (necesaria para reuniones comerciales).\n"
            "- Tommy: primer insight de validacion del equipo de Talent sobre Trainly.\n"
            "- Ronnie: conseguir feedback del area de industrias; definir si iniciativa Freegate/Vision 360 "
            "es viable.\n"
            "- Todo el equipo: cargar horas en la herramienta (reconocido como dificil de lograr).\n\n"
            "2. Fran como lead temporal\n"
            "Mariano pasa la lista de pendientes a Fran para que tenga visibilidad de lo que tiene que hacer el "
            "equipo. Marilyn expresa dudas sobre la capacidad de Fran de gestionar: despues de la reunion de "
            "Agora, Fran pregunto por Slack que tenia que hacer, mostrando dificultad para entender sus propias "
            "responsabilidades. Marilyn ve mas potencial de liderazgo en Ronnie a futuro.\n"
            "Decision: Mariano hace seguimiento primero a traves de Fran; si no funciona, se mete directamente.\n\n"
            "3. Ronnie — Vision 360 / Freegate Benchmark\n"
            "Mariano decide redirigir a Ronnie: en vez de solo trabajar con Freegate, le encarga:\n"
            "- Entender de que iba el producto Vision 360.\n"
            "- Analizar que ofrece Freegate en relacion a Vision 360.\n"
            "- Hacer un benchmark comparativo.\n"
            "Guille advirtio que Freegate es mas complejo de lo esperado (puede llevar varios dias).\n"
            "Mari habia puesto una semana; se puede extender si es necesario.\n\n"
            "4. Plan de accion — Reporte IA y sistema de tracking\n"
            "Marilyn mostro nueva funcionalidad del back office de I+D:\n"
            "- Antes: reporte mensual manual (porque no habia data de tareas de los chicos en junio).\n"
            "- Ahora: reporte generado con IA que cruza el log de tareas versus lo planificado.\n"
            "- El reporte detecta desvios concretos: 'fulanito cumplio/no cumplio, desvios: estos'.\n"
            "- Feature adicional: ability de poner un 'warning' en tareas que demoran mas de lo esperado, "
            "para enriquecer el reporte con feedback orientado al individuo.\n"
            "- Este reporte es interno (no lo ve Fede ni socios); sirve para dar feedback bien dirigido.\n\n"
            "5. Wiki de iniciativas en el back office\n"
            "Marilyn mostro la nueva seccion 'wiki' del back office:\n"
            "- Vista estructurada de cada etapa de la iniciativa con resumen de lo completado.\n"
            "- Pensada para compartir con comerciales (vista diferente al UI operativo).\n"
            "- Plan futuro: generador de presentaciones en HTML con prompting, usando la informacion "
            "ya cargada en la iniciativa.\n\n"
            "6. Situacion de Denis — Performance y comportamiento\n"
            "Marilyn reporto la situacion critica con Denis Perafan:\n"
            "- No esta trabajando: se conecta a las 5 de la tarde, no estuvo online en todo el dia, "
            "cuando se le asigna algo desaparece y al dia siguiente no entendio nada.\n"
            "- Actitud negativa: cuando se lo sumo a la herramienta de tracking (carga de horas), se enojo "
            "porque implica rendir cuentas. Trajo esa actitud a todas las dailies durante semanas.\n"
            "- El equipo lo nota y lo resiente: Yanzo le contesto con hostilidad cuando Denis le pidio "
            "feedback fuera de horario laboral el dia anterior a su presentacion.\n"
            "- Ausencias: se toma licencias por enfermedad frecuentemente, a veces desaparece sin formalizar. "
            "People (Laura) hace historia cuando hay muchas licencias activas.\n"
            "- Las chicas de People inauguraron un Excel en SharePoint para registrar ausencias de Denis "
            "sin que llegue al recibo (para tener un historial sin generar alarma inmediata).\n\n"
            "Decision de Mariano:\n"
            "- Tendra una charla motivacional con Denis en contexto de que Marilyn no esta.\n"
            "- Si no da vuelta la tortilla: activar proceso formal de mejora de performance (PIP).\n"
            "- El PIP lo asustara (Denis es recien padre), pero si no labura, no hay vuelta.\n"
            "- La reunion con People (pendiente) incluira este contexto.\n\n"
            "7. LEC / REP de Robotica\n"
            "Naiara pregunto si el REP (informe tecnico) de robotica y agentes que prepararon meses atras "
            "todavia sirve para presentar ahora.\n"
            "Marilyn confirmo que si: el contexto (robotica + agentes) sigue siendo relevante, "
            "y el Excel de soporte ya fue completado. Todo listo para presentarlo.\n\n"
            "Accionables:\n"
            "- Mariano: pasar lista de pendientes a Fran; hacer seguimiento del equipo via Fran.\n"
            "- Mariano: redirigir a Ronnie para benchmark Vision 360 vs Freegate.\n"
            "- Mariano: charla con Denis mientras Marilyn esta de vacaciones.\n"
            "- Mariano: reunion con People para tratar situacion de Denis.\n"
            "- Marilyn (viajes): Amsterdam + Madrid, 15 dias. Disponible por WhatsApp si urgente."
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
