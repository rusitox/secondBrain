"""Ingest Fathom transcripts batch 11 (recordings 662255712, 654146921, 654050542)."""
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
        "source_id": "662255712",
        "date": "2026-05-05",
        "title": "Trainly POC TecPetrol y Feedback Demo Pampa Energy — Estrategia de Producto",
        "content": (
            "Meeting: Revision de la POC de Trainly para TecPetrol y feedback de la demo con Pampa Energy\n"
            "Date: 2026-05-05\n"
            "Participants: Sebastian Loizaga, Mariano Ortega, Marilyn Botheatoz, Paula Vejrup\n\n"
            "Contexto: Reunion de equipo para revisar el estado de la POC de Trainly con TecPetrol "
            "(que se hara ese mismo dia), el feedback de la demo con Pampa Energy, y definir la "
            "estrategia de producto y expectativas para los clientes.\n\n"
            "1. Feedback de la demo con Pampa Energy\n"
            "Pampa Energy mostro interes en una plataforma de capacitacion con funcionalidades "
            "avanzadas. Sus pedidos principales:\n"
            "- Organizacion de cursos por roles y cronogramas anuales de capacitacion.\n"
            "- Matriz de competencias: asignar niveles de expertise requeridos por puesto/rol, "
            "con cursos asignados automaticamente segun las competencias que faltan.\n"
            "- Generacion de videos como fuente de capacitacion.\n"
            "- Gestion de competencias: nivel basico, intermedio, avanzado segun funcion.\n"
            "- Soporte a SCORM (formato estandar de eLearning).\n"
            "Pampa Energy ya tiene sistemas de capacitacion en funcionamiento; buscaba algo ya "
            "desarrollado y probado en produccion, no algo en desarrollo.\n"
            "Marilyn: la expectativa de Pampa era ver un producto maduro ya caminando con usuarios. "
            "La impresion fue que Trainly esta en etapa de desarrollo activo.\n"
            "Mariano: hay dos tipos de clientes: Pampa (quieren producto listo) y Syngenta "
            "(dispuesta a co-construir y ve valor en participar del desarrollo).\n"
            "Syngenta: ya conoce como funciona Flock, entiende que Trainly esta en estadio de "
            "desarrollo activo, y lo ve como ventaja (puede pedir lo que necesitan).\n\n"
            "2. Estrategia para la POC de TecPetrol (ese dia)\n"
            "La propuesta de POC ya fue armada y enviada por Jorge para comentarios.\n"
            "Marilyn: el compromiso de I+D para la POC ya esta definido en el documento acordado. "
            "Prioridad: que la app funcione perfectamente para los 5 usuarios asignados, con los "
            "agentes existentes y la asignacion de roles. No agregar features nuevas que no estaban "
            "en el alcance acordado.\n"
            "Seba queria agregar features (como la matriz de competencias) para mejorar las chances "
            "de ganar la POC. Marilyn: hay que separar POC (puesta en produccion de la cascara "
            "actual) de evolutivos (features nuevas). No mezclarlos.\n"
            "Mariano: si se van a agregar features, hacerlas internamente primero, validar que "
            "funcionan, y recien entonces habilitarlas para la POC. No comprometerse con el cliente "
            "en algo no testeado.\n"
            "Decision: mostrar en la reunión de POC cuales son las funcionalidades actuales y "
            "cuales estan 'work in progress', manejando las expectativas del cliente correctamente.\n\n"
            "3. Funcionalidades en desarrollo\n"
            "En progreso activo:\n"
            "- Edicion de cursos (Tommy trabajando en eso)\n"
            "- Soporte a multiples archivos por curso\n"
            "- Generacion de presentaciones/videos desde la plataforma (complejidad alta, sin "
            "timeline definido; modelos de vision de Google no estan abiertos al publico)\n"
            "Matriz de competencias: factible, complejidad de UX/UI mas que tecnica. Marilyn quiere "
            "involucrar a Ianzo para disenarlo bien antes de implementarlo.\n\n"
            "4. Gestion de expectativas con el cliente\n"
            "Antes de que los usuarios de TecPetrol comiencen a usar la plataforma:\n"
            "- Hacer un onboarding obligatorio para evitar frustracion con lo que aun no esta.\n"
            "- Comunicar claramente el alcance actual y las funcionalidades que vienen.\n"
            "- TecPetrol pidio que Flock les presente los cursos precargados; esto les evita "
            "el problema de los tiempos de generacion de cursos.\n\n"
            "Accionables:\n"
            "- Tommy: continuar desarrollo de edicion de cursos y multiples archivos.\n"
            "- Marilyn: involucrar a Ianzo para diseno UX de matriz de competencias.\n"
            "- Equipo: preparar un documento de expectativas / roadmap para mostrar a clientes "
            "(que funcionalidades hay, cuales vienen).\n"
            "- Seba + Mariano: onboarding para usuarios de TecPetrol antes de dar acceso."
        ),
    },
    {
        "source_id": "654146921",
        "date": "2026-04-28",
        "title": "Framework I+D IMAXD — Revision y Consolidacion con Naiara y Santiago",
        "content": (
            "Meeting: Revision y consolidacion del framework de I+D de Flock — comparacion entre "
            "el framework ERSAP de Naiara y el framework detallado de Mariano\n"
            "Date: 2026-04-28\n"
            "Participants: Mariano Ortega, Naiara Acosta Najmanovich, Santiago Samra\n\n"
            "Contexto: Reunion de equipo para revisar y unificar los dos documentos del framework "
            "de I+D que habian armado Naiara (presentacion ERSAP) y Mariano (framework detallado "
            "con checklists por etapa). El objetivo es tener una version unificada para presentar "
            "tanto al equipo comercial (ese jueves) como a los socios (semana siguiente).\n\n"
            "1. Presentacion del framework ERSAP (Naiara)\n"
            "Framework armado con Claude Design. El nombre 'ERSAP' se puede cambiar. Todo en ingles "
            "para que 'suene fancy'. Estructura de la presentacion:\n"
            "- Slide 1: descripcion del framework. Misión: identificar y validar tecnologias con "
            "potencial de negocio, llevarlas a soluciones para clientes reales via MVP y ventas "
            "tempranas, abstraer y detectar patrones, evaluar como candidato a producto, construir "
            "business case y decidir la graduacion al producto.\n"
            "- 4 pasos del area de I+D: (1) Definir tecnologia + business case, (2) Aprobacion, "
            "(3) Investigacion + demo, (4) Pendiente de agregar (transferencia).\n"
            "- 3 gates de decision: aprobacion de la tecnologia (la investigacion se alinea con "
            "la estrategia), candidato a producto (la solucion se abstrae y escala mas alla del "
            "cliente), graduacion al producto (el business case justifica la inversion).\n"
            "- Roles en el proceso: I+D (descubre, transfiere), Comercial (valida en el mercado, "
            "vende, ejecuta MVP, expande a 3 clientes), Management (decide la graduacion, define "
            "si es candidato a producto), Producto (construye business case, analiza benchmark, "
            "genera el product business case).\n\n"
            "2. Framework detallado de Mariano (5 etapas)\n"
            "Mariano presento su version con mucho mayor nivel de detalle por etapa:\n"
            "- Etapa 1 (Problema/Hipotesis): Inputs = oportunidad, deteccion de un dolor, "
            "oportunidad comercial, paper/benchmark, sponsor, vertical. "
            "Decisiones: que problema investigar, que hipotesis validar, que resultado minimo "
            "indicaria que vale la pena seguir, que queda dentro/fuera, nivel de prioridad. "
            "Entregable: research brief (hipotesis, KPIs, criterios go/no-go, stakeholders).\n"
            "- Etapa 2 (Investigacion): Diseno del experimento, arquitectura candidata, recursos, "
            "restricciones tecnicas, alternativas descartadas. "
            "Entregable: plan de implementacion.\n"
            "- Etapa 3 (Implementacion): No se busca un producto final sino un artefacto suficiente "
            "para validar la tecnologia. Entregable: prototipo o POC, demo tecnica, repo, dataset, "
            "logs y trazabilidad, documento tecnico de implementacion.\n"
            "- Etapa 4 (Validacion): Evidencia para decidir si la linea de investigacion continua, "
            "pivotea, se convierte en producto/capacidad o se descarta. "
            "Incluye posibilidad de pivot (hipotesis falla pero aparece otra oportunidad -> volver "
            "al ciclo 1-4). Entregable: informe de validacion con evidencia cuantitativa/cualitativa, "
            "decision recomendada, backlog de mejoras.\n"
            "- Etapa 5 (Insights y transferencia): La investigacion se transforma en una capacidad "
            "interna, componente reutilizable, demo comercial, paper, landing, propuesta para cliente "
            "o nueva linea futura de I+D. Recien aca termina para IMAXD y entra el flujo comercial.\n\n"
            "3. Debate sobre go/no-go de cada etapa\n"
            "Etapa 1 go/no-go: no avanzar si el problema es ambiguo, no hay hipotesis verificable, "
            "no hay impacto potencial, requiere recursos imposibles, no hay datos ni forma de "
            "conseguirlos.\n"
            "Etapa 3 go/no-go: no avanzar si no hay tecnologia madura, el costo de prueba es muy "
            "alto, no hay forma de medir el exito, el enfoque depende de un proveedor de riesgo, "
            "la solucion ya existe sin diferencial.\n"
            "Santiago: estos checklists le hubieran frenado muchas iniciativas desde el principio "
            "(ejemplo: cuantica a cierta escala).\n\n"
            "4. Necesidad de tiempos estimados por etapa\n"
            "Santiago pidio agregar plazos estimados a cada etapa para presentar a socios. "
            "Objetivo: calmar la ansiedad sobre cuanto tarda cada cosa. "
            "Mariano: los tiempos no estan medidos aun; el plan es medir las iniciativas que "
            "tenemos en curso y sacar un promedio. Esto esta en el roadmap del ano. "
            "De momento se puede agregar una referencia basada en la media de las ultimas "
            "iniciativas, aclarando que es una referencia y no una promesa.\n\n"
            "5. Templates para cada entregable\n"
            "Mariano: todo lo que tiene entregable en cada etapa deberia tener un template. "
            "Santiago: ese template deberia generarse con IA para que sea consistente y "
            "no se preste a interpretaciones subjetivas.\n\n"
            "6. Plan de accion para unificar los documentos\n"
            "Naiara: le va a pasar los dos HTML (el de Claude Design y el de Mariano) a Claude Code "
            "para que los unifique con una estetica visual consistente. "
            "Santiago: agregar metricas objetivas para los gates (ej. facturacion minima de 3 ventas "
            "para ser candidato a producto).\n\n"
            "Decisiones:\n"
            "- El framework se unificara en un solo documento HTML con los dos niveles: "
            "vista ejecutiva (de Naiara) + desglose detallado por etapa (de Mariano).\n"
            "- Agregar un template para cada entregable del framework.\n"
            "- Agregar plazos estimados basados en la media de iniciativas actuales "
            "(con la advertencia de que es una referencia).\n"
            "- Agregar metricas objetivas a los gates (ej. numero de ventas para graduacion a producto).\n\n"
            "Accionables:\n"
            "- Naiara: pasar los dos HTMLs a Claude Code para unificar. "
            "Agregar el paso de transferencia/cierre al framework ERSAP.\n"
            "- Mariano: pasar el HTML de su framework a Naiara. "
            "Mapear las iniciativas actuales en las etapas del framework para la presentacion.\n"
            "- Santiago: definir metricas de negocio para los gates de decision."
        ),
    },
    {
        "source_id": "654050542",
        "date": "2026-04-28",
        "title": "Seguimiento Aeropuertos — Robot Big Dipper y Contexto Trainly para TecPetrol",
        "content": (
            "Meeting: Seguimiento POC Aeropuertos con robot cuadrupedo (Big Dipper) y contexto "
            "de Trainly para reunion con TecPetrol\n"
            "Date: 2026-04-28\n"
            "Participants: Mariano Ortega, Jorge Asfour\n\n"
            "Contexto: Reunion de seguimiento entre Mariano Ortega (IMAXD) y Jorge Asfour "
            "(comercial, nuevo en el equipo) para alinear sobre dos temas: el proximo paso con "
            "Aeropuertos (robot cuadrupedo) y el contexto de la situacion de Trainly antes de "
            "la reunion de ese dia con TecPetrol.\n\n"
            "1. Estado del proyecto con Aeropuertos — Robot cuadrupedo\n"
            "El relevamiento en aeropuertos resulto positivo. Aeropuertos quedo muy interesado. "
            "Unico punto critico: la velocidad del cuadrupedo. El cliente quiso un robot mas rapido, "
            "posiblemente con ruedas.\n"
            "Proximo paso acordado: consultar a Big Dipper (proveedor del robot) si existe un "
            "modelo mas rapido con ruedas. Una vez confirmado, volver a aeropuertos con una nueva "
            "propuesta concreta de casos de uso para una POC en campo.\n"
            "Aclaracion de Mariano: Big Dipper no tiene ninguna obligacion ni interes particular "
            "en prestar un robot. Es un favor. El vinculo fuerte con Nestor Rios (representante "
            "maximo de Big Dipper) lo tiene Pablo Baglica (comercial de Acciona), quien gestiono "
            "la compra del robot. Para conseguir el prestamo del robot hay que ir por Pablo -> "
            "Nestor, no por el equipo de soporte.\n"
            "Propuesta de Mariano: organizar una reunion con Big Dipper, explicarles el caso y el "
            "cliente (Aeropuertos), preguntar si tienen un robot con ruedas disponible para "
            "prestar. Si no lo pueden resolver con el equipo de soporte, escalar a Nestor.\n"
            "Jorge lo ve urgente: Aeropuertos quedo muy entusiasmado con el demo y no hay que "
            "dejar que se enfrie.\n"
            "Jorge: coordinara con Mati para determinar las especificaciones tecnicas del robot "
            "requerido antes de ir a Big Dipper.\n\n"
            "2. Contexto de Trainly — Historia del producto y cambio de estrategia\n"
            "Mariano le explico a Jorge el contexto completo de Trainly:\n"
            "- Origen: a mediados del ano anterior, cuando se inicio la vertical de Industrias 4.0, "
            "se acordo que IMAXD armaria una vertical de producto de 2 personas para generar "
            "cascaras de producto con las que salir a hacer demos.\n"
            "- Las primeras dos necesidades identificadas por Seba fueron: plataforma de "
            "entrenamiento (-> Trainly) y plataforma de Computer Vision (-> Vision 360).\n"
            "- Se hizo un delivery muy rapido (1-1.5 meses) de cada cascara, para que el equipo "
            "comercial pudiera hacer demos y generar tracking comercial.\n"
            "- Cambio de estrategia reciente: los socios no estan seguros de querer invertir en "
            "productos. El nuevo enfoque: lo que surge para crear nuevos productos tiene que ser "
            "consecuencia de haber vendido un servicio o desarrollo ad hoc primero. Si varios "
            "clientes piden lo mismo, recien entonces se evalua crear un producto.\n"
            "- Consecuencia para Trainly: la cascara actual no esta lista para produccion. "
            "No tiene el testing, la arquitectura ni el desarrollo necesario para un cliente "
            "como TecPetrol. No se debe ofrecer proactivamente mas de lo que ya esta "
            "desarrollado y probado.\n\n"
            "3. Reunion con TecPetrol ese dia\n"
            "El POC con TecPetrol fue definido con un alcance especifico: procesar los PDFs de "
            "TecPetrol con los agentes de Trainly y mostrar que la app puede usarse por los "
            "5 usuarios asignados.\n"
            "Jorge: el objetivo de la reunion es mostrar que se cumplio el alcance acordado. "
            "Si al cliente no le gusto algo, la puerta debe quedar abierta para una siguiente "
            "version con mas tiempo y objetivos bien definidos.\n\n"
            "4. Reunion con Pampa Energy (ese jueves)\n"
            "Pampa Energy tuvo una primera reunion y mostro interes en plataforma de capacitacion "
            "con requerimientos muy especificos (contenido certificado por aprobadores, funcionalidades "
            "avanzadas). Marilyn de IMAXD participara.\n"
            "Jorge: no podra asistir. La estrategia es mostrar lo que existe y entender el gap "
            "para que el cliente decida si quiere invertir.\n\n"
            "5. Coordinacion futura Jorge + IMAXD\n"
            "Se acordaron reuniones quincenales entre Jorge y el equipo de IMAXD (Marilyn) para "
            "que Jorge se vaya familiarizando con como trabajan y aportando una perspectiva "
            "comercial/del sector desde el inicio de los proyectos.\n"
            "Jorge: tiene perspectiva del sector Oil & Gas que puede enriquecer las decisiones "
            "de diseno/funcionalidades de las plataformas (ej. lo que el cliente va a querer "
            "ver vs lo que se esta construyendo).\n\n"
            "Accionables:\n"
            "- Mariano: llevar a Mati el pedido de coordinar con Big Dipper para el robot de ruedas.\n"
            "- Jorge + Mati: definir especificaciones tecnicas del robot antes de ir a Big Dipper.\n"
            "- Mariano: coordinar reunion quincenal Jorge + Marilyn. Gestionar a traves de Marilyn.\n"
            "- Jorge: presentar a nueva integrante del equipo comercial en las proximas reuniones.\n"
            "- Mariano: mantenerse al tanto del resultado de la reunion de TecPetrol ese dia."
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
