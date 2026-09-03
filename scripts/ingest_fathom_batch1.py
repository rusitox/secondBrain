"""Ingest Fathom transcripts batch 1 (recordings 804960405, 804857547, 798084449)."""
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
        "source_id": "804960405",
        "date": "2026-08-31",
        "title": "Object Tracking / Retail Analytics Research — Flock IT",
        "content": (
            "Meeting: Object Tracking / Retail Analytics Research Presentation\n"
            "Date: 2026-08-31\n"
            "Recorded by: Mariano Ortega\n"
            "Participants: Luisina Giorgetti, Jorge Asfour, Emanuel Gutierrez, Matias Gasave, "
            "Santiago Samra, Marilyn Botheatoz, Fatima Bottero, Mariano Ortega\n\n"
            "Luisina presento resultados de investigacion sobre Object Tracking para retail analytics. "
            "La solucion usa tecnologia de seguimiento de objetos (YOLO, RoboFlow trackers) para "
            "identificar comportamiento de personas en entornos de retail, usando infraestructura "
            "de camaras de vigilancia existente.\n\n"
            "Componentes: Detector de objetos (bounding boxes, confianza), Tracker (asigna IDs, "
            "sigue cajas a lo largo del video), Pipeline completo (videos -> detecciones -> tracking "
            "-> heatmaps + metricas), Dashboard interactivo (personas, permanencia, ocupacion, flujo, heatmaps).\n\n"
            "Hipotesis validada parcialmente: tecnologia funciona para heatmaps y metricas de comportamiento "
            "reutilizando camaras existentes, pero KPIs tecnicos no alcanzaron umbral minimo.\n\n"
            "Problemas: cambios de ID en tracker, definicion de zonas afecta precision, calidad de detecciones.\n\n"
            "Diferencial competitivo vs Bcount, Retail Next, Foodfalcam:\n"
            "- Reutilizamos camaras de seguridad existentes (competencia vende hardware propio)\n"
            "- Customizacion total: podemos detectar cualquier objeto (montacargas, pistachos, etc)\n"
            "- Open source\n\n"
            "Posibles mejoras: fine-tuning del detector con imagenes propias, nuevas arquitecturas, "
            "mas algoritmos de tracking.\n\n"
            "Aplicaciones industriales: retail, logistica/depositos, aeropuertos, universidades, zonas industriales.\n\n"
            "Comercializacion: servicio de desarrollo customizado, no producto enlatado.\n\n"
            "Jorge pregunto sobre tracking en tiempo real (posible). Matias propuso logistica/depositos. "
            "Santiago menciono aeropuertos. Mariano: usar speech de infraestructura existente como diferencial comercial."
        ),
    },
    {
        "source_id": "804857547",
        "date": "2026-08-31",
        "title": "Checkpoint Mariano + Marilyn — Team Update Flock I+D",
        "content": (
            "Meeting: Weekly Checkpoint Mariano Ortega + Marilyn Botheatoz\n"
            "Date: 2026-08-31\n"
            "Participants: Mariano Ortega, Marilyn Botheatoz\n\n"
            "Newsletter y Playbook:\n"
            "- Newsletter: ongoing, terminar pronto. Automatizar para no requerir diseno manual cada mes.\n"
            "- Marilyn sube objetivos del equipo al portal/newsletter.\n"
            "- Playbook pendiente de feedback de Mariano (urgente, People presionando).\n"
            "- Feedbacks pendientes de Mariano: Mike, Lianzo, Dennis, Franco Samay.\n\n"
            "Agenda proxima semana:\n"
            "- 10 septiembre: reunion de Mariano con socios (no hay checkpoint).\n"
            "- 11 septiembre: cumpleanos de Marilyn, dia libre. Chicos hacen checkpoint con Mariano.\n\n"
            "Ronnie:\n"
            "- Volvio de vacaciones. Objetivo: cerrar POC Freegate definitivamente (1-2 semanas).\n"
            "- POC pistachos: armar propuesta tecnica interna, definir estrategia comercial.\n"
            "  Dudas de que cliente solo queria extraer conocimiento tecnico.\n\n"
            "Vision 360:\n"
            "- Equipo comercial sigue vendiendo. Reunion jueves con Expo Rural (empresa Abedis) para demo.\n"
            "- Mariano: comunicar a comerciales que producto esta frizado mientras se analiza.\n\n"
            "Tommy:\n"
            "- Tecpetrol: avanzando bien, solo USD 6 de tokens consumidos.\n"
            "- Iniciativa video para capacitaciones en Trainly: modelos multimodales (mas costosos).\n"
            "  Hacer prueba acotada (1 min de video).\n"
            "- Validacion con Seba y Pau antes de ir a cliente.\n"
            "- Falta: integracion captura de video. Proponer como iniciativa de gafas de realidad aumentada "
            "  (mas vendible para socios). Accionable: Tommy hacer mini-research de gafas AR y precio.\n\n"
            "LLM y costos:\n"
            "- Mariano recomienda GPT 5-6 Luna: 80% ahorro de costos, mas potente que GPT 4-O.\n"
            "- Open Router disponible para modelos alternativos (modelos chinos baratos).\n\n"
            "Bici: cerrando POC, capacitacion esta semana, charla para Flockers.\n\n"
            "Mati:\n"
            "- Robotica: desafio WiFi en robot.\n"
            "- Caso de uso Mariano: proponer 2-3 ideas avanzadas del robot (no solo control remoto) para ferias.\n"
            "- Monitor de Flock en casa para resolver tema ruleta y app viewer.\n\n"
            "Fran:\n"
            "- Cerrando documentacion etapa Agora.\n"
            "- Optimizacion de costos: convertir CVs a Markdown antes del modelo (reduce tokens).\n"
            "- Tommy tiene contexto del proyecto para cuando Fran este de vacaciones.\n"
            "- Fran se va de vacaciones desde el 7 de septiembre hasta finales de septiembre.\n"
            "- Reunion pendiente con Fede: definir si hacer punta a punta digital o mejorar usabilidad.\n\n"
            "Mike:\n"
            "- Recibio Oculus Meta Quest. Problema: vinculado a cuenta de Mati Serrano.\n"
            "  Propuesta: usar cuenta corporativa de IMAXDECO.\n"
            "- Bloqueante: Seba y Pau no definen experiencia de producto. Mariano: que siga generando assets.\n\n"
            "Denis:\n"
            "- Situacion compleja de gestion. Marilyn agotada de la carga.\n"
            "- People propone proceso de Performance Review (sin bonos, posible candidato a recorte).\n"
            "- Denis elige objetivos demasiado grandes, sin conciencia de sus limitaciones.\n"
            "- Autoevaluacion de Denis no alineada con la realidad.\n"
            "- Denis es persona con capacidades especiales. Empresa dice ser inclusiva pero sin playbook formal.\n"
            "- Marilyn necesita vacaciones de Denis, que no sea su responsabilidad por un tiempo.\n"
            "- Mariano: va a buscar opciones. Performance Review podria llevar a proceso de reubicacion.\n"
            "- Mariano tiene reunion con People al dia siguiente."
        ),
    },
    {
        "source_id": "798084449",
        "date": "2026-08-25",
        "title": "Reunion de Management — Naiara, Santiago, Mariano",
        "content": (
            "Meeting: Reunion de Management\n"
            "Date: 2026-08-25\n"
            "Participants: Naiara Acosta Najmanovich, Santiago Samra, Mariano Ortega\n\n"
            "Horas libres / bench:\n"
            "- Aproximadamente 500 horas libres actualmente.\n"
            "- Se arma grupo con Manu, Nati, Naiara y Mariano para asignacion de septiembre.\n"
            "- Proxima reunion con socios: van a preguntar por los cuanes (horas disponibles).\n\n"
            "Federacion (proyecto):\n"
            "- Avanzados, incluso por delante del cronograma.\n"
            "- Nuevo perfil Java incorporandose (reemplaza a empleado con 4 trabajos, despedido con causa).\n"
            "- Despido con causa comprobado via Nozis. Ejecutar cuando convenga.\n\n"
            "Clientes comerciales:\n"
            "- Caja: RFP presentado. Debate sobre credito de quien trajo el cliente (Accion vs Flock).\n"
            "- Tecpetrol: Agus lo ordeno en agosto. Deadline 3-4 semanas. Jorge vende mas horas en septiembre.\n"
            "- Adium: cliente pidio soluciones en entorno Microsoft (Power Apps + Copilot).\n"
            "  Workshop proxima semana para presentar resultados de consultoria de procesos. Mati vende post-workshop.\n"
            "- Presupuesto: objetivo de recortar aproximadamente USD 30.000.\n\n"
            "LLM y modelos:\n"
            "- Fran usa GPT 4-O para Agora (Naiara: ya esta muy atras).\n"
            "- Mariano recomienda GPT 5.6 Luna: 80% ahorro de costos.\n"
            "- Open Router con modelos chinos como alternativa barata.\n"
            "- Optimizacion: convertir CVs a Markdown antes del modelo para reducir tokens.\n\n"
            "Agora (plataforma de reclutamiento):\n"
            "- Busqueda para Patagonia/Colsen: 137-157 postulados, problema de filtrado corregido, relanzamiento proximo.\n"
            "- Wada tiene estrategia de alimentar mas partes del proceso con sistema multiagente.\n"
            "- Reunion pendiente con Fede para definir direccion del producto.\n"
            "- Mariano prepara presentaciones de ROI de iniciativas para mostrar a socios.\n"
            "- Accionable: presentar 2-3 iniciativas con Santiago y Naiara antes de ir a socios.\n\n"
            "Workshops:\n"
            "- Beringer: workshop 4 horas cancelado. Cliente quiere sesiones de 1 hora por perfil. Fecha pendiente.\n"
            "- Metalsa: pateado para septiembre. Fran Sampe da el workshop (vacaciones casi todo septiembre).\n"
            "  Accionable: coordinar fecha evitando vacaciones de Fran.\n\n"
            "Publicaciones LinkedIn:\n"
            "- Mariano pendiente de subir publicacion post-Expo Industria (viernes).\n"
            "- Agora debe ser mencionada como solucion desarrollada por Flock en publicaciones de clientes.\n\n"
            "Red comercial (Santiago):\n"
            "- Contactando 7-8 personas de su red, 4 por semana. Retomar contacto, ver oportunidades Flock.\n\n"
            "Google Manager:\n"
            "- Propuesta de pricing avanzando. Fati y Fede coordinando. Propuesta esta semana.\n\n"
            "Lucas / Banana (cliente externo):\n"
            "- Debate sobre proceso de trabajo. Lucas critico, Naiara hablo por telefono, quedo bien.\n"
            "- Lucas quiere framework de trabajo claro y puntos de control.\n"
            "- Percepcion: Lucas quiere armar empresa con Mati."
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
