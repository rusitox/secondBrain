"""Ingest Fathom transcripts batch 5 (recordings 736225755, 734233643)."""
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
        "source_id": "736225755",
        "date": "2026-07-06",
        "title": "Revision Back Office I+D, TaxFlow y Workshop Comercial — Mariano + Fede",
        "content": (
            "Meeting: Revision del back office de I+D, integracion con TaxFlow y propuesta comercial del workshop\n"
            "Date: 2026-07-06\n"
            "Participants: Mariano Ortega, Federico Valentino Lacoste\n\n"
            "1. Presentacion de la landing y back office de I+D\n"
            "Mariano mostro el rediseno de la landing publica del area de I+D. "
            "La landing expone verticales de investigacion, proyectos activos e iniciativas. "
            "Esta alimentada por un back office propio que actua como CMS.\n\n"
            "Estructura del back office:\n"
            "- CMS de contenidos: publicaciones, papers, noticias, actualizaciones de miembros del equipo.\n"
            "- OKRs: replicando informacion que antes estaba en Excel. OKRs internos y externos, "
            "verticales asignadas, planes mensuales, seguimiento por integrante.\n"
            "- Plan de accion: miembros del equipo cargan tareas diarias vinculadas a iniciativas y OKRs. "
            "El sistema cruza lo planificado con lo ejecutado mediante IA para detectar desvios. "
            "Lideres generan reportes mensuales de cumplimiento.\n"
            "- Iniciativas de investigacion: flujo formal de aprobacion (pedido -> aprobacion -> 5 etapas). "
            "Cada iniciativa tiene wiki, hipotesis, KPIs, repositorio en Markdown, links a publicaciones.\n"
            "- Vista estrategica (pendiente): capa para management/socios sin nivel de detalle operativo.\n\n"
            "Feedback de Fede sobre la landing:\n"
            "- Landing y sitio de Flock tienen identidades visuales distintas y no integradas.\n"
            "- Falta link navegable de regreso al sitio principal de Flock.\n"
            "- Logo de Flock no aparece en landing de I+D.\n"
            "- Usar solo nombres de pila de los miembros (no apellido completo).\n"
            "- Las presentaciones no deben depender de links a herramientas externas (ej. Gamma); "
            "exportar dentro del ecosistema propio.\n\n"
            "Objetivo declarado del back office: 'Segundo Cerebro de I+D' con toda la documentacion en "
            "Markdown para consultas con IA. La generacion de evidencia actual alimenta ese sistema RAG.\n\n"
            "2. Integracion entre back office de I+D y TaxFlow\n"
            "Fede presento TaxFlow, plataforma centralizada de gestion de tareas y OKRs para toda la empresa.\n"
            "Funcionalidades TaxFlow:\n"
            "- OKRs: ciclos mensuales con iniciativas estrategicas por area, seguimiento de KPIs y metricas, "
            "alertas automaticas, reportes/presentaciones automaticas para socios.\n"
            "- Integracion bidireccional con ClickUp para equipos que ya lo usan.\n"
            "- Vinculacion de proyectos I+D: plan de accion solo lectura desde TaxFlow; tareas se gestionan "
            "desde la app de I+D.\n"
            "- Single Sign-On Microsoft: TaxFlow ya lo soporta; I+D pendiente de implementar.\n"
            "- Asistente IA integrado: responde preguntas sobre estado de la app, genera reportes y graficos, "
            "produce presentaciones para management.\n\n"
            "Discusion sobre la sincronizacion I+D <-> TaxFlow:\n"
            "- Mariano resolvio provisionalmente usando un skill de Claude que consume la API de TaxFlow "
            "(uso cookies del navegador en lugar del token oficial de API).\n"
            "- Flujo acordado: UNIDIRECCIONAL (I+D postea hacia TaxFlow, no a la inversa).\n"
            "- Mariano crea unico proyecto en TaxFlow para I+D, verticales como carpetas.\n"
            "- Integracion oficial con token de API: pendiente para cuando vuelva Mari (desarrolladora del back office).\n\n"
            "3. Propuesta comercial del workshop\n"
            "- Informe ya generado. Reducir valor de entrada a aprox. USD 900-1000, con opciones de continuacion.\n"
            "- Contenido valorado positivamente; modificacion principal es ajustar valores economicos.\n"
            "- Candidato para dar el taller: Fran (en Mar del Plata, descartado por logistica). "
            "Tommy es alternativa a evaluar.\n"
            "- Es un workshop de I+D; Santi debe estar al tanto pero no ejecutara.\n\n"
            "4. Demo en reunion de Vistage (anecdota)\n"
            "Fede mostro en Vistage como usar IA para generar una aplicacion funcional completa en ~1 hora "
            "usando Claude Code (algo que normalmente lleva 6 meses y 4-5 personas, ~ARS 180M). "
            "Impacto muy fuerte; un participante resolvio a la 1 AM un problema pendiente de meses "
            "usando lo aprendido.\n\n"
            "5. Herramienta de marketing con IA (idea propuesta)\n"
            "- Analizaria la marca (sitio web, redes, SEO) para entender posicionamiento.\n"
            "- Parametrizaria proporciones de contenido (marca empleadora / contenido util / orientado a ventas).\n"
            "- Generaria calendarios de posteos y borradores de copy.\n"
            "- Se integraria con Brandbox para que Natalia de marketing valide y publique.\n"
            "- Involucrar a Barbara (marketing + conocimientos Claude Code) como co-desarrolladora.\n\n"
            "6. Pruebas de concepto con robot cuadrupedo\n"
            "Tres empresas pymes disponibles para pruebas (via Fede):\n"
            "1. Fabrica de inyeccion de plastico (zona General Rodriguez) — certificada ISO 9001.\n"
            "2. Panificadora (zona Quilmes/Bernal) — proceso con restricciones de contaminacion.\n"
            "3. Fabrica/reparacion de pallets — caso de uso EPP deteccion de clavos mal doblados.\n"
            "Descartado uso del robot en Oil & Gas por restricciones de seguridad (vapores/explosivos).\n"
            "Caso mas prometedor: fabrica de pallets por EPP rapido de implementar.\n\n"
            "Decisiones:\n"
            "- Landing I+D: agregar logo Flock, link regreso, nombres de pila, exportar presentaciones al ecosistema propio.\n"
            "- Sincronizacion I+D <-> TaxFlow: unidireccional. Integracion oficial con token API cuando vuelva Mari.\n"
            "- Mariano crea proyecto en TaxFlow hoy con carpetas por vertical.\n"
            "- Workshop cotizado en USD 900-1000, propuesta a Santi pronto.\n"
            "- Robot cuadrupedo en Oil & Gas: descartado.\n"
            "- Herramienta de marketing con IA: I+D ideara el producto; posiblemente Barbara lo implemente.\n\n"
            "Accionables:\n"
            "- Mariano: crear proyecto TaxFlow hoy, pasar lista emails equipo a Fede.\n"
            "- Mariano: ajustar landing I+D (logo, link, nombres).\n"
            "- Mariano: coordinar con Nati integracion visual de landing con sitio Flock.\n"
            "- Mariano: contactar tres referentes de pymes para visitas y definir caso de uso del robot.\n"
            "- Mariano: definir quien da el workshop y ajustar valor en propuesta para Santi.\n"
            "- Fede: pasar contactos de duenos de pymes (pallets, panificadora, plastico).\n"
            "- Mari (cuando vuelva): implementar integracion oficial API entre back office I+D y TaxFlow."
        ),
    },
    {
        "source_id": "734233643",
        "date": "2026-07-03",
        "title": "Reunion Semanal Industrias — TecPetrol, Chevron, Trainly, Robot, TGS",
        "content": (
            "Meeting: Reunion semanal de industrias — Seguimiento comercial Oil & Gas\n"
            "Date: 2026-07-03\n"
            "Participants: Mariano Ortega, Sebastian Loizaga, Federico Valentino Lacoste, Paula Vejrup\n\n"
            "1. Kickoff con TecPetrol (TECPE)\n"
            "Kickoff realizado exitosamente el miercoles previo. Participaron Guille, Fernando Arjona, Jorge, Nati.\n"
            "Primera reunion de reglamento ese mismo dia (viernes) con equipo de Neuquen, de forma remota.\n"
            "Se requieren accesos corporativos: mail de TECPE para el equipo y acceso a Jira de ellos.\n"
            "Una vez obtenidos los accesos (estimado 2-3 semanas), el equipo viajara a Neuquen.\n"
            "Fernando (Fer) no puede llevar el proyecto solo; hay que dimensionar el equipo.\n"
            "TecPetrol quiere que Flock tome su backlog y lo gestione.\n"
            "Seba planifica reunion pequena (el + Nati + Pau) con coordinador del backlog en TECPE antes "
            "de involucrar mas personas. El backlog se migrara a Jira con criterios de priorizacion y business case.\n"
            "Mariano propone a AUS (Agustin) para soporte operativo con Jira (bueno en gestion de proyectos).\n\n"
            "2. Viaje comercial a Neuquen\n"
            "Seba plantea visita comercial adicional a Neuquen (ademas de la tecnica de TECPE).\n"
            "Propuesta de Fede: 3 a 5 dias, minimo 2 reuniones por dia. Involucrar SDRs de Accion "
            "(consiguieron contactos de TECPE) para bombardear petroleras de la zona.\n"
            "Revisitar contactos existentes (Vista, el 'pelado') y explorar nuevas areas en cada empresa "
            "(ej. sistemas, sala de monitoreo).\n"
            "Mariano: aprovechar para contactar areas de sistemas en clientes donde solo se hablo con area "
            "de negocio, para detectar necesidades tecnologicas desde otro angulo.\n"
            "Fede: identificar en todas las petroleras al responsable de la sala de monitoreo "
            "(perfil clave, suele estar en Neuquen presencialmente).\n"
            "Pendiente: validar aprobacion general del viaje antes de formalizarlo.\n\n"
            "3. TGS — Prueba de concepto de analitica de video\n"
            "Reunion presencial con TGS esa semana, resultado positivo. Asistencia presencial con mas personas.\n"
            "Acordado: primera prueba de concepto de analitica de video (discovery).\n"
            "TGS proveera videos existentes de eventos de seguridad patrimonial (intrusion, incendio).\n"
            "Objetivo: demostrar capacidades con esos videos, acotar solucion a ese primer paso "
            "(ciberseguridad e IT querian agregar requisitos que complicaban todo).\n"
            "Contexto: relacion con TGS viene de ~15 reuniones sin cierre; nuevas personas del lado del "
            "cliente es senal positiva de avance.\n\n"
            "4. Robot cuadrupedo — Estrategia y casos de uso\n"
            "El perro robotico NO debe ofrecerse para Oil & Gas / refineria: en reunion con Raizen se "
            "perdieron 2 horas hablando del robot en contexto de refineria, inviable por vapores y "
            "clasificacion de areas explosivas. El robot es como 'una bomba molotov' en ese entorno.\n"
            "Casos de uso VALIDOS para el robot:\n"
            "- Inspeccion en subestaciones electricas: si.\n"
            "- Entornos industriales sin vapores/gases: si.\n"
            "- Patrullaje autonomo en zonas seguras: si.\n"
            "- Refinerias / Oil & Gas: NO.\n"
            "Mariano: transferencia comercial de la linea de robotica ese mismo dia (formalizara casos de uso).\n"
            "POC alternativas: tres empresas pymes de Fede (plastico, panificadora, pallets) sin restricciones.\n"
            "Utiles para: validar tecnologia en entornos flexibles, generar casos de exito, material de ventas.\n\n"
            "5. Reunion con Chevron\n"
            "Reunion confirmada para la semana siguiente. Asistiran Seba, Fatima y otros.\n"
            "Estrategia: equipo Chevron 100% operativo (gerencia de operaciones).\n"
            "NO presentar nada tecnico; usar material visual (fotos del proceso, capturas).\n"
            "Mensaje central: 'Somos expertos en PAI (AVEVA) y podemos ayudarlos a contextualizar "
            "y explotar sus datos operativos'.\n"
            "PAI/AVEVA identificado como la oportunidad mas clara para Chevron: muy atrasados en "
            "digitalizacion comparado con TECPE.\n"
            "Trainly tambien se mencionara como posible necesidad (fue lo primero que preguntaron antes).\n"
            "Georeferenciacion/tracking de cuadrillas: con cautela. Mariano: esa linea de investigacion "
            "aun no inicio; si preguntan, decir 'tenemos una linea de investigacion arrancando'.\n"
            "Fede: en primeras reuniones exploratorias no hablar tecnicamente; esperar interes concreto "
            "para meter perfiles tecnicos.\n\n"
            "6. PAI / AVEVA — Oportunidad transversal\n"
            "TECPE tiene 50.000 variables y solo 2 personas dedicadas a administrar PAI. YPF probablemente "
            "tenga un batallon.\n"
            "Modelo de negocio propuesto por Seba: centralizar la administracion de PAI como servicio "
            "compartido entre varias petroleras. Un especialista da servicio a TECPE, Chevron y otras "
            "simultaneamente, abaratando costos por economia de escala.\n"
            "Cristian Castro (3 certificaciones AVEVA) identificado como perfil clave para este modelo.\n"
            "Raizen ya menciono AVEVA en una reunion reciente, mostrando interes.\n"
            "Pendiente: una vez haya algo concreto post-Chevron, evaluar hablar con Cristian sobre el "
            "modelo comercial.\n\n"
            "7. Techin\n"
            "Techin tiene maquina de impresion 3D de concreto y tecnologia Motion Vision.\n"
            "Reunion de media hora exploratoria la semana siguiente. Asistiran Jorge, Guille y Seba.\n"
            "Flock fue proveedor de Techin en el pasado (via ACCIONA).\n"
            "Objetivo: entender situacion de Techin y ver como Flock puede ayudar en productividad.\n\n"
            "8. HubSpot (CRM) — Visibilidad comercial\n"
            "Pipeline en HubSpot no esta categorizado por industria ni tipo de producto, dificultando "
            "visibilidad de oportunidades de Industrias.\n"
            "Fede propone: etiquetas por segmento (industria) y por producto ofrecido (PAI, analitica "
            "de video, Trainly).\n"
            "Mariano: ya se empezaron a agregar etiquetas a oportunidades de I+D por pedido de Business.\n"
            "Posibilidad de conectar Claude con HubSpot para consultas en lenguaje natural sobre propuestas "
            "comerciales (requiere token de usuario).\n\n"
            "9. Trainly — Modelo comercial y negociacion con TECPE\n"
            "Trainly: producto propio de Flock para capacitacion. Interesados: TECPE, TGS, Sin Gente, "
            "Wordleafs, Fideopampa. Ningun cierre.\n"
            "Problema: modelo de licencias por usuario + tokens demasiado complejo; nadie entiende "
            "cuanto va a pagar.\n"
            "TECPE pidio bajar precio de USD 6.000 a USD 3.000; tienen desarrollo interno que dicen que compite.\n"
            "Decision: bajar a USD 3.000 y mandarlo ya, sin mas demoras.\n"
            "Propuesta estrategica alternativa discutida: vender como software a medida (pago unico, "
            "sin licencias). Cuando el cliente quiera evolucionar, Flock vende el desarrollo del cambio. "
            "Cuando Flock agregue funcionalidades (ej. realidad aumentada), se las muestra al cliente.\n"
            "Warning de Mariano: riesgo de seguir buscando modelo perfecto es que el tren se pasa "
            "(como ocurrio con Praia). El producto ya esta hecho; hay que ser mas agresivos.\n"
            "Reunion pendiente de redefinicion del modelo comercial de Trainly: Fatima, Jorge, Rampa. "
            "Fede pidio ser incluido junto con Mariano. Fede toma rol de moderador.\n"
            "Reunion de Trainly con Medellin: cancelada ese dia porque Gustavo no podia asistir.\n\n"
            "Decisiones:\n"
            "- TECPE: ejecutar primer proyecto lo mas rapido posible. AUS apoya operativamente con Jira.\n"
            "- Viaje a Neuquen: validar aprobacion; planificar agenda 3-5 dias con 2+ reuniones por dia.\n"
            "- Robot: NO proponer en Oil & Gas/refinerias. Restringir a entornos sin gases/vapores.\n"
            "- Trainly/TECPE: bajar precio a USD 3.000 y mandarlo ya.\n"
            "- Trainly modelo comercial: evaluar venta como software a medida (pago unico, sin licencias). "
            "Fede y Mariano participaran en reunion de definicion.\n"
            "- HubSpot: categorizar oportunidades por industria y producto.\n"
            "- Chevron: presentar PAI como mensaje principal, material visual, sin jerga tecnica.\n\n"
            "Accionables:\n"
            "- Seba: dimensionar equipo para proyecto TECPE hoy y formalizarlo.\n"
            "- Seba: organizar reunion pequena con coordinador del backlog de TECPE (el + Nati + Pau).\n"
            "- Seba: validar aprobacion del viaje comercial a Neuquen con management.\n"
            "- Seba + Fatima: preparar presentacion para Chevron (visual, foco en PAI).\n"
            "- Seba: enviar propuesta de Trainly a TECPE con precio USD 3.000 sin demoras.\n"
            "- Seba: invitar a Fede y Mariano a reunion de redefinicion comercial de Trainly.\n"
            "- Fede: tomar rol de moderador en reunion de redefinicion de Trainly.\n"
            "- Fede: pasar contactos de 3 pymes a Mariano para visitas con robot.\n"
            "- Paula: confirmar con Jorge detalles de reunion con Techin.\n"
            "- Mariano: sacar de invitacion recurrente a Agus Villegas (convocar solo cuando sea necesario).\n"
            "- AUS (Agustin): apoyar operativamente el armado de Jira para proyecto TECPE."
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
