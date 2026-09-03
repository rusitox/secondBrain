"""Ingest Fathom transcripts batch 9 (recordings 699308254, 662356235)."""
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
        "source_id": "699308254",
        "date": "2026-06-23",
        "title": "Capacitacion Interna Oil & Gas — Cadena de Valor, Vaca Muerta y Oportunidades Tecnologicas",
        "content": (
            "Meeting: Capacitacion interna sobre la industria de Oil & Gas — Cadena de valor, "
            "tecnologias de extraccion y oportunidades comerciales en Vaca Muerta\n"
            "Date: 2026-06-23\n"
            "Participants: Sebastian Loizaga, Paula Vejrup, Guillermo Schettino, Marilyn Botheatoz, "
            "Fatima Bottero, Mariano Ortega\n\n"
            "Contexto: Primera de dos sesiones de capacitacion interna organizadas por Flock para el "
            "equipo comercial y tecnico. Objetivo: introducir a todos los miembros en conceptos "
            "fundamentales de la industria de petroleo y gas, con foco en Argentina y en la formacion "
            "Vaca Muerta. Proposito estrategico: preparar al equipo para generar un offering de "
            "soluciones tecnologicas para clientes del sector Oil & Gas.\n\n"
            "1. Cadena de valor del sector (Upstream, Midstream, Downstream)\n"
            "- Upstream: extraccion desde los pozos. Sismicidad 3D, perforacion, terminacion "
            "(fracking) y produccion. Mayor porcentaje del presupuesto de la industria (~70%).\n"
            "- Midstream: transporte del crudo y gas desde yacimientos hacia refinerias o puntos de "
            "exportacion. Principales empresas: TGS (gas) y OILVALL (petroleo).\n"
            "- Downstream: refinacion y distribucion de combustibles y derivados. Incluye licuefaccion "
            "del gas para exportacion (GNL).\n\n"
            "2. Convencional vs. No convencional (Vaca Muerta)\n"
            "Diferencia fundamental: yacimientos convencionales (roca porosa y permeable, el hidrocarburo "
            "fluye naturalmente) vs. no convencionales como Vaca Muerta (roca tipo marmol, no permeable, "
            "requiere fractura hidraulica).\n"
            "- Argentina paso de predominantemente convencional a 70/30 en favor del no convencional.\n"
            "- Vaca Muerta: segunda reserva de gas mas grande del mundo, cuarta de petroleo.\n"
            "- Un pozo no convencional cuesta entre 13 y 15 millones de dolares (perforacion + terminacion).\n"
            "- Produccion inicial: 800-1.500 barriles/dia generando 80.000-150.000 USD/dia.\n\n"
            "3. Proceso de fracking (fractura hidraulica)\n"
            "- Perforacion vertical de ~3.000 metros, luego rama horizontal de 3.500-4.000 metros.\n"
            "- Punzado con cargas explosivas controladas para crear canales en la roca.\n"
            "- Inyeccion de agua con arena a presiones de 10.000-12.000 PSI (~200 veces la presion "
            "domiciliaria).\n"
            "- Entre 40 y 60 etapas de fractura por pozo. Cada etapa usa 200-300 toneladas de arena "
            "y 1.500 m3 de agua.\n"
            "- Total de agua por pozo: ~25 piletas olimpicas. Arena total: 10.000-15.000 toneladas "
            "(500-700 camiones).\n"
            "- Costo por etapa: ~150.000 USD. Costo total de fracturas de un pozo: 7-8 millones USD.\n\n"
            "4. Logistica como oportunidad de negocio\n"
            "La logistica es una de las principales oportunidades para soluciones tecnologicas de Flock:\n"
            "- Vaca Muerta a 200-400 km de Neuquen capital por rutas de alto trafico.\n"
            "- Camiones de arena (500-700 por pozo) desde Entre Rios o Chubut.\n"
            "- Tiempos muertos (NPT — Non-Productive Time) extremadamente costosos.\n"
            "- Muchas empresas transportan personal en avionetas; accidentes de transito frecuentes.\n\n"
            "5. Geografía y empresas clave del sector\n"
            "Cuencas productivas: Neuquina (Vaca Muerta), Noroeste, Cuyana, Golfo San Jorge, Austral.\n"
            "Operadoras principales: YPF, Panamerican Energy (PAE), Vista, Pluspetrol, Shell, Chevron, "
            "Tecpetrol, Pampa Energia.\n"
            "Empresas de servicios pequenas: Tango, Benoil, Aconcagua, Toccoa, Ventia, Quintana.\n"
            "La mayoria de las empresas grandes tienen proyectos RIGI "
            "(Regimen de Incentivo a las Grandes Inversiones) a 5-10 anos.\n\n"
            "6. Sistema de concesiones y superficiarios\n"
            "Las concesiones son licitadas por la provincia de Neuquen por plazos de 10-15 anos. "
            "El subsuelo pertenece al Estado provincial, que cobra 12-15% de regalias por barril. "
            "Los superficiarios reciben compensaciones fijas por uso de caminos, instalaciones y pozos.\n\n"
            "7. Tecnologias de medicion y control de produccion\n"
            "- Separadores trifasicos (petroleo, gas, agua) para medir produccion por pozo.\n"
            "- Nuevas tecnologias: medidores multifasicos y algoritmos de prediccion de produccion "
            "('controles sinteticos') que reducen la frecuencia de medicion fisica.\n"
            "- Todo pozo tiene sensores de presion y temperatura transmitidos en tiempo real a salas "
            "de control locales y remotas (Buenos Aires / Neuquen).\n\n"
            "8. Sistemas de extraccion artificial\n"
            "Cuando cae la presion natural del pozo (1-2 anos en Vaca Muerta):\n"
            "- Gas lift: inyeccion de gas comprimido para aliviar la columna del pozo (el mas usado en "
            "Vaca Muerta actualmente).\n"
            "- Bombeo mecanico: las 'ciguenas' visibles en la ruta, mayormente en convencional.\n"
            "- Electrosumergibles: bombas electricas instaladas en el fondo del pozo.\n\n"
            "9. Sala de control de YPF y oportunidad con Aveva/PAI\n"
            "Sala de control de YPF en Neuquen: 50 personas, sistema PAI de Aveva para visualizacion "
            "en tiempo real. Se discutio la posibilidad de un partnership con Aveva para representar "
            "algunas de sus soluciones industriales.\n\n"
            "10. Caso Tecpetrol — Seguimiento de obra\n"
            "Tecpetrol como proyecto concreto de Flock: seguimiento de obra de una planta industrial "
            "en construccion mediante analitica de video (Computer Vision). Se exploro disponibilidad "
            "de camaras en obra y posibilidad de agregar analitica.\n\n"
            "Decisiones:\n"
            "- Continuar con segunda sesion focalizada en problematicas comunes de clientes del sector.\n"
            "- Logistica de camiones y materiales identificada como principal oportunidad de offering.\n"
            "- Mantener el interes en TGS como cliente estrategico.\n"
            "- Explorar partnership con Aveva para representar PAI en el mercado.\n\n"
            "Accionables:\n"
            "- Preparar segunda sesion sobre problematicas comerciales detectadas (semana siguiente).\n"
            "- Avanzar con conversaciones pendientes con YPF.\n"
            "- Seguimiento con OILVALL (sin respuesta a correos enviados).\n"
            "- Explorar iniciativa de telemetria del Hub Norte (Rincon de los Sauces).\n"
            "- Evaluar camaras en obra de Tecpetrol para project de object tracking."
        ),
    },
    {
        "source_id": "662356235",
        "date": "2026-05-14",
        "title": "Framework I+D Flock — Iniciativas, Modelo de Subsidio de POCs y Prep Reunion Socios",
        "content": (
            "Meeting: Revision del framework de I+D de Flock — Mapeo de iniciativas, modelo de subsidio "
            "de POCs y preparacion para presentacion con socios y equipo comercial\n"
            "Date: 2026-05-14\n"
            "Participants: Mariano Ortega, Naiara Acosta Najmanovich, Federico Valentino Lacoste, "
            "Santiago Samra\n\n"
            "Contexto: Reunion interna del equipo de I+D (IMAXD) de Flock para revisar y validar el "
            "framework de trabajo de I+D, mapear el estado de iniciativas tecnologicas en curso, debatir "
            "el modelo de subsidio para POCs con clientes, y preparar la agenda para dos reuniones "
            "proximas: equipo comercial de Industrias 4.0 (Seba y Pau, ese jueves) y socios "
            "(semana siguiente).\n\n"
            "Temas preliminares:\n"
            "- Gestion de consumo de tokens de LLMs: un miembro del equipo (Fatih) habia excedido su "
            "cuota. Santiago: no aumentar cuotas prematuramente, que el equipo 'choque con la pared' "
            "y aprenda a usar los modelos eficientemente antes de escalar. Fede propuso evaluar "
            "DeepSeek (R1/R2, ~75% menos costo que GPT-4) como alternativa centralizada para usos "
            "no relacionados con desarrollo.\n"
            "- Informe de seguridad externo sobre Praia: un conocido de Swiss Medical realizo un "
            "analisis de seguridad de Praia (prompt injection, WAF, autenticacion doble factor, "
            "infraestructura). Se acordó revisar el informe para identificar vulnerabilidades relevantes.\n\n"
            "Framework de I+D — Estructura por etapas:\n"
            "- Etapa 0 (Backlog/Hipotesis): Ideas no iniciadas. El plan anual de la vertical "
            "alimenta esta etapa.\n"
            "- Etapa 1 (Problema/Hipotesis): Definicion formal del problema.\n"
            "- Etapa 2 (Investigacion): Iniciativas en curso de research.\n"
            "- Etapa 3 (Implementacion): Desarrollo de la solucion con posible participacion de "
            "cliente real.\n"
            "- Etapa 4 (Validacion): Validacion interna y/o externa con cliente real.\n"
            "- Etapa 5 (Insight y transferencia): Conclusion, decision go/no-go para avanzar a venta.\n"
            "- Primera venta: Operacion comercial real con pago del cliente.\n"
            "- Siguientes ventas: Escala del negocio.\n\n"
            "Debate clave: validacion interna vs. validacion con cliente real\n"
            "Fede: para pasar de implementacion a primera venta, es necesaria una validacion con "
            "cliente real (no solo POC interna). Mariano: en Robotica hay plan de dos instancias: "
            "primero interna (navegacion autonoma en oficina), luego externa (campo real, posiblemente "
            "Aeropuertos). El gate de go/no-go hacia primera venta requiere validacion externa. "
            "Excepcion: cuando la salida es un paper o conocimiento (ej. benchmark de plataformas de "
            "Computer Vision), la iniciativa puede cerrarse en Insight sin validacion externa.\n\n"
            "Estado de iniciativas tecnologicas:\n"
            "- Benchmark de plataformas de Computer Vision: Investigacion (2->3). Paper en confeccion "
            "con plataformas comerciales y open source; informara el go/no-go de Vision 360.\n"
            "- Fugas y derrames (Oil & Gas): Investigacion/Implementacion. Avanzado; reunion reciente "
            "sugiere pasar a etapa 3 con cliente Proden.\n"
            "- Rediseno de Agora: Investigacion (etapa 2). Rediseno UX/UI basado en entrevistas con "
            "Talent; pendiente go/no-go para implementar.\n"
            "- Navegacion autonoma simulada en entornos virtuales: Validacion (3->4). Pausado por "
            "baja por paternidad de Dennis; Mati avanza con simulacion fisica.\n"
            "- Cuadrupedo fisico (Unitree) con Computer Vision: Validacion (3->4). Navegacion "
            "autonoma en oficina + modelo de deteccion; prevista para mayo.\n"
            "- Generacion de datos sinteticos y auto-etiquetado: Final de implementacion. "
            "Prueba final en fugas y derrames.\n"
            "- Presencia humana en Agora (deteccion de identidades sinteticas): Terminara en paper.\n"
            "- TrainLink: Validacion -> POC con Tecpetrol. Si se aprueba propuesta Tecpetrol -> "
            "etapa 4 con cliente real.\n"
            "- Vision 360: POC pausada. Go/no-go depende del benchmark de plataformas de CV.\n"
            "- Avatar propio (Metahuman): Etapa 3->4. Refinando nivel de exigencia.\n"
            "- Agora Multiagente: Validacion activa. Las chicas de Talent ya lo estan usando.\n"
            "- Praia: Etapa 6 (ya paso el proceso). Primera venta: Aeropuertos. Segunda: Toki. "
            "Falta consolidar mas ventas para pasar al siguiente umbral.\n\n"
            "Debate sobre modelo de subsidio de POCs:\n"
            "Santiago: la primera venta deberia pagarse. Propuso cobrar un monto simbolico al inicio "
            "(ej. 5.000 USD) y descontarlo del MVP si la POC es exitosa. El dinero valida el "
            "compromiso real del cliente.\n"
            "Fede: hay casos donde conviene subsidiar si el cliente tiene alto potencial (ej. una "
            "petrolera con posibilidad de replicacion masiva). Propuso que la POC sea gratuita pero "
            "con compromiso escrito de contratar el MVP si se cumplen criterios de exito definidos "
            "previamente.\n"
            "Naiara: distinguio entre subsidio en Implementacion (necesario porque IMAXD trabaja para "
            "un cliente sin retorno) y subsidio en primera venta (donde ya deberia haber pago). "
            "Sugirio definir un presupuesto anual de POCs para evitar que el subsidio sea ilimitado.\n\n"
            "Conclusiones sobre el modelo de subsidio:\n"
            "- En implementacion: se puede subsidiar total o parcialmente. Cliente puede pagar monto "
            "simbolico para demostrar compromiso.\n"
            "- En primera venta: el cliente debe pagar el precio real (sin subsidio, o con subsidio "
            "explicito y justificado ante socios).\n"
            "- Se establecera un presupuesto anual de POCs para controlar cuantas se pueden ofrecer "
            "subsidiadas por ano.\n"
            "- El subsidio requiere aprobacion: no puede decidirse unilateralmente por el equipo "
            "comercial.\n\n"
            "Analisis de mercado para la primera venta:\n"
            "Fede: necesario hacer benchmark de precios de mercado antes de fijar el valor de venta.\n"
            "Tres patas: (1) pata tecnica (a cargo de IMAXD), (2) pata de precios/comercializacion "
            "(a cargo de comercial), (3) pata de negocio: P&L del cliente para validar si el precio "
            "tiene sentido. 'Me da igual que este vendiendo solucion o SaaS, el cliente tiene que ver "
            "que invertir en esto le tiene sentido.'\n\n"
            "Preparacion de proximas reuniones:\n"
            "Reunion con equipo de Industrias 4.0 (Seba y Pau) — ese jueves:\n"
            "- Presentar el framework y hacerlos sentir parte del proceso.\n"
            "- Mostrar en que etapas participan (definicion de problema, acompanamiento comercial, "
            "traduccion al lenguaje del negocio).\n"
            "- Evitar que perciban el framework como algo que los desplaza.\n"
            "- Discutir el caso de la POC con Proden (fugas y derrames) como ejemplo.\n\n"
            "Reunion con socios — semana siguiente:\n"
            "- Presentacion ejecutiva del framework (pocas slides).\n"
            "- Usar ejemplos conocidos (Praia, Aeropuertos, TrainLink).\n"
            "- Enfocarse en las preguntas de los socios: donde ponen la plata, como deciden, que retorno.\n"
            "- Respuesta al retorno: si se consolidan cuatro ventas de una tecnologia, se genera un "
            "negocio nuevo que no existia antes.\n\n"
            "Decisiones:\n"
            "- La validacion externa con cliente real es requisito para pasar a primera venta "
            "(con excepciones para iniciativas que terminan en paper).\n"
            "- Subsidio de POCs se permite en etapa de implementacion con monto simbolico; en primera "
            "venta el cliente debe pagar.\n"
            "- Se creara un presupuesto anual de POCs.\n"
            "- Analisis de mercado obligatorio antes de fijar precio de venta.\n"
            "- El plan anual de la vertical se incorporara como Etapa 0 (backlog) del framework.\n"
            "- Se agregaran fechas estimadas de finalizacion e indicadores de esfuerzo/complejidad "
            "a cada iniciativa.\n\n"
            "Accionables:\n"
            "- Naiara: completar fichas de iniciativas con fechas y nivel de esfuerzo; agregar Praia "
            "al mapa del framework; refinar contenido de slide de primera venta.\n"
            "- Mariano: completar mapeo del plan anual en el backlog; refinar las preguntas de las "
            "fichas de cada iniciativa.\n"
            "- Fede: preparar discurso para reunion del jueves con Seba y Pau (eje en que input "
            "necesitamos de Industrias y donde participan ellos).\n"
            "- Todo el equipo: definir reglas formales del subsidio (criterios, presupuesto, "
            "aprobacion) para incluir en el framework antes de presentar a socios."
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
