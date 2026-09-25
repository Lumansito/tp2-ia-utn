# Próximos pasos

Qué queda para cerrar el TP2, en orden sugerido. Última actualización: 25/09/2026.

## 1. Validar en vivo el flujo completo del agente (prioridad alta)

Hasta ahora solo se probó en vivo (Postgres real + LLM real) una pregunta del **Modo Documentación**
(RAG de esquema), que respondió bien. Falta probar, con la base de demo de Docker ya levantada:

- [ ] Una consulta de **lectura** en Modo Agente (por ejemplo "¿cuáles son los 5 productos más caros?")
      y confirmar que el SQL generado es correcto y que el guardrail no bloquea nada que debería pasar.
- [ ] El flujo completo de **escritura con aprobación (HITL)**: pedirle al agente un `UPDATE` o
      `INSERT`, confirmar que queda pendiente en el banner de aprobaciones, aprobarlo, y verificar que
      se ejecutó contra la base y quedó en el log de auditoría (pestaña Auditoría).
- [ ] Un caso de **auto-corrección**: una pregunta donde el primer SQL que arme el agente falle (por
      ejemplo un nombre de columna ambiguo) y confirmar que se corrige solo con el error que le
      devuelve `run_select`.
- [ ] Confirmar que `EMBEDDING_MODEL` (`models/gemini-embedding-001`) sigue vigente — no dio error
      hasta ahora, pero no se confirmó explícitamente como sí se hizo con `LLM_MODEL`.

## 2. Fase 8: notebook de entrega

Pendiente a propósito hasta que la app esté cerrada y validada (punto 1). Cuando se arranque:

- [ ] Rehacer `notebooks/demo.ipynb` desde cero (el actual corresponde a una versión vieja del
      proyecto).
- [ ] Debe agregar la raíz del proyecto a `sys.path`, leer el `.env`, y mostrar en orden: introspección
      → documentos generados → indexado en Chroma → Modo Documentación → Modo Agente con sus pasos
      (timeline) → guardrails bloqueando un caso prohibido → flujo HITL completo → log de auditoría.
- [ ] Incluir casos de prueba con sus resultados reales.
- [ ] Entregarlo **ejecutado, con las salidas guardadas** (no solo el código).

## 3. Presentación oral

- [ ] Armar la presentación: caso de negocio, arquitectura, decisiones de diseño, dificultades
      encontradas (ya documentadas en [`01-documentacion-actual.md`, sección 9](01-documentacion-actual.md#9-dificultades-encontradas-y-cómo-se-resolvieron))
      y resultados.
- [ ] Preparar un plan B para la demo en vivo (capturas de pantalla o un video corto) por si falla la
      red o la cuota del LLM durante la defensa.
- [ ] Repasar el **TP1** (clasificación de alumnos con redes neuronales): en la defensa hacen 1 o 2
      preguntas sobre eso también.

## 4. Coordinación con el equipo

- [ ] Confirmar que los commits locales de esta sesión (base de demo en Docker, puerto configurable,
      fix de `uvloop`, modelo de Gemini actualizado, dependencia de Node) estén realmente en
      `origin/main` — el `git fetch` falló por SSH en el entorno donde se hicieron estos commits, así
      que conviene verificarlo (o pushearlos) desde una máquina con acceso normal al repositorio.
- [ ] Avisarle al resto del equipo (Tomás y compañía) que hay commits nuevos para traer con
      `git pull`, en particular la base de demo de Docker y el fix de `requirements.txt` en Windows.

## 5. Detalles menores (no bloquean la entrega)

- [ ] El explorador de tablas de la pestaña Esquema usa el motor de conexión principal para el
      `SELECT ... LIMIT`, no el de solo lectura (`DATABASE_URL_READONLY`, si está configurado). No es
      grave porque igual pasa por SQLAlchemy con una consulta fija, pero se puede prolijar.
- [ ] Warning de Streamlit por `use_container_width` (deprecado, se reemplaza por `width=...`). Es
      cosmético, no rompe nada.
- [ ] Hay varios contenedores de Docker de otros proyectos corriendo hace meses en la máquina de
      desarrollo (`documentos-kretz-db`, `manuales_strapi`, `manuales_db`, `mi-proyecto-n8n`). No
      afecta a este proyecto, pero vale la pena pararlos si se necesita liberar recursos.
