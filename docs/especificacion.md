# DFSha — Especificación formal del servicio

**Actualización E4 del usuario:** distribución real de RF1/RF2 preservando las
semánticas de H1; control sin contenido, bytes directos cliente–DN y copia S/S
autorizada, R=1/W=1 temporal, ubicaciones separadas de manifiestos. No etcd ni HA
en este perfil. [Diseño](etapa4-diseno.md), [contrato E4](protocolos-hito2.md).
Los requisitos/cronograma/rúbrica del PDF se conservan. Q01–Q07 sin respuesta
docente nueva; Q02 para archivos pequeños/vacíos y Q05 siguen pendientes.

**Actualización H1/E3 del usuario:** CRUD lógico (incluido overwrite explícito),
perfiles persistidos 4/64/128 MiB por archivo/snapshot, bloques inmutables cifrados,
CQRS sobre SQLite y coordinación local. [D25–D30](etapa3-diseno.md) y
[contrato operativo](protocolos-hito1.md) prevalecen sobre propuestas incompatibles
de E1 que siguen abajo como diseño final. RF1/RF2 implementados; RF3 completo E5.
No es WORM ni retención permanente; snapshots/pins retienen solo referencias válidas.
cd valida identidad y permiso x del directorio; no modifica cwd real del servidor.
No se implementa ni se deja pendiente «modelo 2 de acceso».

Versión de diseño 1.0 · 2026-09-07 · SI3007/ST0263, 2026-2 · Etapa 1.

Este documento define el servicio que se implementará. No acredita implementación, pruebas funcionales ni despliegue. El estado verificable está en [estado.md](estado.md); la cobertura del enunciado, en [matriz-requisitos.md](matriz-requisitos.md).

<a id="s1"></a>
## 1. Fuentes, autoridad y clasificación

La fuente principal es [SI3007-262-proyecto1-dfs.docx.pdf](enunciado/SI3007-262-proyecto1-dfs.docx.pdf), leído íntegramente: siete páginas, numeradas 1–7. Se conserva una [extracción por página](evidencias/etapa1/lectura-pdf.txt). La [guía complementaria](propuesta/Prompts_Codex_DFSha_Opcion1_CS.md), también leída, propone una secuencia de once etapas; sus afirmaciones sobre otros chats o estudios previos no se toman como evidencia accesible.

Se usan estas clases en los documentos:

| Clase | Significado y autoridad |
| --- | --- |
| PDF | Requisito u obligación explícita del archivo disponible, con página y sección. |
| USR | Instrucción explícita del usuario en la solicitud de etapa 1, incluidas las reglas de corrección final. No se atribuye al docente. |
| INT | Interpretación operativa del equipo sobre texto abierto o ambiguo; se registra la consulta docente si corresponde. |
| DIS | Decisión o parámetro técnico adoptado para este diseño; revisable con justificación. No es una exigencia del PDF. |

El PDF y las aclaraciones explícitas del docente prevalecen sobre la guía técnica. No se encontró una aclaración docente independiente. La opción 1 se toma de la elección expresa del usuario. RNF8, p. 2, contiene únicamente tres puntos suspensivos: no añade exigencias concretas. Los ejemplos de pp. 4–5 y los recursos sugeridos de p. 7 no obligan a usar un NameNode único, HDFS, FastAPI, Kafka, Linux o Docker.

<a id="s2"></a>
## 2. Objetivo, problema y actores

**Objetivo general (PDF, p. 1; formalización INT):** diseñar e implementar un sistema de archivos distribuido propio que permita almacenar, transferir y modificar archivos grandes mediante varios nodos, con acceso concurrente, consistencia, redundancia, seguridad y localización dinámica. Tanto la escritura como la lectura de un archivo de varios bloques deben usar varios DataNodes.

**Problema:** un servidor único concentra capacidad, ancho de banda y fallos; copiar archivos completos tampoco resuelve el acceso parcial concurrente. DFSha debe preservar un árbol lógico estable mientras cambia la ubicación física de sus bloques y debe definir qué observa el usuario ante concurrencia, interrupciones y reintentos.

