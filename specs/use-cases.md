# Use Cases — secondBrain AI Chief of Staff

Ejemplos de consultas y flujos de trabajo para sacar el máximo provecho del sistema.

---

## Búsqueda en el conocimiento base

El agente busca en emails, Slack, Teams, reuniones de Fathom y páginas de Notion.

```
¿Qué se habló sobre el presupuesto del proyecto X?
Resume los últimos mensajes de Slack donde se menciona [cliente/colega]
¿Alguien me mandó algo sobre la integración con [sistema]?
¿Qué decidimos en la última reunión de [proyecto]?
```

Podés filtrar por plataforma siendo más específico:

```
¿Qué me dijo [nombre] por Slack esta semana?
¿Hay algún email sobre [tema]?
¿Qué se habló en las reuniones de Fathom sobre [cliente]?
```

---

## Gestión de compromisos y tareas

El agente revisa los compromisos detectados automáticamente durante la ingesta.

```
¿Qué tengo pendiente para esta semana?
¿Hay algo atrasado que debería haber entregado?
¿A quién le debo respuesta?
¿Qué le prometí a [colega/cliente] la semana pasada?
¿Qué compromisos tengo con [cliente] sin resolver?
```

---

## Agenda y preparación de reuniones

```
¿Qué reuniones tengo hoy?
Prepárame para la reunión de las 3pm con [nombre]
¿Con quién me reúno hoy y de qué se habló con ellos últimamente?
¿Qué temas abiertos tengo con los asistentes de mi próxima reunión?
```

---

## Memoria experiencial — enseñarle al agente

El agente puede guardar learnings sobre clientes, proyectos y patrones usando la herramienta
`save_learning`. Cuanto más le enseñás, más contexto tiene en futuras conversaciones.

**Guardar preferencias de clientes:**
```
Anotá que [Cliente X] prefiere recibir los reportes los viernes antes del mediodía
Recordá que [Cliente Y] no usa Slack, solo email
[Nombre] es el real decision maker en [Empresa], no [otro nombre]
[Cliente Z] trabaja con sprints de 2 semanas y presenta los jueves
```

**Guardar contexto de proyectos:**
```
Recordá que el proyecto [X] tiene fecha límite el 30 de octubre
El stack técnico de [Empresa] es React + Node, no tienen Python
[Proyecto] está en pausa hasta que [condición]
```

**Consultar lo que ya aprendió:**
```
¿Qué sabés de [cliente]?
¿Qué recordás sobre el proyecto [X]?
¿Cuáles son las preferencias de trabajo de [nombre]?
¿Qué contexto tenés sobre [empresa]?
```

---

## Conversación multi-turn

Dentro de la misma sesión del CLI, el agente recuerda el contexto de los turnos anteriores.
No hace falta repetir el contexto en cada pregunta.

```
# Turno 1
¿Qué temas están abiertos con [cliente]?

# Turno 2 — sin repetir el nombre del cliente
¿Y cuándo fue la última vez que les mandé algo?

# Turno 3
Redactame un follow-up basado en eso

# Turno 4
Hacelo más corto y en tono informal
```

Las sesiones expiran después de 24 horas de inactividad. Al abrir el CLI al día siguiente
se inicia una sesión nueva.

---

## Briefing situacional

```
Dame un resumen de todo lo que pasó esta semana
¿Cuáles son los temas más urgentes que tengo ahora mismo?
¿Qué no debería olvidar antes del fin de semana?
Prepárame para la semana que viene
¿Hay algo crítico que se me esté escapando?
```

---

## Slash commands disponibles

| Comando | Descripción |
|---|---|
| `/briefing` | Briefing diario completo (agenda + compromisos + alertas) |
| `/sync slack` | Sincroniza Slack ahora |
| `/sync outlook` | Sincroniza Outlook (emails + calendario) |
| `/sync fathom` | Sincroniza transcripts de Fathom |
| `/commitments` | Lista compromisos pendientes |
| `/notion` | Publica el briefing en Notion |
| `/digest` | Genera el digest semanal |
| `/prep` | Preparación para reuniones del día |
| `/server` | Estado del servidor local |

---

## Tips para mejores resultados

1. **Sincronizá frecuente** — `/sync slack` antes de preguntar algo reciente garantiza datos frescos.
2. **Enseñale contexto** — cada vez que aprendés algo nuevo sobre un cliente, decíselo. Se acumula entre sesiones.
3. **Sé específico con nombres** — el agente busca semánticamente; mencionar el nombre del cliente o proyecto mejora los resultados.
4. **Usá la sesión completa** — no cierres y vuelvas a abrir el CLI en la misma conversación; el historial se usa para respuestas más coherentes.
5. **Preguntás en español, responde en español** — el agente detecta el idioma automáticamente.
