"""Ingest Fathom transcripts batch 14 (recordings 617149952, 615893732, 606076550)."""
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
        "source_id": "617149952",
        "date": "2026-03-20",
        "title": "Reunion Semanal Vertical Industria 4.0 — Benoil, Trainly, Vision 360 y Plan Comercial",
        "content": (
            "Meeting: Reunion Semanal Vertical Industria 4.0 — Benoil, Trainly, Vision 360 y Plan Comercial\n"
            "Date: 2026-03-20\n"
            "Participants: Sebastian Loizaga, Paula Vejrup, Santiago Samra, Federico Valentino Lacoste, "
            "Mariano Ortega\n\n"
            "Contexto: Reunion semanal de la vertical de Industria 4.0 de Flock, previa a Semana Santa. "
            "Se revisan oportunidades activas, estado de productos y estrategia comercial.\n\n"
            "1. Propuesta Benoil — Discovery Oil & Gas\n"
            "La propuesta para Benoil esta casi cerrada. Se fusiono el rol de lider del proyecto "
            "con el analista funcional para mantener el precio por debajo de un umbral aceptable. "
            "Santiago recomienda incluir un checkpoint con el cliente al final de la semana 1 o 2 "
            "para validar alcance y evitar desvios. Plan: enviar mail previo a Gonzalo (contacto "
            "en Benoil) para mantener el interes, luego enviar la propuesta la semana siguiente.\n\n"
            "2. Estado de Clientes y Oportunidades Activas\n"
            "- Servipet: reunion agendada para despues de esta misma llamada. Foco en soluciones "
            "operativas (rutinas de campo, radio automatica), similar a lo trabajado con Tecpetrol.\n"
            "- Tecpetrol: tiene proyecto abierto de capacitaciones para equipos. Contactaron a "
            "Sebastian para mostrar Trainly/Cognify. Se necesita disponibilidad de Ruben "
            "para la semana siguiente.\n"
            "- Vista Energy: se mandara propuesta de acompanamiento. El contacto es un filosofo "
            "sin equipo a cargo ni area de sistemas propia. Estrategia: 'top of mind', ir mostrando "
            "propuestas constantemente hasta que surja oportunidad. No hay claridad sobre "
            "poder de decision o presupuesto del contacto. Mariano pide que se de visibilidad "
            "interna de las propuestas que circulen para detectar posibles bloqueos.\n"
            "- Plus Petrol: se haran adaptaciones al avatar/asistente de Vista para una "
            "presentacion en abril.\n"
            "- ProDem: empresa de boca de pozo interesada en el proyecto de fugas y derrames "
            "con camara dual (Geek Vision). Instalando la camara; se espera iniciar conversaciones "
            "la semana siguiente.\n\n"
            "3. Productos en Desarrollo\n"
            "- Trainly (ex Cognify): plataforma de entrenamiento con IA. En rediseno de UX. "
            "Un recurso del squad de productos dedicado.\n"
            "- Vision 360: otro recurso del squad terminando el Pitch Deck para salir a pitchear "
            "externamente. Rediseno en curso.\n"
            "- Fugas y derrames (Computer Vision): Luisina y Guille continuan con imagenes sinteticas "
            "como prioridad. Se perdio una licitacion anterior frente a un competidor que afirmo "
            "tener un modelo listo con las camaras existentes. Accion: indagar si ese competidor "
            "logro el objetivo prometido para re-evaluar el enfoque propio.\n\n"
            "4. Integracion de la Vertical con Flock\n"
            "La vertical Industria 4.0 comenzo a integrarse operativamente a Flock:\n"
            "- Desde el miercoles participan en la reunion de priorizacion comercial "
            "(con Mati, Nadia Rampa, Jorge).\n"
            "- Se detecto que las iniciativas de la vertical no estaban en el sistema de "
            "seguimiento de Flock ('el bot no las capturaba').\n"
            "- Se participara tambien en reuniones los viernes.\n"
            "- Proximo hito: presentacion formal de la vertical en el 'Flocky Day' de abril.\n\n"
            "5. Debate Estrategico: Cotizacion, POC y Relacion I+D/Operaciones\n"
            "Problema central: cuando llegan solicitudes al equipo tecnico, el contexto comercial "
            "no esta trasladado y se genera retrabajo. Falta un vinculo entre preventa e ingenieria.\n"
            "Postura de Sebastian: la vertical opera principalmente con I+D; Operaciones solo "
            "se involucrara como recurso puntual.\n"
            "POC gratuitas: el primer caso de exito justifica absorber el costo; no se puede "
            "regalar POC a todos los clientes. El costo de investigacion es de I+D; el de "
            "ejecucion con conocimiento adquirido es decision comercial.\n"
            "Fede propuso implementar niveles de descuento (politica comercial) para controlar "
            "cuantas POC se dan gratis y a quien.\n\n"
            "Decisiones:\n"
            "- Enviar mail a Gonzalo (Benoil) antes de la propuesta para mantener el interes.\n"
            "- Cerrar y enviar propuesta Benoil la semana siguiente.\n"
            "- Indagar si el competidor que gano en Tecpetrol fugas/derrames cumplio lo prometido.\n"
            "- Organizar reunion con Nai y Santi para revisar presupuesto anual y OKRs de I+D.\n"
            "- Armar plan comercial de 3 y 6 meses para la vertical.\n\n"
            "Accionables:\n"
            "- [Sebastian] Enviar mail a Gonzalo (Benoil) esta semana; confirmar rate de SCADA.\n"
            "- [Sebastian/Paula] Cerrar propuesta Benoil y enviarla la semana siguiente.\n"
            "- [Paula] Indagar resultado del competidor en proyecto fugas/derrames de Tecpetrol.\n"
            "- [Mariano] Confirmar estado de Vision 360 y Trainly; coordinar reunion con Nai "
            "y Santi para mostrar presupuesto y OKRs a la vertical.\n"
            "- [Vertical] Armar plan comercial 3/6 meses con foco en oil & gas + segunda industria.\n"
            "- [Sebastian] Coordinar reunion con Tecpetrol (capacitaciones) con Ruben.\n"
            "- [Todos] Preparar presentacion de la vertical para el Flocky Day de abril."
        ),
    },
    {
        "source_id": "615893732",
        "date": "2026-03-16",
        "title": "Revision Propuesta Discovery Benoil — Alcance, Equipo y Pricing",
        "content": (
            "Meeting: Revision Propuesta Discovery Benoil — Alcance, Equipo y Pricing\n"
            "Date: 2026-03-16\n"
            "Participants: Sebastian Loizaga, Paula Vejrup, Santiago Samra, Mariano Ortega\n\n"
            "Contexto: Reunion interna de Flock para revisar la propuesta de Discovery para Benoil "
            "(empresa de oil & gas). Se define alcance, equipo, timeline y pricing.\n\n"
            "1. Contexto y Origen de la Oportunidad\n"
            "Contacto: Gonzalo, gerente de infraestructura IT con background en operaciones de "
            "oil & gas. Necesidad inicial: analitica de video — Benoil tiene camaras en multiples "
            "yacimientos con distintos sistemas de visualizacion (foco en seguridad patrimonial) "
            "y quiere integrarlas. Benoil es una empresa nueva con foco en tecnologia para operar "
            "campos petroleros de manera eficiente. Tienen presupuesto asignado.\n"
            "Output esperado: propuesta de Discovery/Assessment que mapee todas las operaciones, "
            "identifique oportunidades, genere un plan de accion con recomendaciones y casos de "
            "negocio (impacto, costo).\n\n"
            "2. Alcance del Assessment\n"
            "Tres clusters geograficos: Santa Cruz (un cluster), Mendoza Sur y Mendoza Norte.\n"
            "Por cluster se relevara: telemetria y SCADA, sistemas heredados, infraestructura "
            "de comunicaciones, sistemas de video, nivel de integracion entre plataformas, "
            "disponibilidad y calidad de datos operativos (muchos son manuales), rutinas de "
            "operacion de campo, frecuencias de visita, gestion de alarmas, mantenimiento y "
            "confiabilidad, seguridad, monitoreo y procesos organizacionales.\n"
            "Entregables: diagnostico por cluster (madurez digital, brechas, casos de negocio, "
            "roadmap por activo) + vision integrada corporativa (benchmark interno, portfolio "
            "consolidado, roadmap corporativo con priorizacion de iniciativas).\n\n"
            "3. Modelo de Ejecucion y Tiempos\n"
            "Duracion total estimada: 8 a 12 semanas. Secuencial: semana de kickoff → "
            "relevamiento en campo por cluster (Mendoza Norte + Sur en una semana, Santa Cruz "
            "en otra) → semana de consolidacion → semanas de analisis y presentacion final.\n"
            "Las semanas de campo son full time. El equipo viaja desde Buenos Aires. Las "
            "locaciones a mas de 300 km se relevan con informacion provista por personal de campo.\n\n"
            "4. Equipo Propuesto\n"
            "- Lider de proyecto: Sebastian Loizaga (con expertise en oil & gas junto con Pablo).\n"
            "- Especialista Oil & Gas / Operaciones.\n"
            "- Arquitecto IoT / Video / IA: candidato interno Flock — Mati Araujo (primera opcion).\n"
            "- Especialista SCADA / IEC / OT: perfil externo (subcontratar), uno solo para los "
            "tres clusters para garantizar consistencia. A cotizar con contactos de Neuquen.\n"
            "- Analista funcional: integra los tres relevamientos (negocio, sistemas, infraestructura) "
            "y genera el mapa completo. Candidata mencionada: Brenda.\n"
            "Se decidio no cambiar el equipo a mitad del proyecto para evitar perdida de informacion.\n\n"
            "5. Pricing Preliminar\n"
            "Total estimado: USD 50.000.\n"
            "- Componente fijo base: USD 20.000.\n"
            "- Variable por cluster: Mendoza Norte USD 8.000, Mendoza Sur USD 8.000, "
            "Santa Cruz USD 12.000 (mayor logistica y distancias).\n"
            "- Viaticos a discutir (contra factura aparte).\n"
            "- Pendiente: simular costos reales de viaje y alojamiento.\n"
            "- Pendiente: cotizar costo/hora del consultor SCADA externo.\n\n"
            "Decisiones:\n"
            "- Enfoque modular por cluster con integracion final corporativa.\n"
            "- El especialista SCADA externo debe ser uno solo (no uno por provincia).\n"
            "- Se agrega el rol de analista funcional al equipo.\n"
            "- Sebastian asume el riesgo de estimacion y gestionara desviaciones con el cliente.\n"
            "- La memoria descriptiva (Word) con detalle del relevamiento se comparte al cliente "
            "junto con la presentacion PowerPoint.\n"
            "- Antes del kickoff se pedira al cliente el organigrama y estructura por cluster.\n\n"
            "Accionables:\n"
            "- [Paula] Preparar Excel de horas por perfil por semana; simular costos de viajes.\n"
            "- [Santiago] Conseguir costo por perfil en base al Excel; cotizar consultor SCADA "
            "externo con contactos de Neuquen.\n"
            "- [Sebastian] Agregar roles clave de entrevistados y seccion de informacion previa "
            "a recopilar en la propuesta; refinar schedule con bullets por semana.\n"
            "- [Mariano] Validar que el numero total hace sentido; aportar referencia de "
            "cotizaciones de Discovery anteriores si las hay.\n"
            "- [Equipo] Definir si el analista funcional es Brenda u otro perfil disponible; "
            "confirmar a Mati Araujo como candidato para rol IoT/arquitectura."
        ),
    },
    {
        "source_id": "606076550",
        "date": "2026-02-27",
        "title": "Preparacion Reunion TGS y Feedback Vaca Muerta Insights — Robot y Vision 360",
        "content": (
            "Meeting: Preparacion Reunion TGS y Feedback Vaca Muerta Insights — Robot y Vision 360\n"
            "Date: 2026-02-27\n"
            "Participants: Sebastian Loizaga, Matias Gasave, Mariano Ortega, Paula Vejrup, "
            "Guillermo Schettino\n\n"
            "Contexto: Reunion de preparacion para una reunion de discovery con TGS "
            "(Transportadora de Gas del Sur) y repaso del feedback del evento Vaca Muerta Insights.\n\n"
            "1. Feedback de Vaca Muerta Insights\n"
            "- El robot cuadrupedo mostro muy bien: con camara proyectando en un monitor, "
            "el equipo ponia una botella frente al perro y este se sentaba; ponia un vaso "
            "y se paraba. La analitica de personas en tiempo real funcionaba continuo. "
            "El equilibrio del robot llamo mucho la atencion.\n"
            "- Solucion tecnica: el robot usa dos camaras — una para la analitica (con cierto "
            "delay) y otra para la proyeccion en tiempo real. Con una sola camara el delay "
            "era de 5-10 segundos, inaceptable para una demo.\n"
            "- El stand tuvo impacto visual fuerte. Recomendacion para futuros eventos: "
            "pantalla bien grande para que lo que ve el perro sea visible al publico.\n"
            "- Varias oportunidades surgieron en el evento: empresa grande de servicios de "
            "operacion y mantenimiento en Vaca Muerta, empresa de servicios de agua de fractura, "
            "reunion con gerente de operaciones de Tecpetrol (quiere sacar las cosas ya, "
            "diferente timing que el grupo de Buenos Aires).\n"
            "- No quedaron en la licitacion de otro cliente (precio muy lejos de los "
            "competidores). Propuesta para reestructuracion: equipo de Flock con acciones "
            "in situ para conceptualizar iniciativas y generar proyectos.\n\n"
            "2. TGS (Transportadora de Gas del Sur) — Preparacion de Reunion\n"
            "Origen del contacto: Rodrigo Perez (Risk Manager de TGS) respondio a una campana "
            "de High Ticket de Flock. El mail hablo de sistema de camaras con IA: EPP, "
            "comportamientos riesgosos, escapes, fugas, incendios, 24/7.\n"
            "Interlocutores esperados:\n"
            "- Rodrigo Perez (Risk Manager, background completo en seguridad patrimonial).\n"
            "- Jorge Barajobre (jefe de infraestructura y servicios de IA, foco en SAP y BD).\n"
            "- Representante de Telcosur (empresa de TGS que provee servicios de drones e "
            "infraestructura para TGS y terceros).\n"
            "- Juan Cruz Taraski (lider clave).\n"
            "Duracion: 45 minutos. Formato esperado: exploratoria, no tecnica.\n\n"
            "3. Contexto Tecnico de TGS para Preparacion\n"
            "- Negocio: transporte de gas en alta y media presion; midstream; liquidos; telco. "
            "Infraestructura: kilometros de canerias en dos provincias, estaciones de "
            "recompresion, plantas de procesamiento de condensados.\n"
            "- Las plantas tienen poco personal; las lineas de canerias no tienen personal.\n"
            "- Para deteccion de fugas de gas (no visibles en termica): se usan camaras IR "
            "especificas o camaras FLIR de espectro especial (costo USD 10.000+ por camara). "
            "La camara termica convencional no sirve para gas no visible. Las camaras RGB "
            "tampoco detectan gas sin colorante.\n"
            "- Drones: Telcosur opera drones para inspeccionar lineas y plantas. En el evento "
            "VMI habia una empresa con dron + camara FLIR para deteccion de emisiones.\n"
            "- No tiene sentido competir con Telcosur en servicios de drones ya que es la "
            "empresa propia de TGS.\n\n"
            "4. Estrategia para la Reunion TGS\n"
            "Recomendacion de Matias Gasave:\n"
            "- Arrancar con una gran introduccion y presentacion de la vertical Industria 4.0.\n"
            "- Capitalizar la presencia en Vaca Muerta Insights para mostrar que Flock "
            "conoce el negocio (no son paracaidistas).\n"
            "- Mostrar el video/fotos del robot en el evento para generar credibilidad.\n"
            "- Luego mostrar el abanico de offerings de la vertical y hacer demos.\n"
            "- Indagar sobre Telcosur para entender capacidades y cómo complementarse.\n"
            "Recomendacion de Mariano: no entrar en reunion tecnica; si surgen preguntas "
            "tecnicas, responder brevemente y proponer una reunion tecnica especializada. "
            "Objetivo: exploratoria, identificar puntos de interes, donde haya interes hacer "
            "doble click con una reunion especifica.\n"
            "Vision 360 + Sistemas Multiagentes: propuesta de Mariano de mencionar la "
            "combinacion de analitica de video con sistemas multiagentes para detecciones "
            "operativas — generalmente atractivo para el sector.\n\n"
            "5. Totem Praia en Aeroparque\n"
            "Matias Gasave visito el Aeroparque el dia anterior y vio el totem de Praia. "
            "Esta mal ubicado: contra una pared del mismo color, en el area de cintas de "
            "valijas, donde nadie se detiene. Esta pasando completamente desapercibido. "
            "Matias tiene reunion al dia siguiente con el area de IT y Experiencia del "
            "aeropuerto; usara esta informacion para sugerir una mejor ubicacion y hacer "
            "un pitch mas estructurado sobre el valor del producto.\n\n"
            "Decisiones:\n"
            "- Reunion TGS: exploratoria, presentar el abanico completo de offerings, "
            "capitalizar la presencia en VMI, no entrar en detalle tecnico.\n"
            "- Para futuros eventos: pantalla grande para el robot + analitica visible.\n"
            "- No competir con Telcosur en drones; buscar complementariedad.\n\n"
            "Accionables:\n"
            "- [Sebastian] Pasar fotos/videos del robot en VMI a Matias para la reunion TGS.\n"
            "- [Paula] Confirmar duracion exacta de la reunion TGS (45 minutos confirmados).\n"
            "- [Matias] Preparar pitch estructurado para aeropuerto usando observacion del totem; "
            "sugerir mejor ubicacion del totem en la reunion con IT y Experiencia.\n"
            "- [Equipo] Si hay nuevos invitados a TGS, Matias avisa antes de la reunion.\n"
            "- [Seba] Investigar el dron de Telcosur y sus capacidades; ver si se puede "
            "complementar con analitica de IA."
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
