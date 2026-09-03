"""Ingest Fathom transcripts batch 13 (recordings 633129854, 630284863, 617451970)."""
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
        "source_id": "633129854",
        "date": "2026-04-04",
        "title": "Estrategia Vertical Industrias — Trainly, Computer Vision, Proden POC y Plan Q2",
        "content": (
            "Meeting: Estrategia Vertical Industrias — Trainly, Computer Vision, Proden POC y Plan Q2\n"
            "Date: 2026-04-04\n"
            "Participants: Federico Valentino Lacoste, Santiago Samra, Agustin Villegas, "
            "Sebastian Loizaga, Mariano Ortega, Paula Vejrup\n\n"
            "Contexto: Reunion semanal de estrategia de la vertical de Industrias 4.0 de Flock. "
            "Se revisan avances, alineacion entre I+D y comercial, y el plan tactico del Q2.\n\n"
            "1. Alineacion I+D y Comercial — Estrategia de Producto\n"
            "Se discutio la falta de alineacion entre lo que I+D investiga y lo que la vertical "
            "comercial puede ofrecer. Problemas identificados:\n"
            "- Los productos (Trainly, Vision 360) muestran funcionalidades que ya existen en el "
            "mercado sin un diferencial claro. Lo que se promete en el roadmap (realidad inmersiva, "
            "generacion de contenido) aun requiere investigacion y no esta disponible para demos.\n"
            "- Se hicieron cascarones primero para tener algo que mostrar (necesidad comercial), "
            "pero el proceso correcto es: investigacion de producto → analisis de mercado → "
            "feasibility → cascarón → POC. Para futuros productos, el equipo comercial trae la "
            "necesidad y I+D hace el analisis previo antes de desarrollar.\n"
            "- Falta un rol de Product Manager / Product Owner que unifique la vision tecnica, "
            "comercial y de producto a lo largo de todo el pipeline de innovacion.\n"
            "- Los costos operativos de las soluciones (infraestructura, servidores) no estan "
            "calculados. Cuando un cliente pregunta el costo total de una solucion de Computer "
            "Vision con camaras en vivo, el equipo no tiene respuesta. Es necesario armar "
            "escenarios de costos (X camaras, Y modelos, infraestructura local vs. nube).\n\n"
            "2. Trainly — Estrategia y Plan para Q2\n"
            "- Compromiso Q1 no cumplido: conseguir 2-4 POCs de Industrias. Objetivo Q2: al menos "
            "2 POCs en Computer Vision y Trainly.\n"
            "- Demo pendiente con TechPetrol el 28 de abril: se van a mostrar los documentos "
            "tecnicos que enviaron (2 PDFs con imagenes). La demo debe procesar esas imagenes con IA. "
            "La siguiente pregunta del cliente sera como y cuando arranca la POC.\n"
            "- POC de TechPetrol: alcance = procesamiento de imagenes, generacion eventual de "
            "contenido de formacion, 4 topicos, 4-5 usuarios. Propuesta ya armada por Mari. "
            "Mariano revisa y coordina en reunion del 25.\n"
            "- La funcionalidad desarrollada en la POC de TechPetrol quedara embebida en Trainly "
            "como feature del producto para futuras demos.\n"
            "- Debate critico: si se va a una demo mostrando funcionalidades que ya existen en "
            "el mercado, el diferencial tiene que ser al menos parcialmente mostrable. "
            "No alcanza con prometer el roadmap. La realidad inmersiva es el diferencial "
            "propuesto, pero aun requiere investigacion.\n\n"
            "3. Proden POC — Computer Vision Fugas y Derrames\n"
            "- Proden (empresa de oil & gas) tiene interes activo. Guille tuvo contacto ese dia: "
            "proxima semana conectan via VPN para acceder a la camara y hacer pruebas.\n"
            "- El cliente ya tiene el pipeline de alertas: la camara se conecta a un PLC que "
            "genera alertas visibles en sala de control.\n"
            "- Dos zonas de interes: boca del pozo y colector de canerias con valvulas.\n"
            "- Camara dual termica (una sola, puede moverse entre zonas).\n"
            "- Surgieron otras funcionalidades de interes operativo: deteccion de temperatura "
            "delta en canerias, alertas de ramales habilitados/no habilitados.\n"
            "- El esfuerzo de Luisina en esta POC entra dentro de la linea de investigacion "
            "de Computer Vision (ya comprometida). Si se necesitan otros perfiles, hay que "
            "decidir como organizarlo y si tiene costo.\n"
            "- Accion: reunion entre Seba, Mariano y equipo para definir alcance concreto de "
            "la POC, entregables y propuesta al cliente antes de avanzar.\n\n"
            "4. Servipet — Propuesta\n"
            "- Se mando propuesta de plataforma integral: integracion de datos de maquinarias "
            "(Caterpillar, Komatsu: combustible, eficiencia, horas trabajadas, mantenimiento) + "
            "analitica de video de avance de obras con camaras (reportes de baja frecuencia, "
            "centralizados en la plataforma).\n"
            "- Se valida primero que el cliente este alineado con lo propuesto antes de estimar "
            "tiempos y costos. Cuando haya pedido claro, se activa estimacion.\n\n"
            "5. Vision 360 — Mejoras para Demos\n"
            "Fede propuso enriquecer la capa funcional de Vision 360 con detecciones simples "
            "ya resolubles para hacer demos mas convincentes en tiempo real:\n"
            "- Detectar cosas simples (personas, objetos) que muestren que la solucion funciona "
            "en tiempo real (no que sea un video pregrabado).\n"
            "- Instalar camara en la oficina para demos en vivo (sin que sea invasivo).\n"
            "- Los clientes no perciben la diferencia de complejidad entre detectar una veta de "
            "grasa en un ojo de bife vs. contar ganado. Mostrar lo simple como prueba de que "
            "funciona es valioso.\n"
            "- Investigar integracion de Vision 360 con plataformas estandar del sector "
            "(3-4 plataformas de Computer Vision usadas en oil & gas).\n\n"
            "6. Adopcion de IA en Desarrollo\n"
            "Se menciono brevemente (ya discutido en sesion anterior) el experimento de "
            "desarrollo con IA (Nomadear B2): 4 dias habiles vs. 30 estimados. Herramienta: "
            "Fathom para transcripciones de reuniones cruzadas con documentos para informes.\n\n"
            "Decisiones:\n"
            "- Foco Q2: dos POCs (Computer Vision + Trainly), sin abrir nuevos productos.\n"
            "- Para demos futuras: mostrar diferencial tangible o no salir a vender.\n"
            "- Proden: avanzar con la POC (linea de investigacion), definir alcance en reunion interna.\n"
            "- Servipet: esperar validacion del cliente antes de estimar.\n"
            "- Plan tactico Q2 con responsables y plazos: Seba agenda reunion con Mariano y Nai.\n\n"
            "Accionables:\n"
            "- [Seba + Mariano + Nai] Reunion para armar plan tactico Q2 con responsables/fechas.\n"
            "- [Mariano] Reunion del 25 con equipo: revisar propuesta TechPetrol Trainly.\n"
            "- [Mariano] Definir alcance POC Proden con Seba y equipo antes de comprometerse.\n"
            "- [Fede] Explorar enriquecimiento funcional de Vision 360 para demos en tiempo real.\n"
            "- [Fede] Armar lista de integraciones de Vision 360 con plataformas estandar del sector.\n"
            "- [Seba/Pau] Validar alineacion de Servipet antes de estimacion."
        ),
    },
    {
        "source_id": "630284863",
        "date": "2026-04-03",
        "title": "Alineacion I+D y Comercial — Equipo IMASD, Roadmap y Vertical Industrias",
        "content": (
            "Meeting: Alineacion I+D y Comercial — Equipo IMASD, Roadmap y Vertical Industrias\n"
            "Date: 2026-04-03\n"
            "Participants: Mariano Ortega, Sebastian Loizaga\n\n"
            "Contexto: Reunion 1:1 entre Mariano (lider de I+D / IMASD) y Sebastian (lider comercial "
            "vertical Industrias). Se comparte el estado del equipo, el roadmap de innovacion "
            "y se discute la estrategia de posicionamiento de los productos de la vertical.\n\n"
            "1. Estructura del Equipo de I+D (8 personas)\n"
            "El equipo tiene 5 verticales con los siguientes planes:\n"
            "- Inmersivo (Micael): avatares propios web y mobile + MetaHumans (primer semestre); "
            "entornos 3D generados con IA en tiempo real + experiencia Oculus (segundo semestre). "
            "Tambien: reconocimiento emocional en tiempo real, generacion de assets 3D, video inmersivo.\n"
            "- Robotica (Denis + Mati Araujo): evolucion del cuadrupedo (primer semestre), "
            "exploracion de humanoides y brazo robotico open source impreso en 3D (segundo semestre).\n"
            "- Agentes (Fran): producto principal es Agora — plataforma de recruiting/seleccion "
            "automatizada: carga de CVs, matching con IA, ranking, entrevista virtual con IA, "
            "reporte automatico. En pruebas internas en Flock. Proximo paso: Recursos Humanos de Bell. "
            "Version productiva estimada: abril-mayo. Se explora deteccion de identidades sinteticas "
            "para evitar que una IA responda a otra IA en entrevistas.\n"
            "- Computer Vision (Luisina): roadmap incluye Action Recognition, tracking multi-objeto, "
            "tracking multi-camara (REID), RAG sobre video (chat con IA sobre lo que ocurre en "
            "camara en vivo). Sistema de generacion de datasets sinteticos con etiquetado automatico.\n"
            "- Producto (Ian + Tomas): productos Trainly (plataforma de capacitacion con IA, "
            "multi-agent, en rediseno UX) y Vision 360. Para segundo semestre: FlockDocs y "
            "plataforma de monitoreo de robots (en evaluacion).\n\n"
            "2. OKRs y Planificacion Anual\n"
            "- Ciclo de OKRs de marzo a marzo. Algunos OKRs no se exponen a ADH por metodologia.\n"
            "- Objetivos de gestion: dashboard publico de innovacion con estadisticas y tiempos "
            "medios de cada etapa del proceso; segunda version de la landing con papers y casos.\n"
            "- OKR personal de Mariano: exploracion de computacion cuantica (certificacion + POCs).\n\n"
            "3. Agora — Posicionamiento y Demo para TechPetrol\n"
            "- Agora esta lista para demos guiadas (UX autonoma necesita mejora).\n"
            "- Sebastian sugiere mostrar Agora en la reunion con TechPetrol (donde estara RRHH).\n"
            "- Mariano confirma que si es posible mostrarla.\n\n"
            "4. Trainly — Debilidades y Proximos Pasos\n"
            "- Sebastian considera que el producto actual no pasaria una POC real. Faltan:\n"
            "  (a) Costos operativos (OPEX) definidos por segmento de empresa.\n"
            "  (b) Features diferenciales tangibles: manejo de imagenes, automatismo.\n"
            "- Propuesta: brainstorming con Mari y equipo de producto para definir valor "
            "diferencial y estrategia de precios.\n\n"
            "5. Vertical de Agentes — Pitch\n"
            "- La vertical de Agentes tiene el mayor potencial comercial de corto plazo segun Sebastian, "
            "pero el pitch actual es muy abstracto.\n"
            "- Mariano propone desarrollar material visual que muestre agentes interactuando "
            "en contexto industrial (oil & gas) para hacer la propuesta tangible.\n"
            "- Sebastian va a organizar una reunion con Fran para bajar el pitch a casos concretos.\n\n"
            "6. Computer Vision — Camara Termica y Pruebas\n"
            "- Se prueban camaras HikVision dual (termica + RGB). La camara termica NO detecta "
            "fugas de gas (el aire caliente no es visible en termica), pero SI detecta charcos "
            "de agua. Se planifican pruebas con spray.\n"
            "- El IP enviado por el proveedor es local (192.168.x.x) — no accesible remotamente. "
            "Se debe pedir que lo expongan a internet o envien acceso valido.\n\n"
            "7. Robotica — Cuadrupedo\n"
            "- Comercialmente sigue siendo 'verde': no sube escaleras, funciona semi-autonomo.\n"
            "- No se avanzara a humanoides sin madurez suficiente en cuadrupedo.\n"
            "- Plan: cerrar la investigacion con un caso en campo (agro, terrenos familiares de "
            "Rampa o Mali).\n\n"
            "8. Vision Estrategica — Evolucion de IA en Organizaciones\n"
            "Mariano describe el pipeline de madurez de IA organizacional:\n"
            "Automatizacion simple (N8N) → agente individual → multi-agente por area → "
            "orquestador digital de areas → protocolo Agent-to-Agent (A2A) para comunicacion "
            "entre sistemas de distintas empresas. El equipo explora A2A para septiembre.\n\n"
            "9. Acuerdos sobre POCs y Costos\n"
            "- POCs dentro del roadmap de investigacion: se pueden ofrecer sin costo.\n"
            "- POCs fuera del roadmap: deben estimarse y formalizarse como propuesta con valor "
            "(aunque comercial luego decida regalarlas), para que quede registrado como venta.\n\n"
            "Accionables:\n"
            "- [Mariano] Material visual de agentes en contexto industrial para fortalecer el pitch.\n"
            "- [Sebastian] Organizar reunion con Fran para bajar pitch de agentes a casos concretos.\n"
            "- [Sebastian/Mariano] En reunion con proveedor camara: informar que el IP es local "
            "y pedir acceso remoto.\n"
            "- [Equipo de producto - Tomas] Comenzar a dedicar tiempo a Trainly para demo TechPetrol.\n"
            "- [Sebastian + Mari + producto] Brainstorming features diferenciales Trainly + OPEX.\n"
            "- [Mariano] Corregir fechas desactualizadas en PPT roadmap Agentes/Agora.\n"
            "- [Primer semestre] Consolidar Trainly y Vision 360 antes de agregar nuevos productos."
        ),
    },
    {
        "source_id": "617451970",
        "date": "2026-03-27",
        "title": "1:1 Mariano Ortega y Marilyn Botheatoz — OKRs, Equipo, Agora y Aeropuertos",
        "content": (
            "Meeting: 1:1 Mariano Ortega y Marilyn Botheatoz — OKRs, Equipo, Agora y Aeropuertos\n"
            "Date: 2026-03-27\n"
            "Participants: Mariano Ortega, Marilyn Botheatoz\n\n"
            "Contexto: Reunion semanal 1:1 entre Mariano (lider IMASD) y Marilyn (coordinadora "
            "general del equipo de I+D). Se revisan OKRs, estado del equipo, Agora, N8N y "
            "la planificacion de reuniones con Aeropuertos Argentina.\n\n"
            "1. Alineacion con Equipo Comercial (Seba/Industrias)\n"
            "Se acuerda organizar una reunion con Seba y el equipo de Industrias para darles "
            "visibilidad sobre: (a) el presupuesto de ventas estimado de IMASD y (b) el roadmap "
            "de OKRs del equipo de I+D. El objetivo es que comercial entienda en que estadio de "
            "investigacion estaran y que pueden o no ofrecer a clientes.\n"
            "Mariano estara en Brasil la semana siguiente trabajando en horarios flexibles.\n\n"
            "2. OKRs de Marilyn — Retraso\n"
            "Marilyn no pudo avanzar en sus OKRs por estar sobrecargada con tareas de gestion: "
            "planes de carrera, entrevistas de evaluacion (Talent Review), feedback a su equipo "
            "(Denis, Mati Araujo, Pau, Jansu). El mismo ciclo se repetira en septiembre.\n"
            "Acuerdo: incorporar seguimiento de OKRs de Marilyn como item recurrente en las "
            "reuniones semanales.\n\n"
            "3. Evaluacion Individual del Equipo\n"
            "Luisina: mejor desempenio actual del equipo. Se indica al equipo de Talent que "
            "busquen perfiles similares en background academico y laboral.\n"
            "Tommy (equipo de producto): problema de escucha activa y ejecucion no alineada. "
            "En lugar de cerrar el pitch de Trainly como se le indico, se puso a hacer su "
            "propia version sin validarlo. Necesita supervision cercana.\n"
            "Mati Araujo y Denis: no usan todo su tiempo de forma productiva; se dispersan "
            "en tareas no solicitadas. Mati propuso diseno de sistema GPS para el robot sin "
            "que fuera prioridad; Denis construyo una base de conocimiento propia sin que se "
            "lo pidieran.\n"
            "Estrategia acordada: ponerles fechas de entrega con visibilidad externa (demos, "
            "reuniones con otras areas, compromisos con nombre importante). Esto funciona "
            "especialmente con Mati Araujo.\n"
            "Problema 'caja negra' en Robotica: el conocimiento generado por Mati y Denis "
            "no se transfiere. Si se fueran, la vertical quedaria en cero. Al terminar la POC, "
            "se hara una transferencia formal de conocimiento abierta al equipo/empresa.\n\n"
            "4. Estado Tecnico Robotica\n"
            "No queda claro el pipeline definitivo a partir del mapeo con LiDAR en simulacion "
            "virtual. Denis toma un camino y lo da por definitivo sin explorar alternativas. "
            "El patron se repitio varias veces: elige una ruta sin evaluar opciones mas simples.\n\n"
            "5. Agora — Bugs y Proximos Pasos\n"
            "Bugs criticos identificados:\n"
            "- Timeout de entrevistas configurado en 8 minutos (decisión temporal de Fran). "
            "Varias entrevistas se cortan sin despedida del avatar — clientes creen que esta rota.\n"
            "- Bug en creacion de entrevistas: algunas se crean con ID invalida, requieren "
            "recreacion manual (job description + CV + match).\n"
            "Plan: cuando vuelva Fran el lunes, corregir timeout y lista de bugs (estimacion: "
            "medio dia). Luego: reunion con equipo de Talent (Belen y Guada) para presentar "
            "Agora como MVP, aclarando que es MVP en prueba, no producto cerrado.\n\n"
            "6. N8N\n"
            "Mariano no pudo autenticarse en el entorno N8N de I+D en una charla. No esta "
            "claro quien tiene las credenciales. Esta en Railway; Fran era el usuario principal.\n"
            "Accion: cuando vuelva Fran, relevar estado del entorno N8N y documentar "
            "credenciales en Notion.\n\n"
            "7. Aeropuertos Argentina — Dos Reuniones Pendientes\n"
            "Reunion 1 — Propuesta evolutiva de ADA (totem de aeropuerto):\n"
            "- Mati Gassab genero documento con propuestas de innovacion no realistas "
            "(avatar que aprende solo, integracion automatica con sistemas de equipaje).\n"
            "- Lo viable con componente de innovacion: animacion de ADA (MetaHuman). "
            "El resto son mejoras operativas que puede hacer el equipo de operaciones.\n"
            "- Mati Gassab lidera la presentacion (ownership de el); Marilyn y Mariano revisan.\n"
            "- Formato: presentacion aspiracional sin compromisos duros de tiempos.\n"
            "Reunion 2 — Presentacion de innovacion de I+D:\n"
            "- Mati Gassab prometio ir presencial con todo el equipo de I+D incluyendo robot.\n"
            "- Problema: Mati Araujo esta en Espana hasta el dia 20 y el robot no esta disponible.\n"
            "- Alternativa: ir con PPT + videos del robot en lugar de demo en vivo.\n"
            "- Demos candidatas: Vision 360 (deteccion de personas), Trainly, 'hablar con los datos'.\n"
            "- MetaHuman no esta lista (le falta desarrollo en movimiento facial).\n"
            "- Denis no es candidato para llevar a la reunion (riesgo de decir algo inapropiado).\n"
            "- Decision: Mariano se reune con Mati Gassab para definir formato y participantes.\n\n"
            "8. PPT de Comite de Promocion — Marilyn (Instancia 4 a 5)\n"
            "Competencias evaluadas para instancia 5:\n"
            "APROBADAS: Diseno e implementacion de soluciones, Influencia en crecimiento, "
            "Servicio de excelencia, Desarrollo profesional.\n"
            "NO APROBADAS (aun): Verificacion y reporte, Conocimiento de negocio y estrategia "
            "de producto (falta definicion de KPIs de producto), Metodologia y mejora continua.\n"
            "Resultado: 4/7 aprobadas — valido para presentar al comite.\n"
            "Accion: Marilyn arma justificacion esta semana y la envia a Mariano y People.\n\n"
            "Accionables:\n"
            "- [Mariano + Marilyn] Organizar reunion con Seba e Industrias (presupuesto + roadmap).\n"
            "- [Marilyn] Agregar OKRs propios como item recurrente en reuniones semanales.\n"
            "- [Marilyn] Gestionar reunion con Belen y Guada (Talent) para presentar Agora MVP.\n"
            "- [Marilyn + Fran] Corregir timeout (8 min) y bugs de creacion de entrevistas en Agora.\n"
            "- [Marilyn + Fran] Documentar credenciales N8N en Notion y relevar estado del entorno.\n"
            "- [Mati Gassab (revision de Marilyn/Mariano)] Presentacion aspiracional para Aeropuertos.\n"
            "- [Mariano] Reunirse con Mati Gassab para definir formato reunion de innovacion.\n"
            "- [Marilyn] Terminar PPT comite instancia 5 y enviar a People y Mariano esta semana.\n"
            "- [Mariano + Marilyn] Organizar transferencia de conocimiento de Robotica al cerrar POC.\n"
            "- [Continuo] Estrategia de fechas externas/demos para encauzar a Mati Araujo y Denis."
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
