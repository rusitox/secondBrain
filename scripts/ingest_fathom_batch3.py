"""Ingest Fathom transcripts batch 3 (recordings 751256472, 749909979)."""
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
        "source_id": "751256472",
        "date": "2026-07-17",
        "title": "Reunion Comercial — Trendly World Life, PAI, Expo Industrias",
        "content": (
            "Meeting: Reunion Comercial\n"
            "Date: 2026-07-17\n"
            "Participants: Mariano Ortega, Santiago Samra, Sebastian Loizaga, Paula Vejrup, "
            "Federico Valentino Lacoste\n\n"
            "1. Propuesta comercial para World Life / Trendly (licencia perpetua, USD 15.000)\n"
            "Se discutio el estado de la propuesta de licencia de Trendly para World Life.\n"
            "Punto central: necesidad de incluir en la propuesta costos de infraestructura y LLMs "
            "para que el cliente entienda el costo total de ownership.\n"
            "Analogia: vender un auto sin decir cuanto sale la nafta.\n\n"
            "Decisiones:\n"
            "- Mariano pasa durante el dia: orden de magnitud de horas de implementacion, "
            "onboarding, descripcion de infraestructura actual.\n"
            "- Onboarding: modelo 'train the trainers', una semana para capacitar a 3 personas internas.\n"
            "- Tarifa objetivo: USD 13.000-15.000 incluyendo onboarding e implementacion.\n"
            "- Costo de desarrollo distribuido entre 3 a 5 clientes (no impactar 100% a uno solo).\n"
            "- Licencia perpetua sobre snapshot actual del producto. Reventa no incluida.\n"
            "- Futuras mejoras cotizan aparte como PI del cliente o pricing compartido.\n"
            "- Riesgo: multiples instancias de Trendly en diferentes estados de evolucion. "
            "Vision futura: arquitectura centralizada con feature toggling.\n\n"
            "2. Servicio PAI (inteligencia artificial para operaciones)\n"
            "Chevron y otros clientes mostraron interes.\n"
            "Problema: falta recurso tecnico disponible.\n"
            "Cristian (en TECPE via Trace Group) identificado como unico con conocimiento para armar propuestas.\n"
            "Decisiones:\n"
            "- Sebastian convoca a Cristian para dimensionar trabajo tecnico.\n"
            "- Fede sugiere blanquearle a Cristian el contexto estrategico (crecimiento, rol clave, compensacion).\n"
            "- Para cotizaciones formales: sumar a Fati o Jorge en el lado comercial.\n\n"
            "3. Avance de obra / Computer Vision\n"
            "Se descarto monitoreo de avance de obra con camaras fijas (tecnologia insuficiente, "
            "no reemplaza al inspector).\n"
            "Se abre exploracion con imagenes satelitales (Sentinel como proveedor a explorar).\n"
            "Plus Petrol pasa coordenadas de una linea para prueba piloto.\n"
            "Techin pidio monitoreo de productividad (tiempos perdidos, no avance de obra).\n\n"
            "4. NDA con TECPE / ACCIONA\n"
            "NDA frenado: contrato involucra a FLOG Sistemas SRL bajo ACCIONA, inconsistencia legal.\n"
            "Resolucion para el martes.\n"
            "Sebastian mantiene fecha del 27 de julio para viajar a Neuquen.\n\n"
            "5. Expo Industrias\n"
            "Evento anual: 10.000 participantes, 400 empresas en ronda de negocios, 150 stands.\n"
            "Sin predominio de empresas de tecnologia.\n"
            "Natalia (marketing) ya en contacto con la organizacion.\n"
            "Decisiones:\n"
            "- Paula coordina con Nati para opciones de stand, costos y plazos.\n"
            "- Santiago prepara 3-4 guiones cortos de presentacion.\n"
            "- Demos reales: perro robot (Computer Vision en vivo), Trendly, Vision 360, Agora, robot Praia.\n"
            "- No se desarrolla nada nuevo, se trabaja con lo existente mas piezas visuales y videos.\n"
            "- Federico necesita borrador del plan para mediados de semana siguiente (presentar a socios el jueves).\n"
            "- Santiago menciono capacitacion en IA como producto productizable, bajo costo (USD 1.000-2.000).\n\n"
            "Accionables:\n"
            "- Mariano: enviar paquete de costos/implementacion para propuesta World Life.\n"
            "- Sebastian: contactar a Cristian para propuestas de PAI.\n"
            "- Sebastian: pasar coordenadas Plus Petrol para imagen satelital.\n"
            "- Paula: coordinar Expo Industrias con Nati.\n"
            "- Santiago: preparar guiones para Expo Industrias.\n"
            "- Fede: presentar plan Expo Industrias a socios el jueves."
        ),
    },
    {
        "source_id": "749909979",
        "date": "2026-07-16",
        "title": "Reforecast 2026 — Reunion Financiera Flock / Acciona",
        "content": (
            "Meeting: Presentacion Reforecast 2026\n"
            "Date: 2026-07-16\n"
            "Participants: Agustina Fontanals, Veronica Alegre, Ines Grotz, Federico Valentino Lacoste, "
            "Naiara Acosta Najmanovich, Mariano Ortega, Gustavo Herrera, Matias Loizaga, Belen Fernandez\n\n"
            "Contexto: Presentacion del Reforecast 2026 del grupo empresarial (Flock, Acciona, Acciona Chile, "
            "aFactory, SingularMind, Intersoftware). Reunion formal de analisis financiero.\n\n"
            "Resultados del Reforecast 2026 — Flock:\n"
            "Tres segmentos: Federacion Patronal (staffing principal), Provision de Personas "
            "(Metrogas, Turan, Cencosud, Citibank), Desarrollo y Nuevas Tecnologias.\n"
            "- Federacion Patronal: +55% facturacion en dolares, +32% horas vendidas. Mejor tarifa con menos horas.\n"
            "- Provision de Personas: +6% facturacion, +6% horas.\n"
            "- Desarrollo y Nuevas Tecnologias: -24% facturacion, -37% horas vendidas.\n\n"
            "Problema estructural critico:\n"
            "A medida que bajan las horas de Federacion Patronal (tendencia decreciente desde octubre), "
            "quedan ~13 colaboradores sin asignacion en marzo mas 5 en bench.\n"
            "Estos flockers pasarian a proyectos de nuevas tecnologias pero con tarifa mucho menor.\n"
            "Esto comprime la rentabilidad de Flock drasticamente.\n\n"
            "Proyecciones criticas:\n"
            "- Rentabilidad neta de Flock en Q1 siguiente: ~1,6% (vs 26% en 2026).\n"
            "- Para volver al 25% de rentabilidad neta: necesita USD 200.000/mes adicionales en nuevas tecnologias.\n"
            "- Para rentabilidad del 10%: necesita al menos USD 310.000/mes. Hoy factura ~USD 15.000 en ese segmento.\n"
            "- Eliminando 100% del costo de personal sin asignacion: rentabilidad llega a 4,4%, aun insuficiente.\n\n"
            "Otras unidades del grupo:\n"
            "- Acciona: +11,9% facturacion real (enero-abril). Nómina: 229 a 290 personas al anio. "
            "Crecimiento en Medicus (+7), Behringer (+7), Carrefour (+4).\n"
            "- Acciona Chile: +52% facturacion.\n"
            "- SingularMind/Intersoftware: -31%.\n"
            "- aFactory: +15%.\n\n"
            "Estructura de costos — ahorros vs presupuesto original:\n"
            "Ahorro total: USD 43.000 / ARS 693M.\n"
            "- I+D: ARS 230M menos (nomina 9 vs 11 planificadas; postergacion compra humanoide).\n"
            "- Marketing: ARS 143M menos (ingreso de responsable demorado a junio).\n"
            "- Comercial: ARS 189M menos (equipo demorado; sin servicios de prospeccion ni viajes).\n\n"
            "Resultado consolidado grupo 2026:\n"
            "- EBITDA anual: USD 4,7M con equipo I+D; USD 5,3M sin I+D.\n"
            "- Q1 siguiente: EBITDA 10%, resultado final del grupo 6%.\n"
            "- Rentabilidad Acciona: 23,3% estable. Rentabilidad Flock Q1: 4%.\n\n"
            "Discusion estrategica:\n"
            "- Ines Grotz: necesidad de actuar ya, no solo proyectar.\n"
            "- Pipeline de Computer Vision y desarrollo grande en papel, pero cae semana a semana.\n"
            "- Ciclos de cierre de proyectos de desarrollo: 4 a 6 meses (dificulta conversion rapida).\n"
            "- Se necesitan ~USD 350.000/mes adicionales para alcanzar objetivo de rentabilidad.\n"
            "- Gustavo: cada area identifica impacto concreto que puede generar (venta o costos).\n"
            "- Mariano: falta informacion sobre que bloquea el cierre en el pipeline de Computer Vision.\n"
            "- Comerciales solos no pueden defender propuestas tecnicas ante heads de innovacion; "
            "necesitan mas soporte tecnico en reuniones de venta.\n"
            "- Federico: posibilidad de buscar financiamiento externo para I+D (formato startup).\n"
            "- Hay reserva acumulada desde hace mas de un anio para eventualidades.\n\n"
            "Decisiones y proximos pasos:\n"
            "- Definir rentabilidad piso para el grupo y para Flock.\n"
            "- Armar plan de accion con escenarios (Plan A, B, C): venta agresiva + posible reduccion "
            "de estructura si metas no se cumplen.\n"
            "- Puntos de control mensuales para monitorear variables clave.\n"
            "- Naiara: nuevos objetivos de facturacion y analisis de conversion del pipeline.\n"
            "- Revisar verticales: decidir cuales continuar y cuales pausar.\n"
            "- Explorar oportunidades en EE.UU., Chile y Espana.\n"
            "- Proxima reunion: primera semana de agosto con plan de accion completo."
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
