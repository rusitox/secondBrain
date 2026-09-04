"""Ingest Fathom transcripts batch 2 (recordings 797990518, 785552459, 755459695)."""
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
        "source_id": "797990518",
        "date": "2026-08-25",
        "title": "Agora Feedback Meeting — Acciona Team + Flock I+D",
        "content": (
            "Meeting: Agora Feedback Meeting con equipo Acciona\n"
            "Date: 2026-08-25\n"
            "Participants: Guadalupe Poquet, Denghy Sosa (Acciona/Talent), Marilyn Botheatoz, "
            "Francisco Sempe (Fran), Mariano Ortega\n\n"
            "Contexto: Reunion de feedback sobre la busqueda de candidatos para Acciona usando la plataforma Agora.\n\n"
            "Resultados de la busqueda:\n"
            "- 175 personas subieron CV, 63 hicieron matching inicial, 20 completaron entrevista.\n"
            "- La busqueda era muy excluyente: estudios universitarios en curso (administracion/contabilidad), "
            "experiencia en call center + ventas en bancos, rango etario, zona geografica.\n"
            "- Primer filtro era demasiado flexible: dejaba pasar candidatos con tecnicaturas o carreras no afines.\n"
            "- Fran endureci los filtros hace 10-12 dias. Con el filtro estricto, ninguno de los 20 entrevistados "
            "era candidato valido para la busqueda.\n"
            "- Problema principal: motor de matching leia 'ventas' en CV y lo validaba, sin distinguir "
            "si era ventas en call center/banco o ventas de ropa.\n"
            "- Segunda vuelta: mejorada la parte de experiencia, falta reforzar filtros de estudios "
            "(tecnicatura vs licenciatura).\n"
            "- Plan: hacer esa corrreccion adicional en estudios, luego relanzar publicaciones para tercera vuelta.\n\n"
            "Metricas de alcance:\n"
            "- Aproximadamente 400 accesos al link, 175 CVs subidos.\n"
            "- Alta tasa de abandono entre acceso y entrevista (esperado en busquedas masivas sin intermediario previo).\n\n"
            "Feedback de Acciona:\n"
            "- Guadalupe: la herramienta funciona mejor como acompanamiento al reclutamiento, no como reemplazo.\n"
            "- Denghy: exportar lista de emails para contactar candidatos que no quedaron matcheados.\n"
            "- Fran: puede proveer listado de candidatos no matcheados para follow-up de Acciona.\n\n"
            "Estrategia de comunicacion:\n"
            "- Acciona etiqueta las publicaciones como 'Acciona' (para los candidatos). Naiara quiere "
            "que tambien se mencione a Flock como desarrollador del producto.\n"
            "- Guadalupe: decision de comunicacion la tiene Flock/Acciona, estan disponibles para lo que se defina.\n"
            "- Mariano: lo lleva para definir estrategia.\n\n"
            "Vision de producto (Mariano):\n"
            "- Enriquecer el sistema multi-agente para cubrir mas etapas del proceso de seleccion.\n"
            "- Meta: interactuar con Agora ya sea por la web actual o por chat, misma respuesta siempre.\n"
            "- Lleva para ver con Fede.\n\n"
            "Proximos pasos:\n"
            "- Fran: reforzar filtro de estudios (tecnicatura != licenciatura).\n"
            "- Comunicar a Denghy cuando este lista la correccion para relanzar publicaciones.\n"
            "- Mariano: definir estrategia de comunicacion con marketing."
        ),
    },
    {
        "source_id": "785552459",
        "date": "2026-08-14",
        "title": "IMAXD I+D Weekly Meeting — Agora, InsurTech, Marketing Tool, VR/3D",
        "content": (
            "Meeting: IMAXD I+D Team Weekly\n"
            "Date: 2026-08-14\n"
            "Participants: Tomas Garbarino (Tommy), Ian Solari (Bici/Ianso), Matias Araujo (Mati), "
            "Michael Pereira (Mike), Denis Perafan, Francisco Sempe (Fran), Marilyn Botheatoz, Mariano Ortega\n\n"
            "TOMMY — Farmacity + InsurTech:\n"
            "- Demo con Farmacity el lunes: salgio bien. Interes en implementar la sololucion. "
            "Le hizo onboarding de como funciona la IA. Quedaron en evaluar internamente como integrar "
            "con sus pantallas y base de datos de recetas.\n"
            "- InsurTech (Denuncia Inteligente): nuevo front mas limpio, agrego deteccion de imagen sintetica/real "
            "(metadatos revelan si es generada por IA como OpenAI). Workflow paso a paso visible en la UI.\n"
            "- Caso de uso adicional propuesto: si detecta granizo en zona, verificar automaticamente "
            "con datos meteorologicos si realmente hubo granizo.\n"
            "- Proximos pasos: pushear al repo, mandar PR a Dani, disponibilizar link a Mariano para el lunes.\n\n"
            "IAN SOLARI (BICI) — Iniciativa herramienta de marketing (Redar):\n"
            "- Research competitivo: Fithype (optimiza publicaciones, flujo simple), Sintra (automatiza muchas tareas, "
            "demasiado complejo para equipos chicos), Redacuest (similar, de Argentina).\n"
            "- Diferenciales propuestos: contenido que parte desde base de conocimiento propia, "
            "ver las fuentes, retroalimentacion de decisiones, inteligencia de estrategia, "
            "flujo de aprobacion robusto, emular voz de la marca.\n"
            "- MVP propuesto: creacion de copies para posteos, configuracion de conocimiento multimarca "
            "(Acciona + Flock), planificacion de periodo, productizacion.\n"
            "- Branding: nombre Redar, logo basado en lineas de expresion y creatividad.\n"
            "- Decision del equipo: no construir producto nuevo. Mejor mejorar experiencia de Nati "
            "usando el sistema de Dani (interfaz mas amigable, UX mejor). Esperar que Nati use la herramienta "
            "de Dani y ver que necesita. Notificar a Fede de la decision.\n\n"
            "DEBATE — Sistema Operativo de Dani vs herramientas existentes:\n"
            "- Mariano: el OS de Dani es la evolucion de la gobernanza de IA en empresas. "
            "Centraliza procesos, controla acceso a datos, da observabilidad de sistemas multiagente.\n"
            "- Debate: forzar adoption vs libertad de los empleados de usar sus herramientas preferidas.\n"
            "- Mati: compara con ERP + MCP. Mariano: correcto, pero mas accesible y agentizado.\n"
            "- Denis: los grandes LLM providers no van a permitir que intermediarios capturen valor de datos.\n"
            "- Conclusion: hay que entender la herramienta, usarla donde tiene sentido, no como mandato absoluto.\n\n"
            "MIKE — MetaHuman / 3D Assets / VR:\n"
            "- Research sobre creacion de modelos 3D con IA: MetaHuman para replicas de personas (alta calidad 8K), "
            "Tree Ages para objetos 3D desde imagen.\n"
            "- Pruebas con silla (resultado aceptable) y excavadora (resultado malo, demasiado complejo).\n"
            "- Prueba: MCP Unreal genero modelo 3D de la oficina a partir del plano CAD. Resultado bastante bueno "
            "(espejado por error menor), estructura base creada correctamente.\n"
            "- Proximo paso: reemplazar modelos de sillas/mesas en el escenario automaticamente via MCP.\n"
            "- Objetivo MVP: escenario industrial en VR (Oil and Gas/capacitacion de seguridad). "
            "Validar automatizacion con IA, calidad de assets, trabajo manual restante, orquestacion por agente.\n"
            "- Recomendacion de Mati: no simular plantas industriales grandes. Orientar a simulacion de "
            "operacion de maquinaria especifica, valvulas, capacitaciones acotadas.\n"
            "- Hardware: necesitan Oculus Quest 2 o 3 para pruebas (Quest 1 insuficiente). "
            "Accionable: coordinar envio del Oculus a Mike (Mendoza) via Marcos.\n\n"
            "Novedades generales de Mariano:\n"
            "- Trainly: Fede pregunto por avances.\n"
            "- Pronto va a dar update de novedades generales (mencionado al inicio)."
        ),
    },
    {
        "source_id": "755459695",
        "date": "2026-07-21",
        "title": "Reunion OKRs IMAXD — Mariano Ortega + Federico Valentino Lacoste",
        "content": (
            "Meeting: Revision OKRs IMAXD\n"
            "Date: 2026-07-21\n"
            "Participants: Mariano Ortega, Federico Valentino Lacoste\n\n"
            "Contexto: revision de modificaciones a los OKRs del area IMAXD que propuso Mariano en reunion previa.\n\n"
            "OKRs propuestos/revisados:\n"
            "- Duplicar cantidad de soluciones operativas comercializables (Trainly, Agora ya operativos; "
            "Vision 360 pronto; 3 mas para el resto del anio).\n"
            "- Papers publicados: ya cumplieron 4, quieren 8 minimo.\n"
            "- Instancias publicas: objetivo 10 workshops + 10 presentaciones del equipo (antes 6).\n"
            "- Vincular innovacion con generacion comercial: tracking de oportunidades comerciales "
            "originadas por demos y POC de I+D. Se va a registrar en plataforma interna.\n"
            "- Nuevo KPI: tiempo medio de innovacion por etapa.\n\n"
            "Ideas de Fede:\n"
            "- Talleres de IA aplicada para clientes corporativos (IBM, Cipivan, Beringer, Sencosud, "
            "Tecpetrol, Bayer, Siderca). Ven a IMAXD como diferencial de posicionamiento.\n"
            "- Mariano: cautela, para no hacer siempre la misma charla; preferir orientarlo a "
            "IMAXD as a Service. Los talleres de IA aplicada mejor que los de la operacion.\n"
            "- Investigar empresas que invierten en I+D para hacer campanas comerciales dirigidas. "
            "El caso Carrefour (area I+D de 2 personas, poco presupuesto) llego por la ventana.\n\n"
            "IMAXD as a Service / Partners:\n"
            "- Idea de conseguir socios estrategicos que compartan el costo de la investigacion "
            "a cambio de compartir el descubrimiento.\n"
            "- Ejemplo: pistachos: no es una venta directa, puede ser un partner que preste data/campo "
            "y nosotros investigamos.\n"
            "- Beneficio: reducir costos de I+D y conseguir socios estrategicos sin necesariamente facturar.\n"
            "- Alternativa: asociarse con hubs de innovacion o fondos de subvencion.\n"
            "- Accionable: Mariano lleva para pensar como expresarlo como OKR.\n\n"
            "Expo (preparacion):\n"
            "- Fernando confirmo que pueden ir a filmar al perro para generar show en la expo.\n"
            "- Idea de lectura de QR en el stand: capturar datos de asistentes con QR.\n"
            "- Ruleta: para filtrar leads: si alguien accede a la ruleta y gana un discovery, "
            "indica interes real. Formulario de 'grado de madurez digital' como lead magnet.\n"
            "- Contacto Fatima para seguimiento comercial.\n\n"
            "Plataforma IMAXD / Taskflow:\n"
            "- OKR Manager ya tiene tableros con action plans de IMAXD (Mariano lo confirmo).\n"
            "- Tareas en curso por vertical ya mapeadas en Taskflow.\n"
            "- Pendiente: Mari actualiza avance de tareas en ausencia de Mariano.\n"
            "- Fede quiere que cada lider tenga usuario para modificar OKRs directamente.\n\n"
            "Vacaciones de Mariano:\n"
            "- Sale de vacaciones, vuelve en 10 dias.\n"
            "- Prioridades antes de salir: expresar nuevas iniciativas, agregar acceso al management al portal IMAXD.\n"
            "- Ale tendra reunion con Mariano para modificar OKRs (siguiente paso)."
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
