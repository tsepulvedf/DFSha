# DFSha — Matriz de requisitos y trazabilidad

Actualizado 2026-09-08 · Etapas 1–2 · Fuente principal: [PDF local de siete páginas](enunciado/SI3007-262-proyecto1-dfs.docx.pdf). Las páginas indicadas son las impresas, coincidentes con las páginas físicas. Extracción/rúbrica originales conservadas.

**Estado global E3:** RF1/RF2 implementados y comprobados; 87 pruebas aprobadas y
roundtrip 1 GiB con tres clientes en la [ejecución final](evidencias/etapa3/20260909T195446Z/resultado.json).
RF3 completo, HA y seguridad integral siguen PENDIENTES. La distribución E4 se
implementa y verifica según la tabla adicional al final y [evidencias E4](evidencias/etapa4/README.md).
Tablas iniciales conservan fuentes y criterios finales; [evidencias H1](evidencias/etapa3/README.md)
distingue pruebas reales y límites. La [correspondencia E2](#etapa2) es histórica.

RF/RNF conservan los identificadores del PDF. OBJ, DEF, OP, COM, API, INF, ENT, H y EV son identificadores locales para obligaciones sin código. USR registra reglas explícitas del usuario. DIS registra metas del equipo. Los criterios observables son formalización operativa del equipo; no se presentan como nuevos subcriterios de calificación del docente.

E1–E11 son etapas de trabajo de la guía, no semanas. H1=semana 8, H2=semana 10, H3=semana 12; final=semana 13. El plan completo está en [estado, plan](estado.md#plan).

<a id="rf"></a>
## 1. Objetivo y requisitos funcionales

| ID | Descripción y fuente PDF | Interpretación operativa | Criterio observable de aceptación | Etapa prevista | Diseño / implementación prevista | Prueba y evidencia por producir |
| --- | --- | --- | --- | --- | --- | --- |
| OBJ-01 | Objetivo general: archivos grandes distribuidos; tanto escritura como lectura entre varios nodos. P. 1, Objetivo General. | El mismo archivo de varios bloques emplea varios DN como destino y fuente. | Archivo ≥64 MiB escrito y leído mediante ≥2 DN; bytes útiles por nodo y hash final correcto; CN no transporta contenido en versión distribuida. | E1 diseño; E4/H2, E9–10. | [A5](arquitectura.md#a5); SDK/planificador/BlockService. | T-DIST, T-CLOUD: trazas y conteos por nodo. |
| RF1 | Gestión: ls, cd, mkdir, rmdir, rm, etc. P. 1, Cliente DFSha. | Árbol remoto, cwd por sesión, errores, permisos; extras definidos sin inventar significado de «etc.». | Dos sesiones con cwd independientes; creación/listado/borrado; rmdir no vacío falla; raíz protegida; persistencia al reiniciar. | E3/H1 completo; E4/8/10 regresión. | [S5](especificacion.md#s5); cliente y NamespaceService. | T-RF1: comandos, respuestas, árbol y reinicio. |
| RF2 | Transferencia send() y receive(). P. 1, Cliente DFSha. | Archivos completos; put/get son alias DIS. Commit único de upload y snapshot de download. | Vacío/binarios/grandes con hash/tamaño iguales; abortar no deja versión parcial ni destruye la anterior; sin volumen compartido. | E3/H1 completo; E4/6/10 evolución. | [S5](especificacion.md#s5), [A6](arquitectura.md#a6); SDK/TransferService. | T-RF2, T-ATOMIC: hashes, interrupciones, estado. |
| RF3 | Acceso open(), close(), read(), write(), lock(), etc.; distinguir transferencia/acceso. P. 1, Cliente DFSha. | Acceso parcial por offset, snapshots, modos, locks y commits definidos; obligatorio final (también USR). | Patch que cruza bloque preserva bytes externos; EOF/crecimiento/modos; close no confirma; lectores antiguos/nuevos; conflicto y lock vencido; dos escritores compatibles conservan cambios. | E1 semántica; E2 contratos; E5 implementación; E7–8/H3 y E10 pruebas. | [S6](especificacion.md#s6), [A7](arquitectura.md#a7); SDK/HandleService/Coordinator/PatchBlock. | T-RF3, T-CONC, T-FENCE, T-DELETE: bytes esperados, versiones, línea temporal de locks. |

<a id="rnf"></a>
## 2. Requisitos no funcionales

| ID | Descripción y fuente PDF | Interpretación operativa | Criterio observable de aceptación | Etapa prevista | Diseño / implementación prevista | Prueba y evidencia por producir |
| --- | --- | --- | --- | --- | --- | --- |
| RNF1 | Escalabilidad en usuarios, número de archivos y tamaño, etc. P. 1, Servicio DFSha (inicio de lista que sigue en p. 2). | Cubrir las tres dimensiones; metas DIS según recursos, sin prometer crecimiento ilimitado. | Ejecutar niveles de clientes, cantidad y tamaño de S9, registrar niveles no ejecutados; memoria acotada, paginación y análisis al agregar DN. | E1 metas; E4/7/9/10. | [S9](especificacion.md#s9), [A3/A5](arquitectura.md#a3); paginación/streaming/planificador. | T-SCALE: CSV/JSON, recursos, RSS, latencias y errores. |
| RNF2 | Alta disponibilidad y servicio redundante para evitar caídas/pérdida de archivos. P. 2. | Incluir datos, control, metadatos, claves y entrada; modelo de un fallo independiente, sin afirmar disponibilidad ilimitada. | Perder un DN, CN, miembro etcd y finalmente una VM conserva servicio previsto y datos confirmados; recuperación y degradación documentadas. | E6 datos; E7 control; E8/H3; E9–10 hosts. | [A8–10](arquitectura.md#a8); replicador, etcd, SDK failover y custodia. | T-REPL, T-HA, T-QUORUM, T-KEYS, T-CLOUD. |
| RNF3 | Resolver consistencia de datos asociada a redundancia. P. 2. | Versiones inmutables, publicación atómica, snapshots explícitos y fencing; no equivalencia W=consistencia. | Sin parciales visibles, versiones mezcladas, updates perdidos ni publicación obsoleta; resultado idempotente tras pérdida de ACK; quórum perdido sin commits. | E3 atomicidad; E5–7; E8/H3, E10. | [S6](especificacion.md#s6), [A6–8](arquitectura.md#a6); Txn/CAS/ledger/Coordinator. | T-ATOMIC, T-IDEM, T-CONC, T-FENCE, T-DELETE, T-QUORUM. |
| RNF4 | Archivos distribuidos entre nodos y cada archivo distribuido entre varios nodos. P. 2. | Particionar por bloques; excepción operativa vacíos/pequeños registrada en Q02. | Manifiesto de un archivo grande con bloques distintos y ubicaciones en varios DN; fronteras B−1/B/B+1 y último bloque parcial correctas. | E4/H2; E6/9/10. | [A5](arquitectura.md#a5); BlockStore/PlacementService. | T-DIST: manifiesto y registros de bytes; T-RF2 fronteras. |
| RNF5 | Rendimiento y concurrencia en archivos y datos dentro de un archivo. P. 2. | Lectores y escritores compatibles simultáneos; medir coste, no suponer speedup. | Dos writers en bloques distintos conservan ambos deltas; solapados tienen conflicto controlado; medir 1/5/10 clientes y paralelismo bajo igual seguridad/durabilidad. | E4/5; E8/H3; E10. | [S6/S9](especificacion.md#s6), [A5/A7](arquitectura.md#a5); locks por bloque/colas. | T-CONC, T-SCALE: bytes, tiempos, recursos y throughput útil. |
| RNF6 | Cifrado en comunicaciones/almacenamiento, control de acceso por usuario/grupo y seguridad entre nodos. P. 2, incluidos dos subpuntos. | TLS/mTLS, Argon2id, ACL, autorización DN y custodia/rotación; Q03 sobre 2FA/API Keys. | Usuario/grupo correcto pasa; ajeno/nodo falso/token alterado fracasa; validar TLS, cifrado de datos/metadatos/backups y lectura al reemplazar nodo con claves. | E2–3 base; E4–7 integración; E8/H3 completo; E9–10. | [S7](especificacion.md#s7), [A9](arquitectura.md#a9); Authorizer/identidad/crypto. | T-SEC y T-KEYS: pruebas positivas/negativas, configuración y restauración sin secretos. |
| RNF7 | Transparencia de acceso/localización, hasta mecanismos dinámicos; nunca estáticos. P. 2. | Rutas lógicas y SDK; bootstrap de control permitido, ubicaciones de bloques resueltas en ejecución. | Incorporar/fallar/mover nodos sin editar cliente ni ruta lógica; nuevos endpoints alcanzables y réplica elegida conservan snapshot. | E3 CLI; E4/7/9/10. | [A3–5](arquitectura.md#a3); ResolveBlocks/SDK. | T-DISCOVERY, T-HA: configuración antes/después y trazas. |
| RNF8 | Puede aclarar/modificar requisitos o recibir nuevos; tres entradas «…». P. 2. | Sin adiciones concretas en esta versión. Mantener registro de aclaraciones, no inferirlas. | Lectura de p. 2 y registro fechado; futuras aclaraciones con autor/fuente/impacto; no asignar una función inventada. | E1 EJECUTADO; revisar en cada etapa/E11. | [Decisiones, aclaraciones](decisiones.md#aclaraciones). Sin código requerido por los puntos suspensivos. | Evidencia actual: lectura-pdf.txt y registro; futuras actas si existen. |

<a id="transversales"></a>
## 3. Servicio, arquitectura, comunicaciones e infraestructura

| ID | Descripción y fuente PDF | Interpretación operativa | Criterio observable de aceptación | Etapa prevista | Diseño / implementación prevista | Prueba y evidencia por producir |
| --- | --- | --- | --- | --- | --- | --- |
| DEF-01 | Cada grupo realiza definición formal de servicio y RF/RNF. P. 4, Desarrollo §1. | Formalizar objetivos, actores, alcance, semántica, fallos y consultas. | Documento con esos elementos y matriz que cita todas las obligaciones; revisión del equipo registrada. | E1/semana 7; E11 actualizar al sistema real. | [Especificación](especificacion.md). Sin código en E1. | Documentos actuales; acta de revisión del equipo pendiente. |
| OP-01 | Opción 1: C/S con composición/distribución S2S, sistema autónomo de una organización, acceso C/S abierto y S/S autónomo; red privada real/virtual. P. 2; arquitectura según opción asignada p. 4 §2. | Elección USR opción 1; APIs documentadas y nodos internos bajo una autoridad. | Roles separados en H2/final, misma organización; cinco relaciones, flujos internos por VPC y pruebas externas C/S. | E1; E4/H2; E7–9. | [A2/A4/A10](arquitectura.md#a2); servicios cliente/control/datos. | T-COM, T-CLOUD: inventario, APIs y red. |
| COM-00 | Ejecutar sobre Internet, ejemplos REST/gRPC/TCP. P. 4, Comunicaciones de red §3. | Red real con cliente fuera del despliegue; protocolo es elección DIS. | RF1/RF2/RF3 ejecutados por cliente externo contra VMs reales; evidencia de fecha, procesos/hosts y tráfico. | E2 contrato; E9 antes de final. | [A10–11](arquitectura.md#a10); deploy/SDK. | T-CLOUD; local no acredita este requisito. |
| COM-01 | Cliente ↔ ControlNode. P. 5, Protocolos de Comunicación. | Control y metadatos por RPC autenticada, sin contenido del archivo distribuido. | API/errores definidos; traza de Open/Resolve/Commit y failover entre CN. | E2; E3/4; E7/9. | [A4](arquitectura.md#a4); ControlService. | T-COM/T-HA, futuros proto/ y docs/protocolos.md. |
| COM-02 | Cliente ↔ DataNode. P. 5, Protocolos de Comunicación. | Bytes directos, streaming autorizado. | Put/Get/Patch reales en varios DN; usuario sin permiso de bloque rechazado. | E2; E4/5; E8/9. | [A4](arquitectura.md#a4); BlockService/SDK. | T-COM/T-DIST/T-SEC. |
| COM-03 | ControlNode ↔ ControlNode. P. 5, Protocolos de Comunicación. | Coordinación mediada por etcd, representada explícitamente; Q05 pendiente. | Operación iniciada en CN1 puede consultarse/continuar en CN2; ambos comparten locks/resultados; mediación y peers observables. | E2 contrato; E7; E8/H3. | [A4/A7](arquitectura.md#a4); MetadataStore/Coordinator. | T-COM/T-IDEM/T-CONC/T-HA. |
| COM-04 | ControlNode ↔ DataNode. P. 5, Protocolos de Comunicación. | Registro, heartbeat, autorización, recibos y mantenimiento privados. | Incorporación dinámica y ACK auténtico; tarea con identidad/rol incorrecto o generación vencida rechazada. | E2; E4/6/7/8. | [A4](arquitectura.md#a4); NodeService/InternalAuth. | T-COM/T-DISCOVERY/T-FENCE/T-SEC. |
| COM-05 | DataNode ↔ DataNode. P. 5, Protocolos de Comunicación. | Replicación/reparación/base de parche por red privada. | Bloque copiado por conexión real; integridad/durabilidad del destino; nodo falso y tarea inválida rechazados. | E2; E4 diseño; E5/6/8 implementación. | [A4/A6/A8](arquitectura.md#a4); ReplicaService. | T-COM/T-REPL/T-SEC. |
| API-01 | Cada nodo expone una API; cliente CLI/API y roles CN/DN. P. 5, Componentes e Infraestructura. | API por rol, pública o privada según consumidor; SDK documenta su abstracción. | Contratos versionados, firmas/auth/errores y RPC real por rol; interfaz administrativa etcd identificada. | E2; E4/H2; E11. | [A2/A4](arquitectura.md#a2); proto/ y SDK. | T-COMPAT/T-COM; protocolos y ejemplos reproducibles. |
| INF-01 | AWS Academy o GCP académico con VMs IaaS. P. 5, Infraestructura. | Seleccionar proveedor según acceso real; no reemplazar por simulación Docker local. | Inventario de VMs de cuenta académica y ejecución desde Internet; persistencia y prueba de pérdida de VM. | E1 diseño; E9 validación. | [A10–11](arquitectura.md#a10); deploy/. | T-CLOUD, T-HA: inventario real y evidencias externas. |
| INF-02 | Cada nodo nativo o en contenedor Docker. P. 5, Infraestructura. | Docker por host propuesto; Linux nativo alternativa permitida. | Arranque reproducible de cada rol, puertos, volúmenes y reinicio documentados. | E2; E3/4/7/9. | [A1/A11](arquitectura.md#a1); Docker/configuración prevista. | T-REPRO/T-CLOUD; versiones y arranque limpio. |
| INF-03 | Contenedores pueden estar en distintas máquinas; puertos por Internet o red local. P. 5, Infraestructura (posibilidad, no obligación adicional de Docker). | Topología con hosts/volúmenes propios para demostrar tolerancia al fallo de host. | Mapa host→rol→volumen y reglas públicas/privadas; no contar tres contenedores en un host como HA de host. | E1 diseño; E9. | [A10](arquitectura.md#a10); inventario deploy/. | T-CLOUD/T-HA: host real de cada réplica/miembro. |

<a id="entregables"></a>
## 4. Entregables y cronograma

| ID | Obligación y fuente | Interpretación / criterio observable | Etapa prevista | Diseño / artefacto previsto | Evidencia por producir |
| --- | --- | --- | --- | --- | --- |
| ENT-01 | Informe técnico PDF o Word. P. 5, Entregables 1; p. 7, criterio final. | Exportar documento completo que incluya objetivo/marco teórico; servicio/problema; arquitectura/diagramas; protocolos/APIs; algoritmos de particionamiento/distribución; entorno nativo/Docker; pruebas y análisis. Incorporar implementación/resultados mencionados en p. 7. | Documentación continua E1–10; exportar E11/final. | Especificación/arquitectura actuales alimentarán informe editable y PDF/Word final. | T-DELIVERY: archivo exportado revisado visualmente, referencias y contenido verificado. Markdown solo no basta. |
| ENT-02 | Código fuente en GitHub bien documentado. P. 5, Entregables 2; reproducible p. 7. | Repositorio remoto real, fuente comentada, README, dependencias, configuración sin secretos y ejecución desde checkout limpio. | Preparar Git/estructura E2; código E3–10; cierre E11. | src/, proto/, tests/, deploy/, scripts/, README y remoto por definir. | T-REPRO/T-DELIVERY: URL real cuando exista, revisión/commit, comandos y resultados reproducibles. |
| ENT-03 | Video de 10–15 min, explicación y ejecución en vivo o simulada. P. 5, Entregables 3; p. 7, criterio final. | Grabación real de duración en rango, detalles técnicos y procesamiento distribuido. Identificar simulación si se usa; no sustituye prueba cloud. | Preparar evidencia E3–10; grabar E11. | Guion/demo y video final; no creados en E1. | T-DELIVERY: duración, archivo/enlace real revisado; un guion no es video entregado. |
| H-06 | Semana 6: enunciado del proyecto 1. P. 6, Cronograma. | Referencia temporal: conservar el enunciado disponible y su revisión, sin fingir haberlo recibido en otra fecha. | E1 inventario. | PDF/hash y lectura actual. | EJECUTADO inventario; fecha de publicación docente no inferida. |
| H-07 | Semana 7: especificación definitiva por equipo. P. 6. | Entregar definición, arquitectura y decisiones; revisión del equipo/consultas registradas. | E1. | Cinco documentos de esta etapa. | Documentos actuales; entrega/revisión académica PENDIENTE. |
| H-08 | Semana 8: hito 1, diseño e implementación monolítica C/S, RF1 y RF2 completos. P. 6. | Cliente y un servidor por red; pruebas de RF1/RF2, persistencia, errores e interrupciones; conservar versión identificable. | E2–3/H1. | [A1](arquitectura.md#a1); docs/hito1.md y referencia Git previstos. | T-RF1/T-RF2/T-REPRO; no usar versión distribuida para omitir monolito. |
| H-10 | Semana 10: hito 2, arquitectura distribuida opción 1/2 y especificación de comunicaciones. P. 6. | Solo opción 1 en este equipo; división de roles, bloques y protocolos verificados. | E4/H2. | [A1/A4](arquitectura.md#a1); docs/hito2.md/protocolos.md. | T-DIST/T-COM, versión Git del hito. |
| H-12 | Semana 12: hito 3, HA, replicación, consistencia, seguridad. P. 6. | Concluir E5–8, incluido RF3 según plan del equipo, con pruebas reales de esas propiedades. | E5–8/H3. | [A6–10](arquitectura.md#a6); docs/hito3.md/seguridad.md. | T-CONC/T-REPL/T-HA/T-QUORUM/T-SEC/T-KEYS. |
| H-13 | Semana 13: entrega final. P. 6. | Reunir sistema, ejecución cloud y ENT-01–03, sin pendientes ocultos. | E9–11/final. | Auditoría final, informe, GitHub y video. | T-CLOUD/T-DELIVERY y matriz actualizada con resultados reales. |

Las semanas **9 y 11 están vacías** en el PDF: el equipo puede utilizarlas para trabajo interno, pero no se inventa un hito oficial en ellas. Las fechas calendario exactas, integrantes y asignación de responsables no constan en el material disponible.

<a id="rubrica"></a>
## 5. Criterios de evaluación sin completar los puntos suspensivos

Los nombres/pesos siguientes son explícitos. Para los primeros seis, «Aspectos Evaluados» contiene `…`: se conserva así. La columna de evidencia es una **propuesta de preparación del equipo**, no una rúbrica inventada ni garantía de nota. La numeración «5» aparece dos veces en p. 7; los IDs EV evitan confundir esas filas sin corregir silenciosamente la fuente.

| ID local | Nombre y numeración del PDF | Peso | Página / sección | Aceptación documental observable y evidencia prevista del equipo | Etapas |
| --- | --- | --- | --- | --- | --- |
| EV-01 | 1. Definición del servicio y Diseño arquitectónico | 15% | P. 6, Criterios de Evaluación. Aspectos: `…`. | Especificación y diagramas reflejan versión entregada; matriz y decisiones citadas. Documentos actuales, actualización final pendiente. | E1, E11. |
| EV-02 | 2. Especificaciones de comunicaciones | 15% | P. 6. Aspectos: `…`. | Contratos/protocolos y trazas de cinco relaciones; T-COM. | E2/4/7/11. |
| EV-03 | 3. diseño para escalabilidad | 15% | P. 6. Aspectos: `…`. | Diseño de partición/paginación y T-SCALE con límites y resultados reales. | E1/4/10/11. |
| EV-04 | 4. Alta Disponibilidad | 15% | P. 6. Aspectos: `…`. | T-HA/T-QUORUM/T-CLOUD para control, datos, metadatos y acceso; límites explicados. | E6–9/11. |
| EV-05 | 5. Replicación y consistencia de datos | 15% | P. 7. Aspectos: `…`. | T-REPL/T-CONC/T-IDEM/T-FENCE/T-DELETE y versiones/ACK comprobados. | E5–7/10/11. |
| EV-06 | 5. Seguridad | 15% | P. 7. Aspectos: `…`. | T-SEC/T-KEYS y configuración de seguridad real por capa. | E2–8/11. |
| EV-07 | 6. Video e informe final | 10% | P. 7. Aquí sí hay tres aspectos escritos. | Video 10–15 min con ejecución/detalles técnicos; informe completo con objetivos/arquitectura/implementación/pruebas/resultados; GitHub documentado y reproducible (ENT-01–03). | E11. |

Total: **100% = 6 × 15% + 10%**. La evaluación del docente y la satisfacción funcional final están pendientes.

<a id="usuario"></a>
## 6. Reglas explícitas del usuario y metas propuestas

Fuente de todas las filas USR: solicitud de etapa 1 de esta sesión, sin número de página; no se atribuyen al PDF como texto literal.

| ID | Regla / interpretación | Criterio observable | Etapa | Diseño / implementación prevista | Evidencia prevista |
| --- | --- | --- | --- | --- | --- |
| USR-STAGE | Solo etapa 1, inspeccionar antes de editar, preservar archivos y entregar los cinco documentos. | Inventario/fuentes y cinco Markdown coherentes; sin implementación funcional ni provisión. | E1. | [Estado](estado.md). | Auditoría documental actual y hashes de fuentes. |
| USR-RF3 | RF3 obligatorio; snapshots al abrir; close libera y write tiene confirmación definida. | Semántica completa actual; casos de versiones y commits implementados después. | E1/E5/E7. | [S6](especificacion.md#s6); HandleService. | T-RF3; solo diseño EJECUTADO ahora. |
| USR-CONC | Writers en bloques distintos sin pérdida; solapamientos y locks vencidos definidos. | Concurrencia desde dos CN conserva deltas compatibles; propietario vencido no publica ni libera lock nuevo. | E5/E7. | [A7](arquitectura.md#a7); Coordinator/Txn. | T-CONC/T-FENCE. |
| USR-ATOMIC | No anunciar completo sin durabilidad y publicación atómica; sin versiones mezcladas ni actualizaciones perdidas. | Caídas antes/después de ACK/commit dejan estado previo o nueva versión completa, y resultado recuperable. | E3/E5–7. | [A6](arquitectura.md#a6); ledger/commit. | T-ATOMIC/T-IDEM. |
| USR-DEL | Borrado no puede permitir resurrección por operaciones antiguas. | rm seguido de recreación usa otro file_id; writer/GC obsoleto no altera recurso nuevo. | E5–7. | [S6](especificacion.md#s6), [A8](arquitectura.md#a8); tombstones/GC. | T-DELETE/T-FENCE. |
| USR-HA | HA incluye control/metadatos/acceso/claves; réplicas de un host no toleran perderlo. | Un host perdido deja todas las dependencias necesarias; quórum perdido da error acotado. | E6–9. | [A10](arquitectura.md#a10); topología y bootstrap. | T-HA/T-QUORUM/T-KEYS. |
| USR-DATA | ControlNode solo metadatos en distribuido; lectura/escritura con varios DN y localización dinámica. | Inspección de contratos y contadores de bytes; cambio de nodos sin tabla cliente. | E2/E4/E9. | [A4–5](arquitectura.md#a4); SDK/BlockService. | T-DIST/T-DISCOVERY. |
| USR-SEC | Autorización DN; no cripto/consenso propios; claves recuperables. | block_id sin permiso rechazado; dependencias oficiales y pruebas de TLS/cifrado/restore. | E2–8. | [A9](arquitectura.md#a9); Authorizer/crypto. | T-SEC/T-KEYS/T-COMPAT. |
| USR-EVID | Diferenciar EJECUTADO, FALLIDO, PENDIENTE y BLOQUEADO POR ENTORNO; local no acredita Internet. | Toda afirmación de resultado enlaza a ejecución real; pruebas no ejecutadas siguen pendientes. | Todas. | [Estado](estado.md); registro de pruebas. | T-CLOUD y auditorías por etapa. |
| DIS-METAS | 4 MiB/256 KiB, R=3/W=2, 3 CN/3 etcd; objetivos 1 GiB/10 clientes/cantidades crecientes. Fuente: propuesta USR y decisiones DIS. | Parámetros visibles y pruebas con política declarada; ningún valor aparece como exigencia numérica del PDF o resultado obtenido. | E1 diseño; E4–10 validar. | [S9](especificacion.md#s9), [decisiones](decisiones.md#adr). | T-SCALE/T-REPL/T-HA. |

<a id="pruebas"></a>
## 7. Catálogo de pruebas y ubicación de evidencias futuras

No existen todavía estas pruebas ni sus directorios. Cada ejecución deberá registrar requisito/ID, precondiciones, comandos exactos, revisión de código, versiones/configuración, hosts, resultado esperado/real, estado, datos brutos y límites. Convención futura: `docs/evidencias/etapaN/T-ID/`; la implementación prevista se organizará en `src/dfsha/{client,control,datanode,common}`, `proto/`, `tests/`, `deploy/` y `scripts/` a partir de E2.

| ID de prueba | Alcance verificable | Primera etapa de evidencia prevista |
| --- | --- | --- |
| T-COMPAT | Toolchain compatible, importación/serialización y RPC TLS Python↔servidor↔etcd reales, Txn/Lease/Lock/Watch. | E2. |
| T-RF1 | Árbol, cwd, errores, permisos, carreras de rmdir/crear y reinicio. | E3. |
| T-RF2 | Transferencia completa, hashes, vacío/fronteras/grandes y destino previo preservado. | E3; ampliar E4/6. |
| T-ATOMIC | Interrumpir antes/después de persistir, de publicar y de responder; nada parcial visible. | E3; ampliar E6/7. |
| T-COM | RPC/conexiones de todas las relaciones, mediación etcd identificada y seguridad por listener. | E2 parcial; completar E4–8. |
| T-DIST | Bytes C→DN y DN→C en varios nodos, manifiesto, checksum y memoria acotada. | E4. |
| T-DISCOVERY | Alta/cambio/fallo de DN sin editar cliente, endpoints alcanzables y ubicación real. | E4; ampliar E7/9. |
| T-RF3 | Modos, offsets, EOF, crecimiento, cruces de bloque, parche, snapshots y close. | E5. |
| T-CONC | Readers y writers; dos bloques compatibles, mismo bloque conflictivo y crecimiento. | E5; dos CN en E7. |
| T-FENCE | Lease vencido, cliente pausado, unlock viejo y tarea de mantenimiento obsoleta. | E5; distribuido E7. |
| T-DELETE | rm con handles abiertos, recreate, commit viejo y GC sin borrar snapshots. | E5; ampliar E6/7. |
| T-IDEM | Respuesta perdida, retry mismo digest, mismatch y consulta desde otro CN. | E3 parcial; completar E6/7. |
| T-REPL | ACK auténticos W/R, fallo/corrupción, retorno, inventario viejo y cuarto DN. | E6. |
| T-CAP | Disco lleno, reserva concurrente, menos de W y cuota de metadatos; raíz anterior intacta. | E3 parcial; completar E6/7. |
| T-HA | Pérdida de CN/DN/miembro y de VM, entrada alternativa, datos/ACL/operaciones conservados. | E7 procesos; E9 hosts. |
| T-QUORUM | Pérdida/restauración de mayoría, partición, errores/deadlines y sin autoridades divergentes. | E7. |
| T-SEC | Acceso usuario/grupo/ACL, permiso directo DN, revocación, certificados, nodo falso y datos cifrados. | E3 base; completar E8. |
| T-KEYS | Reemplazar DN, claves correctas/ausentes, rotación, backup y restauración aislada. | E8. |
| T-CLOUD | RF1/RF2/RF3 desde cliente externo, hosts académicos distintos, S/S privado y fallo de VM. | E9. |
| T-SCALE | Tres dimensiones RNF1, p50/p95, throughput útil, RSS/CPU, errores y distribución. | E4 medición base; consolidar E10. |
| T-REPRO | Dependencias y arranque reproducibles, persistencia y checkout limpio. | E2 base; E3/9/11. |
| T-DELIVERY | Informe exportado, remoto GitHub real, video 10–15 min y auditoría de cada requisito. | E11. |

Para continuar: actualizar esta matriz cuando exista código/prueba/evidencia concreta; sustituir componentes previstos por enlaces reales sin borrar la distinción entre diseño y resultados. Conservar FALLIDO hasta resolver un fallo y volver a ejecutar su verificación pertinente.

<a id="etapa2"></a>
## 8. Trazabilidad de la etapa 2 ejecutada

Estos identificadores E2 son tareas explícitas del usuario, no nuevos RF/RNF del PDF. Se mantienen todos los criterios, páginas/secciones, pesos y etapas de las tablas anteriores; RNF8/Q01–Q07 sin aclaración docente nueva. [Protocolos](protocolos.md) cubre cada RPC; [catálogo](rpc-catalog.json) diferencia tres implementadas y 47 futuras. Resultados completos en [evidencias E2](evidencias/etapa2/README.md).

| ID E2 / relación con requisitos | Criterio observable y etapa | Contrato/diseño | Implementación y prueba/evidencia real | Límite o pendiente |
| --- | --- | --- | --- | --- |
| E2-ENV · INF-02/03, T-REPRO | Ejecutar con ruta única y versiones comprobadas, sin depender de Docker/WSL ausentes. | D03/D19/D21, entorno.md. | [Bootstrap PS/Bash](../scripts/), pyproject/lock; [inventario](evidencias/etapa2/entorno-git.json), pip check, instalación limpia y build wheel. | Windows EJECUTADO; Linux/cloud PENDIENTE. |
| E2-GIT · ENT-02 | Consultar remoto/historia antes de inicializar; conservar historial y documentar sincronización. | D24, URL proporcionada por usuario. | Remoto vacío confirmado, default_branch main por API, origin configurado; [entorno/Git](evidencias/etapa2/entorno-git.json). | Sin commits/push; sincronización/permiso escritura PENDIENTES. No acredita entrega GitHub final. |
| E2-DEP · T-REPRO, COM-03 | Dependencias exactas compatibles, fuentes/licencias, stubs generables/importables. | D03/D05. | [lock](../requirements.lock), [fuentes](../third_party/sources.lock.json), [generador](../scripts/generate_proto.py); 34 módulos importados en wheel limpio. | Adaptadores definitivos y prueba Linux PENDIENTES. |
| E2-RPC · RF1/RF2/RF3, COM-01–05, API | Tabla por RPC con tipos/límites/auth/errores/plazos/idempotencia/ACK; futuros UNIMPLEMENTED. | [protocolos](protocolos.md), [proto v1](../proto/dfsha/v1/), D22/D23. | [pending.py](../src/dfsha/control/pending.py), 47 casos test_all_future_rpcs_are_unimplemented; auditoría de 50 filas/catálogo. | RF1/RF2 E3 y RF3 E5 siguen sin implementar. COM-03 es mediación, no RPC CN–CN directa. |
| E2-MOD · H-08, D02/D04 | Arrancar servidor sin etcd externo y preparar persistencia local. | [Interfaces](../src/dfsha/common/ports.py), config sqlite/local. | Servidor de diagnóstico arranca sin cliente etcd; [test_local_storage.py](../tests/test_local_storage.py) prueba persistencia/rollback SQLite. | Prueba de biblioteca, no MetadataStore funcional ni RF completos. |
| E2-TLS · RNF6 parcial, T-COM/T-SEC | Cliente/servidor separados por TLS; CA/SAN válidos; mTLS interno rechaza cliente ausente/ajeno. | D17, config con listeners separados. | [server.py](../src/dfsha/control/server.py), [test_transport.py](../tests/test_transport.py); positivos y negativos reales, cliente como subprocess. | No autentica aún usuarios/ACL ni autoriza bloques del DFS. |
| E2-STREAM · RNF1/5 preparación, COM-02 | Stream real incremental, offsets/hash/longitud validados, chunks≤256 KiB; rechazar excesos/corrupción/plazo. | DiagnosticService; B=4 MiB, write≤16 MiB y límite wire 1 MiB. | 8 MiB+17 B por dirección/listener; hash de fixture independiente; pruebas de negativos/deadline. Página64=8399 B y CommitWrite5 con R3=7701 B en fixture de límites. | No son archivos distribuidos ni medición RSS/throughput. Metas 1 GiB/10 clientes PENDIENTES. |
| E2-CRYPTO · RNF6 parcial | AES-GCM cifra/descifra y rechaza alteración; contraseña correcta verifica y errónea falla. | D16/D17. | [test_security.py](../tests/test_security.py), cryptography/argon2-cffi mantenidas. | Cifrado de volúmenes/metadatos, claves/rotación/recuperación E8 PENDIENTES. |
| E2-ETCD · COM-03, RNF3 preparación | KV, CAS aceptado/rechazado, lease vence, Lock/Unlock con propietario obsoleto rechazado, Watch recibido. | Contratos oficiales v3.6.14; comparisons dentro de Txn. | [test_etcd.py](../tests/test_etcd.py), instancia real y prefijo único; revisión de evento/fencing y expiración observados. | No demuestra consistencia DFS, coordinador definitivo, consenso ni HA. Mayoría/failover E7 PENDIENTE. |
| E2-ETCD-SEC · RNF6 parcial | TLS/mTLS con autenticación/RBAC, usuario/rango denegados; servicio detenido devuelve error acotado. | CN de certificado, root/probe/denied y prefijo aislado. | Mismo test_etcd; PERMISSION_DENIED, rechazos TLS y DEADLINE_EXCEEDED/UNAVAILABLE controlado; cleanup cero claves. | No equivale a autorización DN/usuarios del DFS. |
| E2-SCRIPTS · T-REPRO, USR-EVID | Scripts de preparar/generar/iniciar/detener/verificar; evidencia de resultado y límites. | entorno.md/README y estados explícitos. | [verify_stage2.py](../scripts/verify_stage2.py), [smoke_dev.py](../scripts/smoke_dev.py), JSON/XML y logs permitidos; cierre ordenado DFSha comprobado. | No hay instalación de sistema, despliegue ni comandos de cloud ejecutados. |
| E2-DOC · RNF8, ENT-01/02 preparación | Estado, decisiones, matriz y protocolos coherentes; fuentes originales conservadas. | Documentos vivos + ZIP E1 con originales. | [auditoría documental](evidencias/etapa2/auditoria-documental.json), enlaces, filas RPC, hashes de PDF/guía. | Informe final PDF/Word y video 10–15 min siguen E11. |

La aprobación local de E2 habilita preparar **E3/H1 monolítico**, sin saltar RF1/RF2 ni presentar controles/datos distribuidos ya ejecutados. Las relaciones COM-01–05 están definidas; su prueba funcional completa permanece en las etapas indicadas originalmente.
## Correspondencia añadida E3 (sin cambiar requisitos del PDF)

Tabla histórica del cierre E3: la columna Pendiente refleja aquel momento.
E4 ya ejecutada se registra en la siguiente tabla; DN–DN tiene una primitiva
de copia comprobada en E4 y su política automática continúa para E6.

| ID / decisión | Implementación | Comprobación | Pendiente |
| --- | --- | --- | --- |
| RF1, H1 | SDK/CLI, Queries/Commands, SQLite | test_rf1_paths_permissions_pagination_cwd; test_cli_process_and_interactive_shell | Regresión distribuida E4 |
| RF2, H1 | UploadService, BlockService, snapshots/pins | test_binary_boundaries; test_overwrite_snapshot_delete_idempotency | Distribución E4, réplica E6 |
| RF3 | Open(R)/RenewHandle/Close/Resolve como apoyo RF2 | Snapshots/renovación; futuros UNIMPLEMENTED | Parcial/PatchBlock/locks E5 |
| RNF1/RNF4/RNF5, D26/D27 | Perfiles 4/64/128 MiB, fragmentos 256 KiB, admisión 4/2/1 | test_large_profiles_boundaries; medición 1 GiB/3 clientes | Escala de archivos y multinodo E4/E10 |
| RNF2/RNF3, D25/D28 | WAL/FULL, commit atómico, ledger, tombstones, GC | test_fault_recovery_and_lost_commit_response; persistencia/reinicio | R1/W1 no es HA; réplica E6, control/quórum E7 |
| RNF6 | TLS/mTLS, Argon2id/sesiones/ACL, AES-GCM, clave persistente | Negativas E2, revocación, corrupción, clave inválida | Volumen/SQLite/backups/custodia externa E8 |
| RNF7, COM-01/02 | Endpoint resuelto en plan, mismo servidor H1 | SDK/conexiones/hash reales, sin rutas físicas en cliente | Transparencia multinodo E4 |
| COM-03/04/05, D29 | Puertos/contratos, colocación local | Catálogo 51 RPC/stubs | Heartbeats E4, DN–DN E6, CN–etcd–CN E7 |
| RNF8, USR, D30 | Decisiones propias, fuentes preservadas | Contrato H1, PDF leído otra vez | Q01–Q07; RNF8 sin adiciones concretas |
| INF/ENT/H/EV | Windows/docs/código y cronograma | estado.md, hito1.md, Git | Linux/cloud; informe/video 10–15 min, semana 13 |

Evidencias: [índice E3](evidencias/etapa3/README.md). Pruebas E4 usarán varios
bloques por perfil (512 MiB/1 GiB), bytes útiles de lectura y escritura por DN.
64 MiB ya no garantiza cruzar bloques; se sustituye ese ejemplo anterior.
## Trazabilidad adicional de E4 (usuario; no nuevos criterios del PDF)

Estado de ejecución de cada prueba en [evidencia E4](evidencias/etapa4/README.md).

| Requisito conservado | Diseño / implementación E4 | Aceptación observable y prueba | Límite / siguiente evidencia |
|---|---|---|---|
| RF1, RF2 | Commands/Queries H1 + DistributedControl + SDK + DataNode | `test_namespace_snapshot_lost_commit_and_control_restart`, `test_cli_process_and_unindexed_crash_recovery`, roundtrip distribuido | Sin RF3 funcional completo |
| RNF1, RNF4, RNF5, DIS tamaños | Planes por métricas, reservas SQLite, páginas ≤64, 4/64/128 MiB por archivo, chunks 256 KiB | `test_profiles_boundaries_and_coexistence`, `test_dynamic_fourth_node_reservations_and_unavailable`, measure_hito2 512 MiB/3 clientes; bytes útiles de un archivo en ≥2 DN | Concurrencia por clientes; benchmarks E10; Q02 pendiente |
| RNF2, RNF3 | R=1/W=1, publicación única y recibos autenticados; snapshots, tombstones, generaciones | `test_distribution_roundtrip_copy_restart`, `test_interruption_expiry_restart_and_late_receipts`; caída con respuesta UNAVAILABLE o aborto | No HA general; R3/W2 E6 y control/etcd E7 |
| RNF6 | TLS C/S, mTLS S/S, permisos online, AES-GCM, inventarios/recibos persistidos | `test_block_authentication_corruption_and_internal_roles`, regresión E2/H1, recuperación de objeto huérfano | SQLite/WAL/backups sin cifrado aplicativo; seguridad integral E8 |
| RNF7 | ResolveBlocks consulta autoridad; SDK no contiene mapa estático; nueva consulta tras fallo | Cuarto nodo y lectura de archivo previo; copia resuelta con origen detenido | Acceso Internet y HA de entrada pendientes |
| COM-01, COM-02 | Cliente–CN metadatos, cliente–DN bytes | SDK/CLI por procesos, tabla tráfico útil, raíz control sin objetos | Cero contenido no significa cero red |
| COM-03 | Un ControlNode; arquitectura final mediada por etcd preservada | UNIMPLEMENTED/futuro honesto | E7, Q05 docente sin resolver |
| COM-04, COM-05 | Registro/heartbeat/inventario/recibos/autorizar/tareas mTLS; GetReplica origen→destino | Copia real, lectura sin origen, VerifyReceipt tras reinicio | No reparación automática ni resistencia al host |
| INF, ENT, H2 | Laboratorio reproducible Windows local, scripts, documentación y Git existentes | verify_stage4, wheel instalado, hito2/protocolos, commit y push al cierre si disponibles | Cloud, video e informe final pendientes en cronograma original |
| RF3, RNF8, Q01–Q07 | Contratos futuros conservados; no se reintroduce modelo 2 de acceso | Métodos futuros UNIMPLEMENTED; aclaraciones sin inventar | RF3 E5; RNF8 PDF no agrega contenido concreto |