| Actor | Necesidad y responsabilidad |
| --- | --- |
| Usuario autenticado | Gestionar sus recursos y los compartidos con su usuario/grupo, mediante CLI. |
| Aplicación cliente | Usar el SDK para transferencias y acceso por offset; manejar errores y resultados inciertos. |
| Administrador de la organización | Gestionar usuarios, grupos, ACL, cuotas, nodos, certificados, claves y recuperación; acciones auditables. |
| ControlNode | Resolver rutas y versiones, autorizar, coordinar operaciones y publicar metadatos. |
| DataNode | Conservar bloques y atender bytes autorizados, replicación e integridad. |
| Equipo y docente | Especificar, revisar decisiones y demostrar cumplimiento con evidencias. |

Los servidores pertenecen a una organización. No hay federación de SuperPeers ni confianza entre organizaciones independientes. La CLI/SDK es el consumidor del servicio, aunque se desarrolla y entrega como parte del proyecto.

<a id="s3"></a>
## 3. Alcance y relación con el curso

Incluye árbol jerárquico, RF1/RF2/RF3, archivos binarios, distribución de bloques, concurrencia dentro de un archivo, replicación, recuperación, autorización por usuario/grupo, cifrado y ejecución final sobre Internet en VMs académicas. Se implementa un DFS propio; las dependencias aportan transporte, persistencia, consenso y criptografía, pero no sustituyen la lógica del servicio.

La arquitectura **C/S** describe las llamadas del consumidor al servicio. La **composición S/S** descompone ese servicio en control, datos y coordinación, sobre una red privada. Una RPC hace accesible una operación remota mediante un contrato; gRPC/Protocol Buffers será el middleware propuesto. Una RPC puede fallar después de que el servidor haya confirmado: no equivale a una llamada local infalible.

La **transparencia de acceso** consiste en rutas y operaciones uniformes en CLI/SDK. La **transparencia de localización** consiste en resolver los endpoints y réplicas en ejecución. La **concurrencia** permite varias sesiones, lecturas de snapshots y preparación simultánea de cambios sobre bloques distintos, con publicación ordenada de versiones.

Límites DIS: no se promete POSIX completo, montaje FUSE, ejecución de binarios remotos, enlaces duros/simbólicos, renombrado/movimiento, borrado recursivo, archivos dispersos, append atómico, interfaz web, erasure coding ni tolerancia bizantina. Estos límites no eliminan RF3. Archivos vacíos tienen solo metadatos; uno pequeño puede ocupar un bloque, y uno grande reparte sus bloques entre nodos. Esta interpretación de RNF4 se someterá al docente (Q02).

El monolito de semana 8 tiene almacenamiento local y un servidor; la HA es una obligación final, no una propiedad de ese hito. El tamaño máximo anunciado será configurable y al menos 1 GiB en el perfil de validación propuesto, sujeto a recursos. Un límite de recursos se informa, no se disfraza de escalabilidad ilimitada.

<a id="s4"></a>
## 4. Operaciones del usuario y del SDK

| Familia | Operaciones y resultado |
| --- | --- |
| Identidad | `login`, `logout`; administración mínima de usuarios, grupos y ACL. |
| RF1 | `ls [ruta]`, `cd ruta`, `mkdir ruta`, `rmdir ruta`, `rm ruta`. Adiciones DIS: `pwd`, `stat`, `chmod`/gestión de ACL. |
| RF2 | `send(local, remoto)` / `put`; `receive(remoto, local)` / `get`. Transferencia completa con confirmación o aborto. |
| RF3 | `open(path, mode)`, `close(handle)`, `read(handle, offset, length)`, `write(handle, offset, data)`, `lock(handle, range, wait_timeout)`, `unlock(lock_token)`. |
| Soporte DIS | Renovar handle/lock, consultar operación por identificador, abortar upload, obtener estado normal/degradado. |

