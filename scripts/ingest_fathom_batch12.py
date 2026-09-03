"""Ingest Fathom transcripts batch 12 (recordings 653921352, 638751409, 633423858)."""
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
        "source_id": "653921352",
        "date": "2026-04-28",
        "title": "Plan Mayo y Reporte Abril — Reunion OKRs con Ale Yona",
        "content": (
            "Meeting: Plan Mayo y Reporte Abril — Reunion OKRs IMASD con Ale Yona\n"
            "Date: 2026-04-28\n"
            "Participants: Mariano Ortega, Ale Yona, Bernardo De Siano\n\n"
            "Contexto: Reunion mensual de seguimiento de OKRs y KPIs del area IMASD de Flock. "
            "Se revisa el plan de mayo y se cierra el reporte de abril.\n\n"
            "1. Plan de Mayo — Accionables por Objetivo\n"
            "Publicacion tecnica generada: preparar y publicar el paper de integracion con BMS "
            "(Building Management Systems) para modelos custom de Computer Vision. Lo escribio un "
            "miembro del equipo y se publicara en la landing de IMASD/Flock con distribucion en LinkedIn.\n"
            "Transferencia de conocimiento: workshop de generacion de imagenes sinteticas y etiquetado "
            "automatico de Computer Vision (a cargo de Luisina). Orientacion tecnica, abierto a todo Flock.\n"
            "Plan de comunicacion IMASD: revisar y lanzar oficialmente la landing de IMASD con los papers "
            "ya publicados. Coordina con el objetivo anterior.\n"
            "Framework operativo IMASD: al 75% en mayo. Pendiente: templates de salidas de cada etapa "
            "del framework + mapeo de iniciativas de I+D en el framework. Presentacion a los socios en mayo.\n"
            "Demo cuadrupedo: presentacion interna de la demo de navegacion autonoma del robot cuadrupedo "
            "(postergada de abril).\n"
            "Oportunidad de negocio documentada: documentar formalmente el caso de uso de robotica en "
            "aeropuertos (surgido en abril).\n"
            "Pitch deck Agora: revision del pitch deck de Agora (plataforma de agentes) para cierre.\n\n"
            "2. Reporte Abril — Resultados\n"
            "Publicacion tecnica: paper de validacion de identidades sinteticas generado (pendiente de "
            "publicacion en landing).\n"
            "POC tecnologica: se hizo una POC de robotica (cuadrupedo) con Aeropuertos Argentina en el "
            "aeropuerto de San Fernando. No es la POC de navegacion autonoma planificada, sino una mini "
            "POC para el caso de uso de deteccion de animales con el robot. Positivo: surgio como "
            "oportunidad de negocio nueva.\n"
            "Pilotos con usuarios: uno completado y entregado.\n"
            "Pitch de comercial: pitch de Cognify (ahora rebrandead como Trainly).\n"
            "Framework operativo: al 50%, en tiempo.\n\n"
            "3. Desvios de Abril\n"
            "POC de navegacion autonoma del cuadrupedo no completada: el equipo tuvo que desviar "
            "esfuerzo para preparar la mini POC de Aeropuertos (surgio de un dia para el otro tras "
            "una reunion comercial). Lo positivo: se implemento una POC para un caso de negocio nuevo "
            "de robotica en aeropuerto. El impacto fue la postergacion de la demo interna.\n"
            "Computacion cuantica atrasada: el KPI operativo de desarrollar capacidad de computacion "
            "cuantica quedo atrasado. Causa: participacion muy intensa en comites del plan de desarrollo "
            "de talento de Flock (casi a diario, reuniones de 2.5 horas).\n\n"
            "Decisiones:\n"
            "- Mariano prepara el plan de accion en formato compartible con Fede para dar visibilidad.\n"
            "- Se deja pendiente completar 'aspectos a mejorar' para el follow-up con Berni.\n"
            "- Aspectos a mejorar de mayo 2026 a definir en follow-up del 5 de mayo."
        ),
    },
    {
        "source_id": "638751409",
        "date": "2026-04-15",
        "title": "Reunion de Liderazgo FLOC — Estrategia Praia, Adopcion IA y Novedades Comerciales",
        "content": (
            "Meeting: Reunion de Liderazgo FLOC — Estrategia Praia, Adopcion IA y Novedades Comerciales\n"
            "Date: 2026-04-15\n"
            "Participants: Santiago Samra, Naiara Acosta Najmanovich, Gustavo Herrera, Mariano Ortega, "
            "Federico Valentino Lacoste, Matias Loizaga, Ines Grotz\n\n"
            "Contexto: Reunion general de liderazgo de FLOC. Agenda: estrategia del producto Praia "
            "(avatares conversacionales), adopcion de IA en el ciclo de desarrollo, novedades "
            "comerciales y logos, update de operaciones, y estado de la vertical de Industrias 4.0.\n\n"
            "1. Producto Praia — Avatares Conversacionales con IA\n"
            "Praia es el producto mas avanzado de FLOC, con dos clientes reales: Toki (showroom de "
            "telas, atiende recepcion y sugiere productos) y Aeropuerto (punto de informacion al "
            "pasajero). Alianza con Penta. El lider de la vertical (Pepe) ya no esta en la empresa.\n"
            "Estado: la ventaja diferencial se ha erosionado (la tecnologia conversacional era innovadora "
            "al lanzarlo, ahora es estandar). Problemas tecnicos: el avatar es lento, se traba, peor "
            "rendimiento a la tarde. El cliente Toki da feedback de que 'encanta el avatar pero no "
            "funciona como se esperaria'.\n"
            "Problemas estructurales: sin ownership del producto (nadie lo gestiona de forma exclusiva), "
            "sin pricing claro (no se sabe cuantificar el costo de operacion: servidores, licencias "
            "Eleven Labs), sin estrategia de go-to-market fuerte. No hay competidor local actualmente.\n"
            "Debate: el problema no es tecnologico sino de distribucion y go-to-market. Mariano de "
            "Penta esta dispuesto a coinvertir en un Product Owner a mitad de costo.\n"
            "Penta tiene SharePoint con informacion comercial compartida que Fede debe distribuir "
            "a todo el equipo de liderazgo (no se estaba aprovechando).\n\n"
            "2. Adopcion de IA en el Ciclo de Desarrollo\n"
            "Experimento real 'From Brief to Build' con Nomadear v2 (evolutivo de plataforma "
            "de eventos de vehiculos para Fiat Titano y otras marcas):\n"
            "- Con Claude Code (framework SDD + subagentes), un desarrollador (Mujica) produjo en "
            "4 dias habiles un evolutivo estimado en 30 dias habiles de desarrollo tradicional.\n"
            "- El framework incluye: integracion con repositorio, documentacion automatica, revision "
            "de codigo, carga de issues en GitHub, generacion de tests. Subagentes especializados "
            "(analisis funcional, frontend, backend, planificacion, delivery) orquestados en paralelo.\n"
            "Modelo de costos hipotetico:\n"
            "- Desarrollo tradicional: costo de entrega ~60-70%, margen ~30%.\n"
            "- Con IA: costo de entrega ~30%, contingencia 10%, mismo margen 30%, ahorro al "
            "cliente del 30% (paga 70 en vez de 100).\n"
            "- A 6-8 meses: reducir precio al cliente 40-45%.\n"
            "Niveles de adopcion: nivel 1 (sin IA) → nivel 2 (aceleracion individual, 14-15% de "
            "proyectos hoy) → nivel 3 (automatizacion de pasos enteros) → nivel 4 (equipos de "
            "subagentes con checkpoints humanos). Objetivo: acelerar a nivel 3-4.\n"
            "El perfil que se necesita cambia: menos importa calidad de codigo, mas importa criterio "
            "para interpretar necesidades del cliente y traducirlas a decisiones de arquitectura.\n"
            "Tendencias: modelos locales (Gemma 4 de Google) corren en maquinas sin GPU al nivel "
            "de Sonnet 4.6. Se viene un modelo hibrido: modelos pequenos especializados en coding "
            "localmente + modelos razonadores grandes en la nube.\n\n"
            "3. Novedades Comerciales\n"
            "- Jorge se unio al equipo comercial de Argentina (cartera de clientes, generacion "
            "proactiva de oportunidades). El 27 se suma una segunda persona.\n"
            "- Federacion: contrato renovado hasta diciembre (11 meses desde febrero), con aumentos "
            "cuatrimestrales. Se negocia ampliar equipo en 10 perfiles. Propuesta de documentacion "
            "via CONIA. Perspectiva de extension a 2027.\n"
            "- Advanta (chatbot Club Advanta): tercer upselling en curso (1 mes → 2 meses → "
            "negociando 6 meses).\n"
            "- Nomadear: proyecto de 3.5 meses, en negociacion evolutivo de ~30 dias habiles "
            "(proyecto piloto del experimento de IA).\n"
            "- Scalter (Computer Vision deteccion de defectos en telas): cerrado y finalizado, "
            "upselling a asistente comercial por WhatsApp.\n"
            "- Pipeline: Adi, UNSGS, Advanta, Aeropuertos, y otros.\n"
            "- Cambio de buyer persona: clientes Pyme (Advanta, Nomadear, Scalter, Toki) "
            "abren nuevo segmento; la forma de llegar es diferente (no LinkedIn, sino camaras "
            "y asociaciones industriales).\n\n"
            "4. Vertical de Industrias 4.0\n"
            "- 6 meses operando con foco en oil and gas. Logros: multiples reuniones, confirmacion "
            "de interes real, dos productos 'cascarones': Vision 360 (Computer Vision) y "
            "TrainLeap/Trainly (formacion con multiagentes).\n"
            "- Grandes empresas de oil and gas ya tienen plataformas estandar de CV (3-4 en la "
            "industria); oportunidad en empresas de menor porte sin plataforma propia.\n"
            "- Trainly: competencia con productos gratuitos, pero features especificos con IA "
            "detectados como diferencial (TechPetrol y Singenta mostraron interes concreto).\n"
            "- Problema sistematico: se construyo el cascarон primero para tener algo que mostrar "
            "y recien ahora se hace el brainstorming de producto. Igual que Praia: falta un "
            "Product Owner que de continuidad post-MVP.\n\n"
            "5. Problematica Transversal: Venta de Producto vs. Servicio\n"
            "FLOC sabe vender servicio pero no producto. Tres debilidades: (1) no hay estrategia "
            "de go-to-market ni pricing para productos propios, (2) no se indaga sistematicamente "
            "el ROI del cliente (cuanto vale el problema que se resuelve), (3) marketing debil "
            "(se entrevistan candidatos).\n\n"
            "Decisiones:\n"
            "- Avanzar con campanas comerciales para Praia usando casos Toki y Aeropuerto, "
            "apuntando a turismo/retail. Checkpoint en 1-1.5 meses.\n"
            "- Fede comparte SharePoint de Penta con todo el equipo.\n"
            "- Organizar reunion con Mariano de Penta para definir estrategia comercial conjunta.\n"
            "- Continuar busqueda de Product Owner (pago a mitad con Penta).\n"
            "- Validar hipotesis de costos con IA en el proximo mes usando Nomadear.\n"
            "- Incorporar cuestionario de impacto de negocio del cliente en el proceso comercial.\n\n"
            "Accionables:\n"
            "- [Naiara/Jorge] Lanzar campana comercial de Praia (turismo, retail).\n"
            "- [Federico] Compartir SharePoint Penta-FLOC con equipo de liderazgo.\n"
            "- [Federico/Gustavo] Cerrar evaluacion de candidato a Product Owner; agendar "
            "reunion con Mariano de Penta.\n"
            "- [Santiago] Validar hipotesis de costos IA vs. tradicional con Nomadear evolutivo.\n"
            "- [Santiago/Naiara] Incorporar cuestionario de impacto de negocio en ciclo comercial.\n"
            "- [Fede/Mariano de Penta] Relevamiento de mercado de Praia (competencia, diferencial).\n"
            "- [Seba/Fede] Brainstorming del viernes sobre Trainly: MVP, diferencial, modelo de venta.\n"
            "- [Gustavo/Santiago] Mapear transicion a nivel 3-4 de adopcion IA, reconversion juniors.\n"
            "- [Fede] Reunion con Multiverse sobre modelos pequenos especializados."
        ),
    },
    {
        "source_id": "633423858",
        "date": "2026-04-09",
        "title": "Demo POC From Brief to Build — Desarrollo de Software con IA (Nomadear B2)",
        "content": (
            "Meeting: Demo POC 'From Brief to Build' — Desarrollo de Software con IA\n"
            "Date: 2026-04-09\n"
            "Participants: Mariano Ortega, Lucas Mujica, Santiago Samra, Naiara Acosta Najmanovich, "
            "Federico Valentino Lacoste\n\n"
            "Contexto: Demo interna de la POC 'From Brief to Build'. El objetivo fue mostrar la "
            "viabilidad de construir y desplegar software casi totalmente asistido por IA (Claude Code / "
            "Opus), partiendo de transcripciones de reuniones con el cliente, generando documentacion "
            "funcional, creando issues en GitHub, implementando features y generando tests — todo con "
            "minima intervencion humana en la etapa de desarrollo.\n\n"
            "1. Proyecto Base: Nomadear B2 (Plataforma Fiat Titano / Multimarca)\n"
            "La POC utilizo como caso real el evolutivo de Nomadear, plataforma web para eventos de "
            "test drive de vehiculos. La version original fue desarrollada de forma tradicional.\n"
            "Features implementadas por IA en la POC:\n"
            "- Login y autenticacion privada.\n"
            "- Sistema de invitaciones por email con magic link (SendGrid, free tier).\n"
            "- Modelo multimarca/multitenant: 5 marcas (Fiat Titano, Audi Q3, Duster, Hilux, Taos).\n"
            "- Seccion 'Mis Eventos' para usuarios autenticados.\n"
            "- Plantillas de email editables (invitacion, confirmacion, inscripcion a evento).\n"
            "- Modulo de examenes para asesores (preguntas con opciones, timer, asignacion automatica).\n"
            "- Light Mode / Dark Mode (parcialmente funcional).\n"
            "- Formulario publico de inscripcion a eventos para captura de leads.\n"
            "- Sitio de documentacion completo con Docusaurus (arquitectura, funcionalidades, "
            "test plan, resultados).\n"
            "- Test automatizado con Playwright: 19 tests, 19 pasados.\n"
            "- CI/CD con GitHub Actions + deploy automatico a Vercel.\n"
            "Feature NO implementada: evolucion del chatbot (requeria infraestructura Google Vertex AI).\n\n"
            "2. Framework y Metodologia\n"
            "SDD (Spec-Driven Development): framework de subagentes basado en archivos Markdown "
            "(CLAUDE.md / skills) llamado 'SDD Gentleman' (open source). Flujo: Explore "
            "(solo investiga) → Design/Spec (propone arquitectura, requiere aprobacion humana) → "
            "Implement (ejecuta el codigo) → Verify (verifica calidad) → Archive (limpia contexto). "
            "Los agentes pueden correr en paralelo cuando las tareas lo permiten.\n"
            "Engram: libreria open source de memoria persistente para agentes. A diferencia de "
            "claude-mem (guarda todo), Engram guarda solo puntos clave, lecciones aprendidas y "
            "decisiones relevantes, organizados por topic key. Se consulta al inicio de cada tarea SDD.\n"
            "Control de calidad: pre-commit hook que obliga cobertura de tests al 100% y que el "
            "linter pase antes de cualquier push. GitHub Actions con validacion, testing y deploy "
            "automatico. Cuando el hook falla, Claude Code lo detecta, corrige y reintenta solo.\n"
            "Postwork Summary skill: genera resumen por tarea (modelo usado, tiempo, tokens).\n\n"
            "3. Resultados y Metricas\n"
            "- Estimacion original del evolutivo: 30 dias habiles (1.5 meses).\n"
            "- Tiempo real de implementacion con IA: 2 a 5 dias habiles (16-33% del tiempo original).\n"
            "- Propuesta del evolutivo: U$D 36.000.\n"
            "- Claude Max $100/mes (con Opus) fue suficiente aunque alcanzo limites por sesion. "
            "Para 5 personas en un proyecto: ~$1.000/mes en licencias, marginal frente al ahorro.\n\n"
            "4. Desafios y Limitaciones Identificadas\n"
            "- Falsas soluciones: el modelo a veces reporta que soluciono un error cuando no lo hizo.\n"
            "- Confusion entre sistemas de deploy (Vercel vs GitHub Actions).\n"
            "- Cambios visuales (dark/light mode, contrastes) quedan incompletos con mas frecuencia.\n"
            "- Sobredimensionamiento: ante el modulo de timer, propuso solucion compleja con "
            "timestamps en BD; la intervencion humana redirijio a diferencia entre inicio y fin.\n"
            "- Test plans 'felices': valida casos exitosos pero puede omitir casos borde.\n"
            "- La calidad de la documentacion funcional inicial es el factor critico (requiere "
            "criterio humano y conocimiento de negocio).\n\n"
            "5. Discusion Estrategica\n"
            "Roles en el nuevo modelo: el esfuerzo se desplaza del desarrollo al discovery. "
            "Roles propuestos para el equipo virtual de IA: analista funcional, arquitecto de "
            "soluciones, UX/UI, QA. El criterio humano sigue siendo el factor mas critico.\n"
            "Modelo de precios a 6-8 meses: reducir precio al cliente 40-45%, siendo mas competitivos. "
            "El 15% del margen ganado se reinvierte en mayor calidad de discovery.\n"
            "Trabajo en equipo con IA: dividir por modulos, con ingeniero senior controlando el "
            "nucleo y perfiles junior trabajando funcionalidades acotadas.\n"
            "Agents Teams / Managed Agents de Claude Code: permite crear equipos de agentes que se "
            "comunican entre si. Recomendacion: continuar con SDD hasta ganar mayor seniority.\n"
            "Restricciones en clientes con politicas de seguridad (Cencosud, Federacion): trabajar "
            "en local con Claude Code y hacer el PR a mano; el codigo es indistinguible.\n"
            "Gestion del cambio cultural: hay personas que adoptan rapido y otras reticentes. "
            "Decision estrategica: ir en esta direccion. El reskilling no sera uniforme.\n\n"
            "Proximos Pasos:\n"
            "- Mejorar y pulir POC Nomadear B2 (si se gana el proyecto).\n"
            "- Documentar el proceso como caso de estudio interno.\n"
            "- Estandarizar template de documento funcional con casos de uso completos y "
            "requerimientos no funcionales.\n"
            "- Crear skills reutilizables cross-proyecto: login, dashboard, chatbot con IA, "
            "modulo de auditoria, control de usuarios.\n"
            "- Medir consumo de tokens por issue/tarea para datos de costo por feature.\n"
            "- Evaluar framework Managed Agents de Claude Code cuando haya mayor madurez.\n"
            "- Identificar referentes por area que incorporen el framework en su dominio.\n"
            "- Fecha objetivo: MVP con orquestador de agentes a fin de abril 2026."
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
