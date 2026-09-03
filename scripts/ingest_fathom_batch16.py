"""Ingest Fathom transcripts batch 16 (recordings 580724261, 579106305)."""
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
        "source_id": "580724261",
        "date": "2026-02-13",
        "title": "1:1 Mariano y Marilyn — Planificacion OKRs I+D, Agora, Robotica y Vision",
        "content": (
            "Meeting: 1:1 Mariano y Marilyn — Planificacion OKRs I+D, Agora, Robotica y Vision\n"
            "Date: 2026-02-13\n"
            "Participants: Mariano Ortega, Marilyn Botheatoz\n\n"
            "Contexto: Reunion 1:1 de planificacion de OKRs del equipo de I+D para el ano. "
            "Mariano y Marilyn revisan el borrador de OKRs de Marilyn y definen la estructura.\n\n"
            "1. Estructura General de OKRs\n"
            "- Antes de presentar los OKRs a Federico, validarlos con cada integrante del equipo "
            "para que esten comodos y puedan plantear modificaciones.\n"
            "- A cada OKR hay que agregar a que iniciativa estrategica le pega.\n"
            "- Calendarizar los OKRs por mes, con buffer de tiempo libre (no planificar al 100%). "
            "El equipo va a recibir tareas no planificadas; hay que tener margen.\n"
            "- Estrategia: algunos OKRs son publicos/externos (se muestran a toda la empresa) y "
            "otros son internos (solo para seguimiento propio). Los internos son el 'backlog libre'. "
            "De cara al equipo solo se muestran los externos; si algo urgente cae, se pausa un interno.\n\n"
            "2. Agora — Mejoras y Version para Candidatos\n"
            "- UX actual de Agora tiene complejidad: el usuario tiene que crear el match, luego ir "
            "a otra parte, etc. Falta simplificacion. Marilyn ve mas forte a Janssen que a Tommy "
            "para hacer el rediseno. Mariano propone modularizar la app: paquete de prueba de "
            "conocimiento, paquete de entrevista, etc.\n"
            "- Agora version para candidatos (publica): version con otro perfil de usuario (no "
            "solo talent interno). Fran ya tiene el contexto del producto completo; lo ideal es "
            "que lo desarrolle el. Producto haria el discovery de UX/UI de esa version. "
            "Agrego al roadmap de Agora: 'Discovery de Agora para candidatos' y "
            "'Optimizacion de Agora para talent — Rediseno de flujos y experiencia'.\n\n"
            "3. Robotica — Roadmap y Casos de Uso\n"
            "- Primer semestre: finalizar POC del cuadrupedo (navegacion autonoma, los pasos "
            "ya planificados). El humanoide viene como 'premio' de haber cerrado las etapas del perro.\n"
            "- Segundo semestre: exploracion de humanoides y brazo robotico.\n"
            "- Brazo robotico: el de tres dedos sirve para pick & place basico; el de cinco "
            "tiene mas sensibilidad para tareas de precision. Pendiente: diferencia entre G1 y R1.\n"
            "- Explorar NVIDIA Omniverse e Isaac Sim: entornos virtuales de NVIDIA para "
            "Reinforcement Learning y simulacion mundo real. Isaac Sim Replicator para generacion "
            "de datos sinteticos de robots. A agregar al roadmap (Mariano quiere que sea "
            "semestre 1 o 2).\n"
            "- POC Agro con cuadrupedo: encontrar un campo y hacer una prueba real "
            "(caso de uso: el robot recorre verticales de siembra y con CV detecta anomalias/plagas, "
            "lo que el drone no puede hacer porque ve de arriba). Potencial contacto: Venturino "
            "o contactos de Syngenta/Alatanzi.\n"
            "- Denis no vino a la daily sin avisar (preocupacion).\n\n"
            "4. Avatares — Limitaciones y Evolucion\n"
            "- MetaHuman renderizado web: para renderizar con calidad en entornos web, se necesita "
            "una computadora muy potente detras de la pantalla. Se pixela en web comun. Costo de "
            "hardware elevado para los clientes. Dos caminos distintos: MetaHuman (alta calidad, "
            "hardware especifico) vs. video generativo (escala mejor en web y celular).\n"
            "- Video generativo: la mayoria de las plataformas actuales de avatares usan video "
            "generativo (no MetaHuman). Ejemplo: plataforma Replica con modelo propio. Siempre "
            "se depende de un modelo de terceros (mismo problema que con otras herramientas).\n"
            "- Decision: continuar investigando MetaHuman para demos de alta calidad (ej. totem), "
            "y explorar video generativo como alternativa para casos web/mobile.\n"
            "- Segundo semestre: foco en experiencia inmersiva (mayor potencial comercial que "
            "los totems). POC de Oculus/entorno inmersivo con IA generativa.\n\n"
            "5. Vision — Lineas de Investigacion\n"
            "- Action Recognition: reconocimiento de acciones en video. Interesante.\n"
            "- Re-ID (re-identificacion): seguimiento de la misma identidad a traves de "
            "multiples camaras. Muy vendible operativamente.\n"
            "- Vision Language Models (VLM): hablar con una IA sobre lo que ocurre en camaras "
            "en vivo. El estado del arte a explorar.\n"
            "- Synthetic Data Generation: ya en curso con Luisina para la POC de derrames.\n\n"
            "6. Agente Autonomo — Experimento Personal de Mariano\n"
            "Mariano esta corriendo un agente autonomo (OpenCloud en Oracle Cloud VPS gratuita: "
            "24 GB RAM, 512 GB storage, Ubuntu) que trabaja en un kanban propio codeando "
            "de forma desatendida. El agente pasa las cards del kanban (en JSON) y va "
            "pusheando al GitHub. Tuvo un problema: cuando se le acabaron los tokens del modelo "
            "principal (Codex), uso un fallback que borro el JSON del kanban. Solucion: Claude "
            "recupero los archivos; pendiente subir cambios del JSON al repo o usar BD.\n"
            "Experimento mostrando: que se puede armar un equipo de ingenieria de IA que "
            "tome un requerimiento y lo resuelva de forma semi-autonoma con crons y notificaciones "
            "por Telegram cuando algo se traba.\n\n"
            "7. Concepto 'Segundo Cerebro I+D'\n"
            "Mariano y Marilyn discuten agregar a los OKRs un QR de 'crear el segundo cerebro "
            "de I+D' — un sistema multiagente que tenga acceso a metricas, papers, proyectos "
            "y minutas del equipo, y pueda responder consultas, proponer OKRs o lineas de "
            "investigacion. Como evolucion: que pueda ser invitado a una reunion y participar. "
            "Para empezar: chatbot de consulta; luego autonomia creciente.\n\n"
            "8. Protocolo A2A y Reinforcement Learning\n"
            "Dos POCs pendientes de linkear a productos concretos. Marilyn propone primero "
            "explorarlas como tecnologia y luego ver donde aplicarlas.\n\n"
            "Accionables:\n"
            "- [Marilyn] Validar OKRs con cada integrante del equipo antes de presentar a Fede.\n"
            "- [Marilyn] Armar tabla con OKRs externos vs. internos y calendarizarlos por mes.\n"
            "- [Marilyn] Agregar al roadmap de Agora: discovery version candidatos + "
            "optimizacion version talent.\n"
            "- [Mariano] Agregar NVIDIA Omniverse/Isaac Sim al roadmap de Robotica.\n"
            "- [Mariano] Explorar campo para POC agro con cuadrupedo (contactar Venturino).\n"
            "- [Mariano] Resolver agente autonomo: mover kanban de JSON a BD o repo estructurado.\n"
            "- [Marilyn] Armar los OKRs en formato SMART con KPIs para presentar a Fede."
        ),
    },
    {
        "source_id": "579106305",
        "date": "2026-02-12",
        "title": "1:1 Mariano y Marilyn — OKRs I+D, ECC, Avatares, Robotica y Computer Vision",
        "content": (
            "Meeting: 1:1 Mariano y Marilyn — OKRs I+D, ECC, Avatares, Robotica y Computer Vision\n"
            "Date: 2026-02-12\n"
            "Participants: Mariano Ortega, Marilyn Botheatoz\n\n"
            "Contexto: Continuacion de la planificacion de OKRs del equipo de I+D. "
            "Se revisan las verticales restantes: ECC, Avatares, Robotica y Computer Vision.\n\n"
            "1. Documentacion para Ley de Economia del Conocimiento (ECC)\n"
            "Para que Flock pueda certificar la Ley de Economia y Conocimiento (beneficios "
            "fiscales muy importantes), el equipo de I+D debe documentar sus proyectos "
            "segun los formatos requeridos por Ciudad de Buenos Aires y Nacion. La documentacion "
            "no requiere mucho esfuerzo adicional (un documento justificando el proyecto + "
            "un repositorio especifico). Mariano quiere que esto sea visible como OKR "
            "porque el impacto fiscal para Flock es muy alto. Paso siguiente: convertir "
            "los accionables en formato OKR (SMART) con KPIs definidos.\n\n"
            "2. Proceso de Investigacion — Framework\n"
            "La salida de cada linea de investigacion debe ser formalizada: o como un paper "
            "o como un entregable/demo. Los papers alimentan la landing de IMASD.\n"
            "Debate sobre la vertical de producto: el proceso de investigacion tradicional "
            "(hipotesis → validacion → resultado) aplica a las verticales de innovacion, pero "
            "no tan bien a producto (que responde a demanda de la empresa, no a hipotesis propias). "
            "Solucion: dentro de producto agregar investigaciones sobre herramientas para "
            "buildear producto de forma innovadora y hacia donde va el desarrollo con IA.\n\n"
            "3. Avatares — Video Generativo vs. MetaHuman\n"
            "La mayoria de las plataformas actuales de avatares comerciales usan video generativo "
            "(no MetaHuman/Unreal Engine). Las plataformas web-based tienen modelos propios "
            "de generacion de video (ej. Replica). Problema: siempre se depende de un modelo "
            "de terceros con su propio pricing.\n"
            "MetaHuman en Unreal: renderizado de alta calidad, pero requiere hardware muy potente "
            "para ser fluido en un totem. En web se pixela. La diferencia de costo de hardware "
            "es muy significativa para los clientes.\n"
            "Estrategia: primer semestre = cerrar Avatares (avatar propio web + MetaHuman). "
            "Segundo semestre = foco en experiencia inmersiva (mayor potencial de compra, "
            "hay necesidad real de clientes). POC de Oculus con entorno generado con IA.\n"
            "Investigacion de herramientas para crear experiencias inmersivas: Unity tiene "
            "generador de 3D propio. Herramientas de AI para crear videojuegos y experiencias "
            "de realidad aumentada. Caso de uso mencionado: real estate (visualizacion de "
            "propiedades en 3D recorrible a partir de fotos).\n\n"
            "4. Robotica — Casos de Uso\n"
            "Caso de uso agro con cuadrupedo: el robot recorre verticales de siembra "
            "y con CV detecta anomalias y plagas desde abajo hacia arriba "
            "(el drone no puede hacerlo porque ve solo desde arriba). El informe de "
            "cosecha en Syngenta hoy es manual: persona caminando, sacando fotos con el "
            "celular y anotando en una libreta. Hay modelos que identifican plagas y "
            "anomalias en cultivos — el robot puede automatizarlo.\n"
            "Segundo semestre: exploracion de humanoides y operacion. Pendiente: diferencia "
            "entre los modelos G1 y R1 de los distintos humanoides.\n\n"
            "5. Computer Vision — Lineas de Investigacion\n"
            "Lineas activas y nuevas identificadas:\n"
            "- Generacion de datasets sinteticos con etiquetado con IA (en curso con Luisina).\n"
            "- POC derrames oil & gas (en curso con Proden).\n"
            "- Action Recognition: reconocimiento de acciones en video.\n"
            "- Re-ID (re-identificacion multi-camara): seguimiento de la misma identidad a "
            "traves de multiples camaras. Caso operativo muy vendible.\n"
            "- Vision Language Models (VLM): hablar con IA sobre lo que ocurre en camaras en vivo.\n"
            "- Investigacion de tracking multi-objeto.\n"
            "Lineas que se sacan del roadmap de I+D: deteccion especifica de incendios "
            "y gas (son casos operativos 'plug and play', no investigacion original). "
            "Una vez que la POC de derrames tenga el proceso definido, los casos similares "
            "pueden hacerlos operaciones sin que sea investigacion nueva.\n\n"
            "6. Agora — Proceso para la POC de Proden (Vista)\n"
            "Luisina ya leyo el documento y viene con consultas y dudas. Tiene contexto de "
            "que Proden es una POC con potencial de MVP. Luisina sabe que ella y Guille "
            "probablemente la van a ejecutar.\n"
            "Punto critico de tiempos: el mes estimado para entrenar el modelo corre despues "
            "de que el cliente genere los registros de simulaciones, no desde que se mandan "
            "las camaras. Hay que dejarle claro al cliente que el mes empieza cuando "
            "Flock recibe los videos de las simulaciones.\n\n"
            "7. Vertical de Producto — OKRs\n"
            "Los chicos de producto (Tomas, Ian) deben pensar que innovacion pueden "
            "proponer en sus productos, que herramientas o enfoques pueden explorar, "
            "para no estar solo respondiendo a la demanda de la empresa sino tambien "
            "generando ideas propias. Fran hace lo mismo desde la vertical de agentes.\n\n"
            "Accionables:\n"
            "- [Marilyn] Continuar armando OKRs verticales restantes (producto).\n"
            "- [Marilyn] Armar OKRs en formato SMART con KPIs; definir internos vs. externos.\n"
            "- [Marilyn] Preparar reunion con el equipo de Proden/Vista para clarificar "
            "tiempos del modelo (el mes corre desde los videos de simulacion).\n"
            "- [Mariano/Marilyn] Agregar casos de uso agro al roadmap de robotica.\n"
            "- [Marilyn] Seguir investigando herramientas de experiencias inmersivas "
            "y generacion 3D con IA para el segundo semestre."
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