`cd` y `pwd` pertenecen al contexto de la CLI/SDK: no cambian el directorio del proceso servidor. `send`, `receive`, `read` y `write` son operaciones compuestas del SDK. En el sistema final sus RPC de control solo contienen metadatos; `PutBlock`, `PatchBlock` y `GetBlock` llevan bytes directamente a/desde DataNodes. Los contratos `.proto` se crearán en etapa 2, según [arquitectura, §4](arquitectura.md#a4).

<a id="s5"></a>
## 5. Semántica del espacio de nombres y de RF2

### Rutas y directorio actual

El espacio remoto empieza en `/`, distingue mayúsculas y usa `/` en cualquier sistema cliente. Nombres Unicode se normalizan a NFC antes de comprobar duplicados. Se rechazan NUL, separadores dentro de un nombre y `\` en rutas remotas. Límites iniciales DIS: 255 bytes UTF-8 por componente, 4096 por ruta y profundidad 32; se devuelven errores explícitos al excederlos.

Una ruta absoluta parte de `/`; una relativa, del directorio actual de la sesión. `.` conserva la ubicación; `..` sube un nivel y permanece en `/` al llegar a la raíz. El servidor resuelve y autoriza el recorrido, incluidos componentes anteriores a `..`, y nunca concatena sin validar una ruta remota a una ruta del host.

Una sesión comienza en `/`. `cd` verifica existencia, tipo directorio y permiso de recorrido; solo después cambia su contexto. Un `cd` fallido conserva el contexto anterior. El SDK conserva `cwd_path` y `directory_id`: si el directorio se elimina o se recrea con otra identidad, una operación relativa devuelve `CWD_GONE`. Un `cd /` absoluto restablece un contexto válido. El servidor valida la identidad del cwd recibida; cada sesión tiene su propio cwd.

### Gestión y errores de directorios

| Operación | Semántica DIS y errores observables |
| --- | --- |
| `ls` | Lista nombres y tipos ordenados, con paginación. Token ligado a identidad/revisión del directorio; cambio concurrente devuelve `LIST_CHANGED` y exige reiniciar listado. |
| `mkdir` | Crea un directorio vacío; el padre debe existir. Sin creación recursiva implícita. Nombre existente: `ALREADY_EXISTS`. |
| `rmdir` | Elimina solo un directorio vacío. No vacío: `DIRECTORY_NOT_EMPTY`; archivo: `NOT_DIRECTORY`. Raíz: `ROOT_PROTECTED`. |
| `rm` | Elimina un enlace de archivo del árbol. Directorio: `IS_DIRECTORY`. No acepta borrado recursivo. |
| Todas | Distinguen `NOT_FOUND`, `PERMISSION_DENIED`, tipo erróneo y entrada inválida. Las RPC usan códigos gRPC y un motivo de dominio estable; no se analizan mensajes de texto para decidir reintentos. |

La creación/borrado de hijos y el contador/revisión del directorio se actualizan en la misma transacción. `rmdir` compara que sigue vacío al confirmar: un `mkdir`/upload concurrente no puede crear un hijo en un padre borrado. Una entrada de archivo nunca señala un upload incompleto.

### Transferencia completa

`send`/`put` recibe una fuente local estable y un destino remoto exacto. Por defecto, si existe el destino devuelve `ALREADY_EXISTS`; `overwrite=true` solicita reemplazarlo. Un reemplazo mantiene la versión anterior visible hasta confirmar todos los bloques de la nueva. La sesión de upload reserva el nombre o el archivo con lock exclusivo de archivo; no bloquea lecturas del snapshot anterior. Una modificación de la fuente local detectada durante el envío obliga a abortar; las pruebas usarán fuentes inmóviles.

Un envío confirma **una versión completa en una sola publicación**. No se implementará un `send` grande exponiendo sucesivos commits de `write`. Aunque comparta primitivas internas, necesita su propia transacción de upload. Un archivo vacío puede publicarse tras validar metadatos y permisos, sin exigir ACK de bloques inexistentes.

`receive`/`get` abre un snapshot, descarga sus bloques en orden lógico y valida tamaño/checksums. Escribe a un temporal local y reemplaza el destino al terminar mediante la operación atómica del filesystem local; por defecto rechaza un destino existente. Ante fallo conserva el destino previo y reporta un temporal recuperable o limpiable. No necesita un volumen compartido con el servidor. Un cambio remoto durante la descarga no mezcla versiones.

<a id="s6"></a>
## 6. Semántica de RF3

### Handles, modos y snapshots

Un handle opaco pertenece a una sesión/usuario; contiene en el control `file_id`, raíz del snapshot, tamaño, modo, `content_epoch`, revisión de handle y lease. Un `file_id` jamás se reutiliza. `open` se linealiza al leer la versión vigente y registrar su pin en una transacción que compara que esa versión aún es la actual. El almacenamiento de snapshots es explícito; no depende de conservar indefinidamente el historial MVCC de etcd.

| Modo | Si existe | Si no existe | Permisos y acceso |
| --- | --- | --- | --- |
| `r` | Fija snapshot actual. | `NOT_FOUND`. | Lectura. |
| `r+` | Fija snapshot actual. | `NOT_FOUND`. | Lectura y escritura parcial. |
| `w` / `w+` | Trunca a vacío atómicamente al abrir bajo lock de archivo. | Crea archivo vacío. | Escritura / lectura y escritura, respectivamente. |
| `x` / `x+` | `ALREADY_EXISTS`. | Crea archivo vacío de forma exclusiva. | Escritura / lectura y escritura, respectivamente. |

Los modos de escritura exigen permiso de escritura; los modos `+`, también lectura. Crear exige escritura y recorrido del padre. No hay modo `a`: se rechaza como `UNSUPPORTED_MODE`. Todas las operaciones trabajan con bytes, sin conversión de texto.

`open(w/w+)` publica explícitamente el truncado vacío; perder datos por elegir ese modo es su efecto solicitado. Se recomienda `send(overwrite=true)` para reemplazos completos con conservación de la versión anterior durante el envío. Truncar o reemplazar todo el contenido incrementa `content_epoch`: los handles de escritura anteriores deben reabrirse, mientras los lectores conservan su snapshot.

Una apertura posterior a un commit ve la versión vigente, como mínimo tan reciente como ese commit. Un handle previo de lectura sigue leyendo su snapshot. Después de su propio `write` confirmado, el handle escritor avanza al manifiesto publicado, que puede incluir cambios concurrentes compatibles. Otros handles no cambian automáticamente. Las operaciones de un mismo handle se serializan; se usan handles separados para escritores concurrentes.

### Offsets, EOF y crecimiento

`read(h, offset, length)` usa offset desde cero y devuelve hasta `length` bytes del snapshot. Offset/longitud negativos o desbordados: `INVALID_ARGUMENT`. Longitud cero devuelve vacío; offset igual o mayor al tamaño devuelve vacío y EOF. Una lectura que cruza EOF devuelve únicamente los bytes existentes. El SDK consulta solo los bloques que intersectan el rango y puede emitir un stream para rangos grandes.

`write(h, offset, data)` sobrescribe bytes del rango `[offset, offset + len(data))`; no inserta ni desplaza. Tamaño final: `max(tamaño_vigente, fin_del_rango)`. No acorta un archivo. Offset igual a EOF permite crecimiento; offset mayor al tamaño del snapshot del handle se rechaza como `SPARSE_WRITE_UNSUPPORTED`, sin crear huecos. Si crece, adquiere también el lock de tamaño y compara el tamaño base con el vigente; crecimiento concurrente incompatible devuelve `VERSION_CONFLICT`. Una escritura interna que no crece conserva una extensión concurrente ajena.

Una escritura vacía valida el handle/permisos y devuelve cero sin nueva versión. Máximo inicial DIS de una llamada `write`: **16 MiB**, que puede tocar hasta cinco bloques de 4 MiB si no está alineada. Una llamada mayor se rechaza; el SDK no la divide silenciosamente en varias operaciones que aparenten atomicidad conjunta. El usuario puede emitir varias llamadas independientes o usar `send` para una transferencia completa mayor.

Los DataNodes preparan nuevas versiones inmutables de los bloques afectados. Para un parche conservan internamente los bytes restantes del bloque: `PatchBlock` recibe el delta y la identidad base autorizada. Esto permite escribir con modo `w` sin conceder al usuario permiso para leer el contenido previo; solo el DataNode puede obtener la base mediante la API interna. La respuesta contiene metadatos y ACK, nunca esos bytes previos. Un parche pequeño no transfiere de nuevo el archivo completo.

### Confirmación, close y resultados inciertos

`write` tiene éxito únicamente cuando cada bloque nuevo satisface la política durable vigente y el control publica atómicamente la raíz, el tamaño, el resultado de operación y la nueva referencia del handle. Política final: objetivo **R=3**, mínimo de publicación **W=2** copias durables verificadas en nodos y dominios de fallo distintos. Los bloques reutilizados ya publicados conservan sus referencias y política; si algún bloque requerido no tiene réplica accesible, se informa indisponibilidad en vez de anunciar una versión completa utilizable. El detalle de validación está en [arquitectura, §6](arquitectura.md#a6).

El punto de commit es la transacción de metadatos, posterior a los ACK de datos. Un ACK de recepción, un búfer local o el cierre del stream no bastan. `W=2` cuenta confirmaciones de datos: no es el quórum de metadatos ni demuestra consistencia por sí mismo.

`close` libera pins, locks y recursos; **no confirma bytes pendientes**. El SDK espera sus operaciones ya iniciadas antes de cerrar; el servidor rechaza un cierre con operación activa mediante `HANDLE_BUSY`. Se permite repetir `close` con el mismo identificador de operación. Si se pierde conexión, el cliente consulta la operación; el vencimiento de leases libera recursos abandonados y nunca revierte un commit ya publicado.

Un timeout no significa necesariamente aborto. `GetOperation(request_id)` devuelve `PREPARING`, `COMMITTED`, `ABORTED` o `EXPIRED`; si no se alcanza el control, el resultado es `OUTCOME_UNKNOWN`. Se conserva la misma identidad e intención en el reintento. Mismo identificador con contenido distinto: `IDEMPOTENCY_MISMATCH`.

### Locks y escritores concurrentes

Los locks son **obligatorios para publicar escrituras**. `lock` explícito y locks internos de `write` usan una autoridad común. Un lock exclusivo protege un rango redondeado a bloques, o el archivo completo mediante un marcador especial. Los lectores de snapshots no toman locks de escritura. Rangos disjuntos dentro del mismo bloque entran en conflicto por la granularidad elegida.

El propietario es `(session_id, handle_id)`; el token incorpora generación de adquisición, lease y época del servicio. El lock parcial explícito usa el mismo máximo de rango de 16 MiB; el lock de archivo cubre cualquier tamaño sin enumerar todos sus bloques. Adquisición de varios bloques: orden ascendente, espera acotada y liberación de adquisiciones incompletas. No hay upgrades implícitos de rango a archivo; se liberan y vuelven a adquirir. Valor inicial de espera: cero; espera opcional máxima de 5 s. Conflicto: `LOCK_CONFLICT`.

Lease DIS de lock: 30 s, renovación cada 10 s. Handle: 120 s, renovación cada 40 s, vida total máxima inicial de 24 h. Son valores de configuración que deben medirse. `unlock` verifica dueño y generación, y jamás libera el lock de un sucesor. Una operación activa impide liberar su lock (`LOCK_BUSY`). La autoridad es el lease del servidor/etcd, no el reloj del cliente. Perder el lease produce `LOCK_EXPIRED`/`STALE_HANDLE`; no se renueva retroactivamente una propiedad vencida.

Para dos escritores sobre bloques distintos:

1. Cada uno toma locks de sus bloques y conserva las identidades base observadas en su snapshot.
2. Preparan y replican los nuevos bloques en paralelo.
3. Antes de publicar, el control lee el manifiesto vigente y verifica archivo vivo, época, permisos, locks y versiones de **los bloques afectados**.
4. Si otro writer cambió únicamente otros bloques, aplica el delta sobre el manifiesto vigente. Hace compare-and-swap (CAS) de su raíz; si vuelve a cambiar, relee y reintenta de forma acotada.
5. Si cambió un bloque afectado, rechaza `VERSION_CONFLICT`. Nunca copia encima todo el manifiesto viejo ni sustituye silenciosamente una base obsoleta.

Ejemplo: desde `[A0, B0]`, un escritor prepara `A1` y otro `B1`. Se puede publicar `[A1, B0]` y después `[A1, B1]`. Desde dos cambios a `A0`, el segundo no publica automáticamente su cambio sobre `A1`: debe reabrir y decidir cómo reaplicarlo. La preparación es concurrente; los commits tienen un orden total. La propiedad de lock y su generación se comprueban **dentro de la transacción final**: un proceso pausado que reanuda con un lease vencido no publica.

### Borrado con archivos abiertos

`rm` elimina inmediatamente el nombre mediante transacción y conserva una marca de borrado (`tombstone`) del `file_id`. No espera a que terminen lectores o escritores. Un lector ya abierto puede continuar su snapshot mientras el handle y sus permisos sigan vigentes; los metadatos de identidad/ACL y ancestros necesarios permanecen retenidos. Una apertura nueva del nombre falla, salvo que se cree posteriormente un archivo con **otro** `file_id`.

Una escritura preparada antes de `rm` se rechaza al comparar el tombstone/época en commit. Si el commit ganó la carrera, `rm` elimina después esa versión. Un upload de reemplazo antiguo tampoco puede recrear el nombre. Los bloques dejan de ser recolectables mientras algún manifiesto vivo, handle, upload o reparación autorizada los use. Borrar metadatos no significa destruir inmediatamente todos los bloques físicos; [arquitectura, §8](arquitectura.md#a8) define la recolección.

<a id="s7"></a>
## 7. Autenticación, permisos y límites de disponibilidad

Autenticación DIS: usuario/contraseña con Argon2id mediante biblioteca mantenida y sesión opaca revocable. La sesión expira inicialmente a los 30 min; el SDK debe reautenticar según contrato. No se envían contraseñas a DataNodes. La autorización distingue usuario, grupos y ACL positivas; denegación por defecto. Los permisos base propietario/grupo/otros se evalúan por la clase correspondiente y se amplían por las entradas ACL coincidentes. No se implementan ACL negativas.

En archivos, `r` autoriza lectura y `w` modificación. En directorios, `r` autoriza listado, `x` recorrido y `w+x` modificación de entradas. Se exige `x` en cada ancestro. `rm`/`rmdir` requieren `w+x` en el padre, como semántica de modificación del directorio; compartir escritura sobre un directorio permite eliminar sus entradas. Cambiar ACL: propietario o administrador autorizado. El administrador gestiona políticas; para lectura por API también necesita permiso de contenido. Nuevos archivos: propietario `rw`, sin acceso de grupo/otros; directorios: propietario `rwx`, sin acceso adicional, salvo política explícita de creación.

La inicialización crea `/` con lectura/recorrido para usuarios autenticados y escritura administrativa; `/users` permite recorrido, con listado administrativo. Cada usuario recibe `/users/<user_id>` con `rwx` propio. Así puede hacer `cd` desde `/` y crear contenido en su directorio, sin concederle escritura sobre la raíz. Los directorios compartidos se habilitan expresamente mediante grupos/ACL.

Cada acceso a DataNode valida sujeto, operación, archivo, versión/bloque, rango, nodo destino y vigencia mediante permiso opaco del control y comprobación interna autenticada. Conocer `block_id` no concede acceso. Permiso de escribir un bloque no permite leer su base ni enumerar el volumen. Acciones de replicación y borrado físico solo aceptan identidades internas autorizadas.

Revocar usuario/grupo/ACL afecta nuevas operaciones y nuevos streams de bloque tras la revocación. Una RPC de bloque ya autorizada puede terminar, limitada a un bloque de 4 MiB y un deadline de 15 s; no se promete retirar bytes ya entregados. El commit revalida permisos actuales, aunque el stream anterior hubiese sido autorizado. Se mantiene un epoch global de autorización para detectar cambios durante esa validación.

Se elige no ofrecer lecturas desconectadas: sin quórum de metadatos no se autorizan nuevos accesos a bloque, ni nuevas aperturas ni mutaciones, incluidos handles existentes. Un stream autorizado antes de perder quórum puede terminar dentro de su límite. Se responde `UNAVAILABLE/METADATA_QUORUM_LOST` con plazo acotado, no con datos actuales tomados de una caché posiblemente vieja.

<a id="s8"></a>
## 8. Escenarios de uso y fallo

| Caso previsto | Resultado observable y prueba futura |
| --- | --- |
| U01: gestionar árbol desde dos sesiones | Cwd independientes, rutas/errores correctos y persistencia al reiniciar (T-RF1). |
| U02: enviar/recibir archivo binario grande | Hash y tamaño idénticos; tráfico útil de lectura y escritura en varios DataNodes (T-RF2, T-DIST). |
| U03: editar un rango que cruza bloque | Solo bloques afectados cambian; bytes exteriores intactos; lectores antiguos conservan snapshot (T-RF3). |
| U04: compartir con grupo | Acceso permitido al miembro y denegado a un tercero; revocación conforme a §7 (T-SEC). |
| U05: dos escritores y dos ControlNodes | Cambios en bloques distintos se conservan; solapados dan conflicto controlado (T-CONC). |
| F01: cliente/stream interrumpido | No aparece un archivo parcial; se consulta estado y se limpia staging seguro (T-ATOMIC). |
| F02: respuesta de commit perdida | Repetición del mismo request_id devuelve el mismo resultado, sin segunda escritura (T-IDEM). |
| F03: cae un DataNode o se corrompe una copia | Lectura elige réplica íntegra; se informa degradación y se repara cuando hay capacidad (T-REPL). |
| F04: cae un ControlNode o un host completo | El SDK usa otra entrada; datos, control, etcd y claves disponibles dentro del modelo de un fallo (T-HA). |
| F05: partición/pérdida de mayoría etcd | Se detienen publicaciones y nuevas autorizaciones; errores con plazo finito, sin dos autoridades (T-QUORUM). |
| F06: escritor vuelve con lock vencido o después de rm | Commit rechazado; no resucita archivo ni invalida el lock nuevo (T-FENCE, T-DELETE). |
| F07: capacidad insuficiente o menos de W copias | `RESOURCE_EXHAUSTED/NO_SPACE` o `INSUFFICIENT_REPLICAS`; versión previa intacta (T-CAP). |
| F08: reinicio/reemplazo con o sin claves | Con claves autorizadas se verifica lectura; sin ellas no se anuncia nodo listo (T-KEYS). |

<a id="s9"></a>
## 9. Metas de validación del equipo

Todos estos valores son **propuestas DIS**, sin mediciones realizadas. Las pruebas conservarán datos brutos, versión/configuración, comandos, hardware, errores y niveles no ejecutados. MiB/GiB son unidades binarias.

| Dimensión | Meta inicial observable |
| --- | --- |
| Tamaño | Vacío, 1 B, 4 MiB−1, 4 MiB, 4 MiB+1, 64 MiB y 1 GiB; hash correcto en send/receive. |
| Usuarios | 1, 5 y 10 clientes simultáneos; cero corrupción/actualizaciones perdidas en los casos esperados como exitosos. |
| Cantidad | 100, 1.000 y 10.000 archivos pequeños; listados paginados sin omisiones/duplicados con árbol estable. |
| Distribución | Archivo de 64 MiB o mayor: al menos dos DataNodes distintos reciben y sirven bytes útiles; incorporar un cuarto sin editar el cliente. |
| Memoria | Inicialmente RSS del cliente ≤256 MiB y de cada DataNode ≤512 MiB con un archivo de 1 GiB y paralelismo 4; separar coste de runtime y criptografía. Ajustar con recursos y evidencia. |
| Fallos | Detección de DataNode objetivo ≤15 s; recuperación de acceso tras pérdida de un host objetivo ≤30 s; nuevas RPC con quórum perdido fallan en ≤5 s. |
| Rendimiento | Medir throughput útil, latencia p50/p95, errores, CPU y memoria; comparar paralelismo 1/4 y 3/4 DataNodes bajo igual R/W, TLS/cifrado y carga. Sin mínimo de MB/s inventado. |
| Reparación | Medir tiempo hasta R=3 al volver un nodo o añadir capacidad; no fijar tiempo antes de conocer disco/red. |

Tres DataNodes con R=3 consumen aproximadamente tres veces los bytes lógicos, más versiones retenidas, staging y metadatos. La prueba de 10 clientes no exige diez archivos distintos de 1 GiB: esa combinación se dimensionará por separado. Deben probarse las tres dimensiones de RNF1 sin confundir una carga pequeña con capacidad ilimitada.

<a id="s10"></a>
## 10. Supuestos, consultas y obligaciones de cierre

| ID | Cuestión pendiente | Supuesto para avanzar y efecto |
| --- | --- | --- |
| Q01 | El PDF conserva una nota de refinamiento hasta el 26 de agosto (p. 1). No consta una revisión posterior. | Usar exactamente el archivo identificado por hash; solicitar al docente cambios posteriores antes de la entrega definitiva. Lectura y trazabilidad de este archivo sí están verificadas. |
| Q02 | RNF4 dice que cada archivo se distribuye entre nodos, sin excepción por tamaño. | Vacío sin bloques, pequeño con un bloque replicado, grande con bloques repartidos. Confirmar la interpretación sin eliminar la demostración de distribución. |
| Q03 | RNF6 enumera user/password, ACL, 2FA y API Keys en un rango de mecanismos. | Implementar usuario/contraseña, grupos/ACL, sesiones y permisos de bloque. 2FA/API keys de usuario adicionales quedan como extensión, salvo exigencia docente. |
| Q04 | Alcance exacto de transparencia RNF7 y de locks/RF3. | CLI/SDK dinámicos sin POSIX/FUSE; snapshots, locks por bloque y conflictos explícitos de §6. Someter la semántica al docente. |
| Q05 | Relación ControlNode–ControlNode mediada por etcd. | Especificarla como comunicación indirecta real; verificar si el docente exige además una RPC directa entre controles. No simular una relación inexistente. |
| Q06 | Rúbrica con aspectos `…` y numeración repetida de «5» en p. 7. | Conservar nombres/pesos; no crear subcriterios docentes ni prometer nota. |
| Q07 | No constan integrantes, grupo, fechas calendario de semanas, proveedor, cuenta, cuotas ni responsables de secretos. | Preparar infraestructura parametrizable sin aprovisionar. Equipo debe completar esos datos y asignar responsables. |

Las cuestiones no resueltas no autorizan rebajar requisitos. Cualquier aclaración se registra con fecha, autor, fuente y efectos en decisiones/matriz, bajo RNF8. No se han enviado preguntas al docente ni aprovisionado recursos.

El cronograma oficial es: semana 6 enunciado; 7 especificación definitiva; 8 hito 1 monolítico C/S con RF1/RF2 completos; 10 hito 2 distribuido y comunicaciones; 12 hito 3 HA/replicación/consistencia/seguridad; 13 entrega final. Semanas 9 y 11 están vacías en la tabla oficial. El [plan por etapas](estado.md#plan) asigna trabajo interno sin convertirlo en fechas docentes adicionales.

Entrega final obligatoria: informe PDF o Word con los siete contenidos de p. 5; fuente documentada y reproducible en GitHub; video de 10–15 min que explique el sistema y muestre procesamiento distribuido, en vivo o simulado identificado como tal. La posibilidad de simulación en el video no sustituye ejecutar el sistema sobre Internet en VMs de AWS Academy/GCP académico.
# Actualización de alcance del hito 1

Aplican [D25–D29](etapa3-diseno.md): CRUD lógico, snapshots inmutables, perfiles
4/64/128 MiB persistidos por archivo, RF1/RF2 en monolito SQLite y coordinación local.
Son decisiones explícitas del usuario; no requisitos nuevos del PDF. RF3 completo sigue en etapa 5.
