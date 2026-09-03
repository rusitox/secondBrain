"""Ingest Fathom transcripts batch 8 (recording 694461196 — Estrategia Vertical Oil & Gas)."""
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
        "source_id": "694461196",
        "date": "2026-06-23",
        "title": "Estrategia Vertical Oil & Gas — Plan de 3 Sesiones para Definir el Offering",
        "content": (
            "Meeting: Estrategia Vertical Oil & Gas — Plan de tres sesiones\n"
            "Date: 2026-06-23\n"
            "Participants: Gustavo Herrera, Sebastian Loizaga, Paula Vejrup, Naiara Acosta Najmanovich, "
            "Federico Valentino Lacoste, Mariano Ortega, Santiago Samra\n\n"
            "Contexto: Reunion para presentar y validar un plan de tres semanas para definir el offering "
            "de Flock en la vertical de Oil & Gas. El equipo viene de varios meses de reuniones comerciales "
            "en el sector y siente que necesita consolidar conocimiento interno y definir propuestas comerciales "
            "mas concretas antes de volver a los clientes.\n\n"
            "1. Plan de tres sesiones\n"
            "Paula y Sebastian presentaron el plan:\n"
            "- Sesion 1 (esta semana): introduccion a la industria de petroleo y gas para todo el equipo "
            "(I+D, produccion, comercial). Recorrido por la linea de valor del yacimiento: baterias, "
            "sala de control, etc. Sin codigo ni programacion; solo cultura general del sector.\n"
            "- Sesion 2 (semana siguiente): brainstorming con las problematicas recopiladas en los ultimos "
            "seis meses de reuniones con clientes + experiencia de Chevron. Identificar y priorizar "
            "tecnologias/soluciones aplicables al sector.\n"
            "- Sesion 3 (tercera semana): definicion del offering/entradas comerciales mas adecuadas. "
            "Priorizacion de productos y servicios para salir con la pata comercial.\n\n"
            "Gestion de contactos durante las tres semanas:\n"
            "- Pausar el offering de nuevas propuestas a clientes donde ya hubo varias reuniones "
            "(Vista, TecPetrol en otras lineas que no sea Trainly). No volver a esos con lo mismo "
            "mientras se analiza el offering.\n"
            "- Continuar con contactos donde no hubo mucho avance (CGC, Phoenix, PAE) o donde ya hay "
            "una oportunidad en curso (TecPetrol con Trainly, YPF).\n"
            "- Fatima y Jorge estan mapeando el universo de contactos en un Excel para evitar duplicar.\n\n"
            "2. Discusion estrategica con Gustavo\n"
            "Gustavo compartio sus perspectivas:\n"
            "- Le parece bien la iniciativa; la ventaja es que todo el equipo se alinea en el idioma "
            "del sector (como ocurrio con Fede que luego de 6 meses ya maneja el vocabulario de Oil & Gas).\n"
            "- Solicito que el equipo tecnico (Santi, Mariano, Nai) aporte tambien su vision: viabilidad "
            "tecnica de las iniciativas, que tiene recorrido y que no, para no seguir trabajando sobre "
            "cosas sin sentido.\n"
            "- El problema actual: el mensaje de Flock no esta siendo suficientemente acotado; "
            "se va a todo tipo de clientes con todo tipo de ofertas. Hay que definir concretamente "
            "que es lo que Flock ofrece.\n"
            "- Fede acotacion clave: el approach que cambia es dejar de intentar vender un producto "
            "terminado que no existe. Ahora el mensaje es claro: 'Soy experto en este problema + "
            "tengo la tecnologia para resolverlo. Si queres algo ya hecho, no soy para vos. "
            "Si queres que trabajemos juntos en la solucion, si puedo ayudarte.'\n"
            "- Gustavo: eso le sirve para filtrar oportunidades y medir cuan cerrable es cada una.\n\n"
            "3. Novedades de Gustavo\n"
            "- Proxima semana: reunion con dueno de empresa autopartista (industria, no Oil & Gas). "
            "Fede lo menciona como primera reunion generada por el; despues comunicara quienes pueden "
            "sumarse para darle continuidad. Las autopartistas tienen necesidades de datos e IA similares.\n"
            "- YPF: Gustavo generara nueva reunion con el contacto de YPF. Fatima mando un doc de "
            "credenciales para mostrar.\n"
            "- Crexel: avanzando hacia reunion de relevamiento. El contacto de Crexel (en Madrid) "
            "quiere mostrar algo rapido y seguir iterando. Lo ve auspicioso.\n"
            "- Tema politico/legal: hay algo en revision que cuando haya avance lo comunicara.\n\n"
            "4. Recomendacion de Gustavo para las sesiones\n"
            "- Invitar a perfiles que hoy no estan siendo contactados: directores de data, "
            "directores de innovacion en las petroleras.\n"
            "- Que el equipo de I+D pueda estar en esas reuniones con los directores para hacer "
            "un intercambio tecnico real (no que sean los comerciales solos tratando de vender "
            "tecnologia que no dominan completamente).\n"
            "- Reducir si es posible la duracion de cada sesion (1h30 parece mucho concentrado en "
            "tres semanas).\n\n"
            "Decisiones:\n"
            "- Plan de tres sesiones aprobado. Primera sesion este jueves.\n"
            "- Seba agenda las dos sesiones restantes.\n"
            "- Pausar offering de nuevas propuestas a clientes avanzados; continuar con el resto.\n"
            "- El equipo tecnico aportara vision de viabilidad tecnica a las sesiones.\n\n"
            "Accionables:\n"
            "- Seba: agendar sesiones 2 y 3 al terminar la reunion.\n"
            "- Fatima + Jorge: completar Excel de mapeo de contactos del sector.\n"
            "- Gustavo: generar nueva reunion con YPF; comunicar avances de Crexel y tema legal.\n"
            "- Fede: comunicar al equipo sobre la reunion con el autopartista; definir quienes se suman.\n"
            "- Seba/Pau: grabar las tres sesiones (Gustavo las veraen Fathom, no puede asistir "
            "al South Summit este jueves).\n"
            "- Equipo tecnico: preparar inputs para sesion 2 (viabilidad de iniciativas Oil & Gas)."
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
