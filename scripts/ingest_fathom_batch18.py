"""Ingest Fathom transcripts batch 18 (recordings 577704784, 575870639)."""
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
        "source_id": "577704784",
        "date": "2026-02-10",
        "title": "1:1 Mariano y Marilyn — Performance equipo, OKRs y roadmap I+D",
        "content": (
            "Meeting: 1:1 Mariano y Marilyn — Performance equipo, OKRs y roadmap I+D\n"
            "Date: 2026-02-10\n"
            "Participants: Mariano Ortega, Marilyn Botheatoz\n\n"
            "Contexto: Reunion 1:1 previa a la preparacion de OKRs del equipo I+D. "
            "Mariano y Marilyn discuten performance del equipo, el plan de OKRs para presentar "
            "a Fede, el roadmap de distintas verticales y el concepto de segundo cerebro IMASD.\n\n"
            "1. Performance del Equipo\n"
            "Discusion sobre un miembro del equipo (desarrollador de Unreal/Unity) con ritmo "
            "de trabajo lento. Marilyn analiza: falta de seniority, experiencia laboral acotada "
            "y muy especifica, primera reaccion ante desafios nuevos es el miedo. Sin embargo "
            "el interes y compromiso existen. Estrategia: ir pidiendole cosas progresivamente "
            "para aumentar la productividad sin generar presion excesiva. Mariano coincide: "
            "acompanarlo para ganar ritmo, no un problema sino una etapa de desarrollo.\n"
            "Tommy y Janssen trabajando bien juntos (mencionado brevemente).\n\n"
            "2. Estrategia OKRs con Fede\n"
            "Federico ya pidio reunion para definir OKRs. Mariano decide no ir todavia: quiere "
            "preparar propuesta propia del equipo de I+D (con Marilyn) antes de la reunion, "
            "para que los OKRs reflejen lo que realmente pasa en IMASD y no quedarse solo "
            "respondiendo a lo que pide Fede. Plan: juntarse manana y el miercoles para "
            "armar propuesta concreta antes de la reunion con Fede.\n\n"
            "3. OKRs Generales IMASD\n"
            "Revisando borrador de OKRs:\n"
            "- Actualizacion de landing de IMASD (externo — visibilidad de desarrollos del equipo).\n"
            "- Dashboard de avances de verticales con metricas del equipo (puede ser externo "
            "si tiene sentido para que Fede vea metricas). Idea: en la URL de landing de IMASD "
            "agregar seccion con login y tracking de cada vertical con metricas.\n"
            "- Informe de tendencias 2026 (externo — sirve comercialmente y para visibilidad). "
            "Ya empezado, terminarlo no llevaria mucho tiempo.\n"
            "- Participar de alguna hackathon externa.\n"
            "- Sistema de seguimiento de OKRs y verticales (herramienta interna + externa).\n\n"
            "4. Segundo Cerebro IMASD — Sistema Multiagente\n"
            "Marilyn propone un sistema multiagente que:\n"
            "- Los miembros del equipo suban audios/notas y el sistema los procese.\n"
            "- Genere un dashboard de avance de verticales con metricas.\n"
            "- Un agente evaluador compare el progreso real vs. el estimado y genere alertas.\n"
            "- Muestre el estado de cada vertical con colores (rojo si atrasado).\n"
            "- Permita chatear con el sistema para conocer el estatus y por que hay atrasos.\n"
            "Mariano lo ve viable y lo amplia: que crezca con memoria, que Fede pueda acceder "
            "y consultar al bot sin necesitar reuniones. Consideran unificar el dashboard "
            "y el sistema multiagente en un solo producto con nombre marketero.\n\n"
            "5. Avatares — Roadmap\n"
            "OKRs de Avatares pendientes:\n"
            "- Agente conversacional con personaje animado (hada u otro, diferente al humano ya hecho).\n"
            "- Digital clone: empezar con personaje preset, luego explorar clonado de persona real "
            "(mesh del año pasado).\n"
            "- Reacciones en tiempo real a las emociones del usuario.\n"
            "- Creacion de escenarios inmersivos con IA generativa.\n"
            "Estimacion: hasta mitad de ano para cerrar estas lineas de Avatares.\n\n"
            "6. Robotica — POCs y Casos Reales\n"
            "Navegacion autonoma: avance en simulacion (ya navega solo), pendiente en robot real.\n"
            "Problema: el equipo no se compromete con fechas para entregables/demos; respuestas "
            "esquivas. Propuesta de Mariano: arrancar la conversacion recordando que la demo "
            "estaba prometida para enero y ya llevan un mes de atraso — pedir fecha concreta.\n"
            "Caso de uso concreto para demo: ademas de exploracion, necesita inteligencia "
            "(ej. detectar algo). Para el cuadrupedo: POC en un cliente real (ronda de seguridad "
            "o inspeccion). Para el humanoide: segundo semestre (septiembre en adelante).\n"
            "Dificultad: la POC con cliente real no depende solo de I+D; requiere cierre "
            "comercial. Se define dejar en amarillo y hablar con Fede.\n\n"
            "7. Agentes — Lineas de Investigacion\n"
            "Lineas activas y nuevas:\n"
            "- Agente de datos no estructurados: caso de uso en Agora (usuarios suben videos "
            "de admision → procesamiento → enriquecimiento de perfil). Nueva exploracion: "
            "analisis de video (hasta ahora solo audio y texto).\n"
            "- Memoria cognitiva en sistema multiagentes: si no aplica en Agora, en otro producto. "
            "Lo actual (dar contexto a entrevistador) no cuenta como memoria cognitiva real.\n"
            "- Federal Agents: protocolo de comunicacion entre agentes para proteccion de datos "
            "sensibles. Explorable en Agora u otro producto.\n"
            "- Agente I+D (segundo cerebro IMASD): ya descrito arriba.\n\n"
            "8. Tesis de Marilyn — Sistema Multiagente de Video de Producto End-to-End\n"
            "Marilyn esta buildeando como tesis un sistema multiagente que crea un producto "
            "digital de principio a fin. Incluye:\n"
            "- Plugin de Figma conectado con la aplicacion: genera wireframes de pantallas "
            "basado en todo el contexto del MVP definido por agentes anteriores.\n"
            "- Mezcla sistema multiagente con soluciones externas (plugins de herramientas "
            "como Figma).\n"
            "- Posibilidad de armar un Coding Agent que podria resolver tambien el pedido de "
            "Fede (Cognify) de creacion de PPTs y presentaciones.\n"
            "Observation: Marilyn ve riesgo de que haya soluciones superadoras en el mercado "
            "(agentes autonomos que hacen todo con un prompt). La diferencia de su sistema: "
            "control granular paso a paso vs. prompt unico en herramientas como Stitch.\n\n"
            "Accionables:\n"
            "- [Mariano/Marilyn] Juntarse manana y el miercoles para preparar propuesta de OKRs "
            "antes de la reunion con Fede.\n"
            "- [Marilyn] Definir caso de uso concreto para demo de cuadrupedo con inteligencia.\n"
            "- [Mariano] Hablar con Fede sobre el POC de cuadrupedo con cliente real (dejar en amarillo).\n"
            "- [Marilyn] Avanzar OKRs de Avatares y Agentes.\n"
            "- [Marilyn] Mostrar avance de tesis (sistema multiagente end-to-end) cuando este listo."
        ),
    },
    {
        "source_id": "575870639",
        "date": "2026-02-07",
        "title": "Reunion comercial con Agueda Vieitez — Cliente de salud con necesidades de IA",
        "content": (
            "Meeting: Reunion comercial con Agueda Vieitez — Cliente de salud con necesidades de IA\n"
            "Date: 2026-02-07\n"
            "Participants: Mariano Ortega, Federico Valentino Lacoste, Agueda Vieitez\n\n"
            "Contexto: Reunion de acercamiento comercial. Agueda Vieitez es directora de empresa "
            "reseller de tecnologia (business partner de HP, Lenovo, IBM, Dell). Tiene un cliente "
            "del sector salud — institucion medica grande — con necesidades de IA y busca un "
            "socio tecnico que pueda desarrollar los servicios de IA requeridos.\n\n"
            "1. Perfil del Cliente\n"
            "Institucion de salud grande, cliente de Agueda desde hace 8 anos. Tienen un "
            "departamento de IA con multiples proyectos en curso. Toda la infraestructura es "
            "on-premise (no cloud) por gobernanza de datos: servidores con GPU en datacenter "
            "propio. Usan modelos open source o anonimizados (datos enmascarados). Ya tienen "
            "en curso un desarrollo de epicrisis con otro proveedor.\n\n"
            "2. Necesidades del Cliente\n"
            "El cliente hizo workshops de IA con toda la institucion (laboratorio, enfermeria, "
            "contaduria, administracion, auditoria, quirofano, triage, atencion). Cada area "
            "levanto la mano con necesidades propias. Areas de foco:\n"
            "- Epicrisis: automatizar el reporte de internacion para liquidacion con obras "
            "sociales/prepagas. Ya en desarrollo con otro proveedor.\n"
            "- Historia clinica inteligente: que un agente lea historias clinicas, identifique "
            "pacientes para programas preventivos (ej. fumadores → programa cancer), "
            "haga acciones proactivas. 20.000 pacientes aprox.\n"
            "- Otros casos: laboratorio, atencion al paciente, etc.\n"
            "- Asistencia al paciente (menos desarrollada por ahora): que el paciente "
            "pueda consultar sus estudios directamente con la app de la institucion "
            "en lugar de ChatGPT.\n\n"
            "3. Contexto Tecnico Flock\n"
            "Federico menciona que Flock tiene experiencia en sistemas multiagentes en "
            "multiples verticales. Ya tienen desarrollos con LLMs on-premise (productivos). "
            "Mariano aclara que habria que hacer un relevamiento para entender el framework "
            "que el cliente usa y si Flock tiene experiencia en el mismo.\n\n"
            "4. Caso de Exito de Flock — Emergencias Medicas\n"
            "Federico presenta caso de exito: empresa de emergencias medicas, call center. "
            "Procesamiento de llamadas con IA para detectar:\n"
            "- Parte comercial: quienes usan mejores estrategias, oportunidades de mejora.\n"
            "- Parte emergencias: como el operador atendio al paciente, si hizo todas las "
            "preguntas necesarias, propuesta de mejoras mediante tablero.\n"
            "Agueda lo valora como referencia para presentar al cliente.\n\n"
            "5. Riesgos y Recomendaciones Estrategicas\n"
            "Federico advierte: si el cliente trabaja con muchos proveedores distintos, "
            "en el futuro tendra dificultades para alinear modelos y versiones. "
            "Recomendacion: entender la estrategia tecnologica del cliente a mediano plazo "
            "para evitar duplicaciones y complejidades de mantenimiento.\n"
            "Agueda coincide: la conversacion con el cliente debe ser abierta, sin asumir "
            "cosas a partir de la intermediacion de Agueda. El cliente puede haber cambiado "
            "el enfoque desde la ultima reunion con Agueda.\n\n"
            "6. Totem / Agente Conversacional de Flock\n"
            "Federico intenta mostrar un demo del totem de Flock (agente conversacional en "
            "kiosco) pero no estaba levantado en ese momento. Tambien mencionan el totem "
            "de CEMIC como otro caso. Se comprometen a pasar un link para que Agueda lo vea.\n\n"
            "Accionables:\n"
            "- [Federico] Enviar a Agueda el brochure del caso de emergencias medicas (Life ID).\n"
            "- [Federico/Mariano] Pasar link del totem demo a Agueda.\n"
            "- [Agueda] El lunes presenta a Flock al cliente, agenda una primera reunion de "
            "relevamiento.\n"
            "- [Flock] Para la reunion con el cliente: escuchar, hacer preguntas abiertas, "
            "no asumir nada basado en la intermediacion de Agueda."
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
