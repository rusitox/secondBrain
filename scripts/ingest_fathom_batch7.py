"""Ingest Fathom transcripts batch 7 (recordings 721604751, 721555457)."""
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
        "source_id": "721604751",
        "date": "2026-07-06",
        "title": "Adopcion Claude Code, Dashboard Grafana y Gestion de Licencias — Flock",
        "content": (
            "Meeting: Revision metricas de adopcion de Claude Code, dashboard Grafana y gestion de licencias\n"
            "Date: 2026-07-06\n"
            "Participants: Lucas Mujica, Mariano Ortega, Naiara Acosta Najmanovich, "
            "Federico Valentino Lacoste, Santiago Samra\n\n"
            "Contexto: Revision del estado de adopcion de herramientas de IA (fundamentalmente Claude Code) "
            "dentro de Flock y empresas relacionadas (ACCIONA, IMAXD). Se presento el dashboard Grafana "
            "de monitoreo de uso de Claude Code, se discutio la gestion descentralizada de licencias, "
            "el perfil de Dani (posible colaborador externo) y proximos pasos de la estrategia de adopcion.\n\n"
            "1. Dashboard Grafana de monitoreo de Claude Code\n"
            "Lucas Mujica presento el dashboard de monitoreo de uso de Claude Code:\n"
            "- Migrado de GitHub Pages a Vercel para habilitar autenticacion con Microsoft.\n"
            "- Usa capa de permisos administrativos de Claude Team para generar reportes de uso por usuario "
            "(capturados automaticamente, sin que los usuarios puedan modificarlos).\n"
            "- Metricas: personas activas, tiempo de sesion por persona, costo estimado en tokens, "
            "ranking de adopcion por tiempo y costo.\n"
            "- Limitacion: metrica de 'tiempo activo' poco confiable porque las sesiones quedan abiertas "
            "inactivas (idle). La cantidad de tokens consumidos es metrica mas representativa del uso real.\n"
            "- Caso detectado: persona con poco tiempo registrado pero alto costo en tokens indica uso "
            "desatendido (modelo genera contenido sin interaccion humana sostenida).\n"
            "- Propuesta de Mariano: tool que al iniciar sesion en Claude Code registre el proyecto activo "
            "y el repositorio Git, vinculando uso de tokens a entregables especificos.\n"
            "- Propuesta de Fede: agente que mida y reporte tokens gastados por sesion al finalizarla.\n"
            "- Posibilidad de segmentar uso por MCP para entender en que tipo de trabajo se gasta mas.\n"
            "- Pendiente: verificar si el calculo de costos distingue entre modelos (Opus vs otros).\n\n"
            "2. Incorporacion de modelos alternativos en Claude Code\n"
            "Claude Code permite incorporar modelos de terceros via estandar API de OpenAI.\n"
            "Ejemplo: modelo GLM 2.5 (chino) con benchmarks similares a niveles altos a fraccion del "
            "costo de Opus.\n"
            "Mariano ya conecto Claude Code con modelos locales usando ese estandar.\n"
            "Idea: hacer experimentos con distintos modelos por equipo y medir diferencias de costo.\n"
            "Evaluar integrar en Grafana el monitoreo de otras herramientas como Codex (OpenAI), "
            "ya que parte de IMAXD usa Codex en vez de Claude Code. Quedo como idea a explorar.\n\n"
            "3. Gestion de licencias de software — problema detectado\n"
            "Problema sistematico: licencias de multiples herramientas (Claude, Bitbucket, LinkedIn, "
            "Apollo, Wallaxi, Amazon, etc.) distribuidas en varias tarjetas personales (Mariano, Nai, Mati, Fede) "
            "sin proceso de monitoreo ni responsable centralizado.\n"
            "Caso concreto: Bitbucket tenia >20 usuarios cuando el plan gratuito admite 5; "
            "se estuvo pagando plan pago durante meses sin que nadie lo detectara.\n"
            "Decision: Lucas Mujica = responsable unico de gestion de licencias de Flock; Naiara = backup.\n"
            "Plan: solicitar a administracion filtrado de gastos de tarjeta para mapear universo de licencias.\n"
            "Migrar licencias individuales de Claude Code (Flock e IMAXD) al plan Team (USD 25/usuario) "
            "para tener control centralizado: dar de baja usuarios, monitorear inactivos.\n"
            "Para licencias no centralizables (LinkedIn, Apollo, etc.): usar tarjetas prepagadas tipo Pago24 "
            "en vez de tarjetas personales, evitando dependencia de individuos al desvincularlos.\n"
            "Fede propone flujo formal de pedido de licencia al responsable designado.\n\n"
            "4. Estado del proyecto piloto de adopcion de Claude Code\n"
            "El piloto concluyo, tomo mas tiempo del previsto; causas se analizaran en retro del jueves.\n"
            "Proyectos activos y estado de adopcion:\n"
            "- Federacion: cuello de botella en discovery (complejo), no en desarrollo. "
            "Desarrolladores cargados, sin margen para experimentos adicionales.\n"
            "- Advanta: sin restricciones del cliente. Nachito Salinas y Emi usan Claude Code hace tiempo. "
            "Se usa para simular flujos completos (cascarones de aplicacion) para presentaciones al cliente.\n"
            "- City: prohibido por el cliente. Equipo trabaja en VMs controladas.\n"
            "- Senco, Metro, Turan: proyectos de provision de personas, no de desarrollo.\n\n"
            "5. Guia de desarrollo con IA — v1.0 para julio\n"
            "Lucas apunta a tener lista la guia de metodologia de desarrollo con IA v1.0 para julio, "
            "coincidiendo con charla publica interna de Flock que presentara la forma de trabajo con IA "
            "(handbook completo + aprendizajes del piloto).\n\n"
            "6. Idea comercial: servicio de diagnostico de aplicaciones con IA\n"
            "Fede propone: la IA analiza una aplicacion e identifica inconsistencias funcionales, "
            "deuda tecnica y vulnerabilidades. Se ofreceria como servicio gratuito de entrada generando "
            "un reporte y proponiendo a Flock como ejecutor de las mejoras.\n"
            "Antecedente: cliente 'Origenes' captado de manera similar via reporte de QA manual.\n"
            "Lucas: cada proyecto es diferente (distintos stacks, restricciones, deuda heredada), "
            "seria servicio caso a caso.\n\n"
            "7. Perfil de Dani — posible colaborador externo\n"
            "Dani propone un 'sistema operativo' de IA para organizaciones. Diversas perspectivas:\n"
            "- Lucas: Dani tiene ideas de flujos estructurados con chatbots para tareas predecibles. "
            "Genera dudas de compatibilidad con enfoque de Flock (developers con Claude Code en modo libre).\n"
            "- Mariano: Dani se alinearon en vision de sistemas multi-agente verticales. "
            "Cristia que Dani compartio job description de 'AI Engineer' con la que se identifico.\n"
            "- Naiara: el perfil de Dani no necesita ser full time; puede aportar como brazo ejecutor "
            "de iniciativas de adopcion (Grafana, documentacion, experimentos, etc.).\n"
            "Consenso: Dani debe participar en la definicion colectiva y ser ejecutor de lo que se "
            "decida en equipo, no venir a implementar su propia agenda.\n\n"
            "Decisiones:\n"
            "- Lucas Mujica = responsable unico de licencias; Naiara = backup.\n"
            "- Solicitar a admin filtrado de gastos de tarjeta para mapear licencias.\n"
            "- Migrar licencias individuales de Claude Code al plan Team.\n"
            "- Para licencias no centralizables: usar tarjeta prepaga.\n"
            "- Guia de metodologia v1.0 lista para charla interna de julio.\n"
            "- Agendar reunion con Dani para el viernes (post-retro del jueves).\n\n"
            "Accionables:\n"
            "- Lucas: completar dashboard Grafana v1 para julio; gestionar licencias; "
            "dar de baja inactivas.\n"
            "- Naiara: solicitar filtrado de gastos de tarjeta a admin; sumar chicas de People "
            "al team Claude Code.\n"
            "- Mariano + Lucas: armar plan de trabajo formal para Dani antes del viernes.\n"
            "- Naiara: agendar reunion con Dani para el viernes.\n"
            "- Todo el equipo: investigar como diseccionar uso de tokens por MCP y por modelo."
        ),
    },
    {
        "source_id": "721555457",
        "date": "2026-07-06",
        "title": "Onboarding Plataforma Interna I+D — Landing, Iniciativas, Tareas y Plan de Accion",
        "content": (
            "Meeting: Demo y onboarding a la plataforma de gestion del equipo I+D\n"
            "Date: 2026-07-06\n"
            "Participants: Marilyn Botheatoz, Mariano Ortega, Matias Araujo, Denis Perafan, "
            "Tomas Garbarino, Francisco Sempe, Luisina Giorgetti, Michael Pereira\n\n"
            "Contexto: Sesion de onboarding del equipo de I+D a la plataforma interna de gestion "
            "desarrollada por Marilyn Botheatoz junto con Mariano Ortega. La plataforma incluye: "
            "landing publica del equipo, back office de administracion de contenidos, sistema de gestion "
            "de iniciativas (con etapas y checklists), registro de tareas con estimaciones, plan de accion "
            "mensual, OKRs, y sistema de logs con IA para facilitar el registro de tareas.\n\n"
            "1. Landing publica del equipo\n"
            "La landing anterior estaba desactualizada. La nueva fue desarrollada por Marilyn con draft "
            "inicial generado via Claude Design y luego ajustada manualmente.\n"
            "Incluye secciones de: proyectos, publicaciones (informes), noticias y OKRs.\n"
            "Objetivo: vitrina del equipo para compartir en LinkedIn, Slack y otros canales. "
            "Responsabilidad colectiva mantenerla actualizada.\n\n"
            "2. Back office — Administracion de contenidos\n"
            "Permite crear y editar tres tipos de contenido: proyectos, publicaciones (informes de "
            "investigacion) y noticias (eventos, capacitaciones, etc.).\n"
            "Metadatos: autor, vertical, estado (borrador/publicado/archivado), iniciativa vinculada, "
            "imagenes (multi-imagen, markdown para incrustar, estrella para imagen portada).\n"
            "Boton AI de generacion: si el usuario no tiene draft, ingresa un abstract y la IA genera "
            "una primera version.\n"
            "Boton AI de normalizacion de formato: reformatea contenido subido siguiendo etapas del "
            "proceso I+D (primer acercamiento, implementacion, conclusiones). Util para normalizar "
            "informes de 40 paginas en contenido publicable.\n"
            "Las publicaciones pueden incluir archivo de informe completo en LaTeX, habilitando boton "
            "de descarga en la landing.\n"
            "Usuarios colaboradores pueden crear los tres tipos de contenido; admins (Marilyn, Mariano) "
            "tienen permisos adicionales.\n\n"
            "3. Plan de accion mensual\n"
            "Mariano y Marilyn presentan mensualmente un plan de accion para OKRs que define iniciativas "
            "y tareas esperadas de cada miembro del equipo.\n"
            "Los usuarios ven solo sus propios accionables para evitar confusion.\n"
            "El plan es un horizonte/norte; los desvios por imprevistos son tomados en cuenta por el "
            "management sin penalizar al equipo.\n\n"
            "4. Sistema de tareas\n"
            "Los miembros deben cargar las tareas del dia al final de cada jornada (o al dia siguiente "
            "con fecha ajustada).\n"
            "Datos: descripcion, iniciativa vinculada, tipo (desarrollo/investigacion/comercial/"
            "administrativo), estimacion de tiempo (tiempo real), fecha.\n"
            "Granularidad recomendada: cargar tareas separadas por actividad.\n"
            "Sistema de logs (alternativa rapida): sube texto libre o audio describiendo el dia. Un agente "
            "de IA procesa el log y genera automaticamente las tareas correspondientes "
            "(un log de Marilyn genero 3-4 tareas automaticamente).\n"
            "Metricas generadas: porcentaje de tiempo por tipo de tarea (ej. 73% administrativo, "
            "27% desarrollo). Sirven al management para detectar desvios y si el equipo esta siendo "
            "usado en tareas fuera de su perfil.\n"
            "Al cierre de mes: comparativa entre plan de accion y tareas reales para analizar desvios.\n\n"
            "5. Gestion de iniciativas\n"
            "Las iniciativas pueden ser dadas de alta por el equipo interno o por actores externos "
            "(via formulario con ~10 preguntas describiendo el problema, user persona, contexto de uso).\n"
            "Flujo de aprobacion de Mariano/management antes de pasar a 'En curso'.\n"
            "Las iniciativas aprobadas se completan por etapas con checklists; para avanzar a la "
            "siguiente etapa, todos los items deben estar completos.\n"
            "Estados posibles: pendiente de aprobacion / en curso / pausada / finalizada.\n"
            "Ejemplo de iniciativa pausada: 'Fugas y Derrames' — pausada porque el cliente no brindo "
            "la colaboracion necesaria. Se genera un informe de cierre.\n"
            "Las iniciativas cargadas en el sistema provienen de templates previos procesados por un "
            "agente de IA para generar markdown y cargarlo automaticamente.\n\n"
            "6. Stack tecnico de la plataforma\n"
            "Proyecto Next.js en monorepo (front-end y back-end en mismo repositorio).\n"
            "Worker separado (en Railway) con agentes de automatizacion: agente de logs, agente de "
            "normalizacion de formato de notas, etc.\n"
            "El mayor desafio fue de producto, no tecnico: entender requerimientos que aparecian de "
            "forma incremental.\n\n"
            "7. Autenticacion y acceso\n"
            "Doble factor de autenticacion (2FA) con Google Authenticator, aplicado a cuenta Google "
            "y a GitHub.\n"
            "Credenciales iniciales: email Flock + contrasena 'Flock2016' (recomendado cambiarla).\n\n"
            "Preguntas y feedback del equipo:\n"
            "- Denis: propuso usar modelos locales pequenos (1B-4B) para el sistema de logs en vez de "
            "Open Router; agrego idea de bot de Slack para recordar cargar tareas al final del dia.\n"
            "- Matias: propuso filtro por defecto en vista de iniciativas que muestre las propias "
            "con opcion de ver todas. Marilyn lo agrego al backlog.\n"
            "- Luisina: solicito poder editar datos de iniciativas despues de cargados. "
            "Marilyn lo agrego como feature request de prioridad alta.\n"
            "- Michael: como registrar una tarea que se extiende varios dias. Respuesta: sumar horas "
            "o crear nueva tarea segun convenga.\n"
            "- Francisco: Agora y Agora Rediseno tienen hipotesis diferentes; Agora 3.0 (nuevo "
            "evolutivo) seria una nueva iniciativa a cargar cuando se defina el alcance del modulo 1.\n\n"
            "Decisiones:\n"
            "- Metricas de tareas comienzan oficialmente desde julio; semana restante de junio es de "
            "familiarizacion y prueba.\n"
            "- Marilyn ajustara permisos para que usuarios colaboradores vean iniciativas pausadas.\n"
            "- Backlog: edicion de iniciativas (prioridad alta), soporte modelos locales en logs, "
            "filtro por defecto en vista de iniciativas.\n"
            "- Agora 3.0 no se cargara como iniciativa hasta que Mariano defina el alcance del modulo 1.\n"
            "- Fran y Anso deben completar etapas de validacion e insights de Agora.\n\n"
            "Accionables:\n"
            "- Marilyn: enviar QR de 2FA individual a cada miembro del equipo.\n"
            "- Marilyn: fixear permisos para ver iniciativas pausadas; implementar edicion de "
            "iniciativas; agregar soporte modelos locales al sistema de logs; agregar credito a "
            "Open Router para que logs funcionen durante vacaciones.\n"
            "- Fran / Anso: completar etapas de validacion e insights de iniciativa Agora.\n"
            "- Luisina: cargar templates de iniciativa de mapas de calor en la plataforma.\n"
            "- Todo el equipo: comenzar a cargar tareas; reportar bugs via seccion de reportes.\n"
            "- Mariano: definir alcance de modulo 1 de Agora 3.0 para habilitar nueva iniciativa."
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
