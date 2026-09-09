# DFSha: prompts por etapas para Codex

**Proyecto 1 · SI3007 / ST0263 · 2026-2 · Opción 1: cliente/servidor (C/S)**

Esta guía convierte el enunciado en un prompt maestro y once prompts de ejecución. Cada etapa pide trabajo concreto, pruebas y evidencias. La cobertura del enunciado está planificada; el cumplimiento de la implementación deberá demostrarse con esas evidencias.

## 1. Base documental y decisiones de alcance

Se revisaron las siete páginas de **SI3007-262-proyecto1-dfs.docx.pdf**. Es la fuente principal de requisitos y prevalece sobre las decisiones técnicas sugeridas aquí.

El historial visible del proyecto muestra que se han estudiado NFS, arquitecturas C/S, middleware, RPC/RMI, gRPC, MOM y sistemas P2P. Esto sirve para conectar la solución con los temas del curso. No se pudieron revisar los demás archivos de la carpeta ni recuperar conversaciones adicionales; no se atribuye a esos materiales ninguna decisión técnica. El diseño previo del examen se considera un trabajo distinto.

Estas precisiones evitan interpretar mal el alcance:

- La opción 1 mantiene un servicio administrado por una sola organización, con composición y distribución entre servidores dentro de una red privada real o virtual. Los clientes consumen interfaces documentadas.
- El hito 1 es deliberadamente **monolítico C/S**, con RF1 y RF2 completos. La distribución corresponde al hito 2. No hay que saltarse esa primera versión.
- **RF3 sí forma parte del proyecto final**: acceso parcial mediante `open`, `close`, `read`, `write` y `lock`. Una aplicación que únicamente sube y descarga archivos queda incompleta.
- Se debe dividir cada archivo en bloques y distribuirlos. Para demostrarlo se usarán archivos mayores que el bloque; los archivos pequeños pueden ocupar un solo bloque y el archivo vacío solo necesita metadatos.
- Debe haber concurrencia, consistencia y redundancia tanto de los datos como del control y sus metadatos.
- RNF6 exige cifrado en tránsito y almacenamiento, control de acceso y seguridad entre nodos. User/password, ACL, 2FA y API keys aparecen como posibilidades de mecanismos; no hay una lista explícita que obligue a implementarlos todos. La propuesta adopta autenticación, permisos por usuario/grupo y ACL. Se documentará esta interpretación en la especificación del equipo.
- RNF7 permite una CLI/API con resolución dinámica de ubicaciones. Un montaje FUSE o compatibilidad POSIX completa no son exigencias explícitas.
- RNF8 contiene espacios para aclaraciones, sin requisitos adicionales concretos en este PDF. No se deben inventar.
- El resultado debe ejecutarse sobre Internet usando VMs de AWS Academy o GCP académico. Docker local sirve para desarrollo y pruebas, pero no demuestra por sí solo ese requisito.
- Deben entregarse informe PDF o Word, repositorio GitHub documentado y video de **10 a 15 minutos**.

## 2. Base técnica propuesta

Lo siguiente es una **propuesta de implementación**, no una imposición del PDF ni una decisión previa del equipo. Codex deberá contrastarla con el repositorio y mantener cualquier decisión existente que satisfaga el enunciado.

| Elemento | Propuesta y finalidad |
| --- | --- |
| Implementación | Python, gRPC y Protocol Buffers; CLI y SDK propios. Verificar compatibilidad antes de fijar versiones. |
| Evolución | Un servidor modular en el hito 1; ControlNodes y DataNodes como procesos independientes a partir del hito 2. |
| Control | Tres instancias de ControlNode; estado compartido consistente mediante un clúster etcd de tres miembros. Las operaciones de mantenimiento tendrán coordinación exclusiva. |
| Datos | Al menos tres DataNodes con volúmenes independientes; un cuarto nodo para demostrar crecimiento y recuperar tres réplicas mientras otro está caído. |
| Bloques | Tamaño configurable, inicialmente 4 MiB; transferencia por fragmentos menores y memoria acotada. |
| Distribución | Elegir nodos sanos según capacidad y carga; repartir bloques diferentes y variar el nodo inicial de escritura. Guardar la ubicación real en metadatos. |
| Replicación | Objetivo de tres copias por bloque en dominios de fallo distintos. Confirmación con al menos dos copias durables verificadas, seguida de reparación hasta tres. |
| Consistencia | Bloques inmutables por versión; publicación atómica del manifiesto del archivo; lecturas de una versión consistente; control de concurrencia con bloqueos, versiones y transacciones. |
| Seguridad | TLS C/S, mTLS S/S, contraseñas con Argon2id, ACL, permisos de bloque limitados y cifrado autenticado en almacenamiento mediante una biblioteca mantenida. |
| Infraestructura | Linux y Docker; tres VMs independientes pueden alojar, cada una, un ControlNode, un DataNode y un miembro etcd. La colocación y los límites se documentan. |

La separación entre metadatos y bloques se inspira en HDFS. Su documentación también limita las actualizaciones arbitrarias de archivos; por eso esta propuesta toma la organización de componentes y define una semántica propia para RF3. [Arquitectura HDFS](https://hadoop.apache.org/docs/stable/hadoop-project-dist/hadoop-hdfs/HdfsDesign.html).

La redundancia del control merece diseño explícito: la documentación de HDFS trata la disponibilidad del NameNode con nodos redundantes y coordinación. No basta con replicar bloques. [Alta disponibilidad HDFS](https://hadoop.apache.org/docs/r3.3.5/hadoop-project-dist/hadoop-hdfs/HDFSHighAvailabilityWithQJM.html).

Para nuestro diseño, etcd aporta transacciones y operaciones con garantías de consistencia; **no convierte automáticamente al DFS completo en consistente**. La publicación de archivos, las confirmaciones de datos y las autorizaciones siguen siendo responsabilidad del proyecto. [Garantías de etcd](https://etcd.io/docs/v3.6/learning/api_guarantees/).

No se propone construir consenso desde cero, ni añadir Kafka, RabbitMQ, Kubernetes, FUSE o una interfaz web sin una necesidad concreta. Tampoco se sustituye la implementación del DFS por instalar HDFS, NFS o un almacenamiento de objetos existente.

## 3. Cómo usar los prompts

1. Abre el repositorio del proyecto en Codex y deja disponible el PDF, preferiblemente como `docs/enunciado/SI3007-262-proyecto1-dfs.docx.pdf`. Añade allí los materiales del curso que quieras que Codex consulte.
2. Envía **una vez el prompt maestro**, acompañado del prompt de la etapa 1.
3. Después envía cada etapa en orden. Comprueba sus criterios de aceptación antes de iniciar la siguiente. Codex debe corregir los fallos de la etapa activa sin pedir confirmación para cada cambio rutinario.
4. Conserva `docs/estado.md`: permite continuar en otra sesión sin perder decisiones ni confundir trabajo pendiente con terminado.
5. Si cambian el PDF o las instrucciones del profesor, actualiza primero la matriz de requisitos. Los parámetros propuestos pueden cambiar con justificación; los requisitos del enunciado deben conservarse.

| Etapa | Resultado | Relación con el cronograma oficial |
| --- | --- | --- |
| 1 | Especificación formal y arquitectura | Semana 7: especificación definitiva |
| 2 | Contratos, estructura y entorno reproducible | Preparación del hito 1 |
| 3 | RF1 y RF2 en monolito C/S | Semana 8: hito 1 |
| 4 | Bloques distribuidos y comunicaciones S/S | Semana 10: hito 2 |
| 5 | RF3, acceso parcial y concurrencia | Trabajo hacia el hito 3 |
| 6 | Replicación y recuperación de datos | Trabajo hacia el hito 3 |
| 7 | Alta disponibilidad del control y consistencia global | Trabajo hacia el hito 3 |
| 8 | Seguridad integral y cierre del hito 3 | Semana 12: hito 3 |
| 9 | Ejecución en VMs sobre Internet | Preparar desde etapas anteriores; cerrar antes de la entrega |
| 10 | Pruebas integrales, escalabilidad y resultados | Pruebas continuas; consolidación final |
| 11 | Informe, repositorio, video y auditoría | Semana 13: entrega final |

Las etapas son unidades de trabajo, no semanas adicionales. Conviene preparar el acceso académico a las VMs desde la etapa 1 y registrar evidencias desde el primer hito.

## 4. Prompt maestro

Copiar una vez al comenzar; adjuntar también el prompt de la etapa activa.

```text
Actúa como arquitecto e ingeniero de sistemas distribuidos y como colaborador
docente. Vamos a desarrollar DFSha, Proyecto 1 de SI3007/ST0263 2026-2,
siguiendo el PDF SI3007-262-proyecto1-dfs.docx.pdf y la opción 1 C/S.

OBJETIVO
Construir un DFS propio con espacio jerárquico, gestión de directorios y
archivos, transferencia completa, acceso parcial, particionamiento por
bloques, concurrencia, replicación, alta disponibilidad, consistencia,
seguridad y ubicación dinámica. El servidor se compone de servicios S/S
administrados por una organización en una red privada real o virtual.
El sistema final debe ejecutarse sobre Internet en VMs académicas.

FUENTES Y ALCANCE
- Lee el PDF completo y los archivos accesibles del proyecto pertinentes.
- Respeta las instrucciones aplicables del repositorio. No supongas que
  puedes consultar los archivos de otros chats ni sus decisiones.
- Clasifica cada decisión como requisito explícito, interpretación o
  propuesta técnica. Cita página/sección del PDF en la matriz de requisitos.
- Si una propuesta técnica contradice el PDF, corrígela. Si el texto es
  ambiguo, documenta la interpretación y la consulta al docente, y avanza
  con lo que sí esté definido sin declarar resuelta la ambigüedad.
- RF3 es obligatorio en la versión final. RNF8 no agrega contenido concreto.
- El stack sugerido es Python + gRPC/Protobuf, Docker, bloques versionados
  y etcd para coordinación/metadatos replicados. Conserva alternativas
  existentes justificadas que cumplan los mismos requisitos.
- Consulta documentación oficial al introducir dependencias y fija
  versiones compatibles. No implementes criptografía o consenso caseros.

FORMA DE TRABAJAR
1. Ejecuta solamente la etapa que te indique, resolviendo sus dependencias
   imprescindibles. No rehagas todo el proyecto ni saltes hitos.
2. Antes de editar, revisa el código y docs/estado.md. Preserva cambios ajenos.
3. Entrega implementación o documentos reales según corresponda. No te
   detengas después de proponer el plan de una etapa de implementación.
4. Prueba el comportamiento distribuido mediante procesos y conexiones
   reales. Los mocks aislados no demuestran distribución o disponibilidad.
5. Mantén trazabilidad entre requisito, diseño, código, prueba y evidencia.
6. No inventes salidas, mediciones, URLs, despliegues, commits o resultados.
   Distingue EJECUTADO, FALLIDO, PENDIENTE y BLOQUEADO POR ENTORNO.
7. Si falta una dependencia, recurso o credencial, completa todo lo posible,
   describe el bloqueo exacto y deja el procedimiento para finalizarlo.
8. Explica decisiones en español, con términos del curso y ejemplos cortos.
9. Mantén el diseño modular y suficiente para este proyecto académico.
   No añadas características que desplacen los requisitos evaluados.

REGLAS DE CORRECCIÓN
- Un archivo grande se divide entre nodos; tanto lectura como escritura
  usan varios DataNodes. El ControlNode gestiona metadatos, no centraliza
  el flujo de bytes de la versión distribuida.
- La ubicación de bloques se descubre en ejecución. La configuración
  inicial de servidores de entrada no equivale a fijar ubicaciones de archivos.
- No anuncies un archivo como completo hasta cumplir la política de
  durabilidad y publicar sus metadatos de forma atómica.
- Evita archivos parciales visibles, escrituras perdidas, versiones mezcladas,
  escrituras de titulares de locks vencidos y resurrección tras borrado.
- No declares alta disponibilidad final con un único servidor de metadatos,
  una base de datos única o réplicas que comparten un único disco/host.
- Un quórum perdido produce errores controlados; no se inventa consenso.
- Asegura identidad y permisos en ControlNode y DataNode. Diseña cifrado
  y manejo de secretos desde las primeras etapas, y verifícalos en la etapa 8.

CIERRE DE CADA ETAPA
Actualiza docs/estado.md y docs/matriz-requisitos.md con: estado real,
archivos modificados, comandos ejecutados, resultados/evidencias,
decisiones, límites y siguiente etapa. Resume qué se implementó, cómo
se verificó y qué falta. Un test no ejecutado nunca cuenta como aprobado.

Ahora ejecuta la etapa que acompaña este prompt.
```

## 5. Etapa 1: especificación formal y arquitectura

**Resultado esperado:** especificación defendible para la semana 7; todavía no implementar el sistema completo.

```text
Ejecuta la ETAPA 1 de DFSha, bajo el prompt maestro y la opción 1 C/S.

Lee el PDF completo, inventaría materiales accesibles y revisa el repositorio.
Extrae RF1-RF3, RNF1-RNF8, opción 1, comunicaciones, infraestructura,
entregables, cronograma y criterios de evaluación, citando las páginas.
No transformes ejemplos del enunciado en tecnologías obligatorias.

Redacta la definición formal del servicio: objetivo, problema, usuarios,
operaciones, límites, arquitectura y escenarios de uso/fallo. Conecta
C/S, composición S/S, RPC/gRPC, transparencia y concurrencia con el curso.
Explica por qué la opción elegida es un sistema autónomo y no P2P federado.

Propón la evolución del monolito hacia CLI/SDK, ControlNodes y DataNodes.
Define responsabilidades, estado persistente, límites de confianza y
dominios de fallo. Compara brevemente REST y gRPC; elige uno con razones.
La referencia sugerida es gRPC/Protobuf y etcd replicado para metadatos.
Documenta qué resuelve cada dependencia y qué debe implementar nuestro DFS.

Fija semánticas verificables: rutas y cd; rmdir no vacío; borrado de archivo
abierto; send/receive y put/get; open/close; read/write por offset; visibilidad
de cambios; lock/unlock, expiración y conflictos; permisos usuario/grupo.
Elige lecturas por versión fijada al abrir: una nueva apertura posterior a
un commit ve la versión vigente; un handle anterior conserva su snapshot.
Aclara qué se confirma en write y qué hace close; no dejes dos semánticas.

Propón bloques de 4 MiB, streaming acotado, factor objetivo R=3 y mínimo
de confirmación durable W=2 en nodos distintos. Explica que W=2 no es el
quórum de metadatos y no prueba consistencia por sí solo.
Define el comportamiento cuando faltan nodos, espacio o quórum y el
alcance de tolerancia a fallos. No prometas disponibilidad ilimitada.

Acuerda metas medibles del equipo, diferenciadas de exigencias del PDF:
por ejemplo archivos de 1 GiB, 10 clientes concurrentes y pruebas con
100/1.000/10.000 archivos según recursos. No presentes estos números
como resultados obtenidos. Prepara el acceso a AWS Academy o GCP.

Entrega docs/especificacion.md, docs/arquitectura.md, docs/decisiones.md,
docs/matriz-requisitos.md y docs/estado.md. Incluye diagramas de componentes,
despliegue y secuencias de lectura/escritura, y un plan para los tres hitos.

Aceptación: todos los requisitos tienen criterio observable, etapa y
evidencia prevista; no queda RF3 sin plan ni un punto único de fallo del
control sin solución prevista. Registra RNF8 como sin adiciones concretas.
```

## 6. Etapa 2: contratos, estructura y entorno

**Resultado esperado:** base reproducible y especificación de todas las comunicaciones.

```text
Ejecuta la ETAPA 2. Usa la especificación de la etapa 1.

Crea o adapta la estructura: src/dfsha/{client,control,datanode,common},
proto/, tests/, deploy/, scripts/ y docs/. Prepara dependencias compatibles,
generación reproducible de stubs, configuración de ejemplo sin secretos,
logging estructurado y comandos documentados para iniciar y probar.
Valida una llamada gRPC real y la compatibilidad del acceso a etcd v3
antes de comprometerte con un cliente de terceros.

Define contratos versionados para autenticación, espacio de nombres,
transferencia, acceso parcial, metadatos, bloques y administración de nodos.
Incluye como mínimo: Login; List/Stat/Mkdir/Rmdir/Remove; BeginUpload,
CommitUpload/AbortUpload y consulta de su estado; Open/Close/Read/Write,
Lock/Unlock; PutBlock/GetBlock; RegisterNode/Heartbeat/BlockReport;
ReplicateBlock y operaciones internas de coordinación que el diseño use.
Aclara cuáles son funciones del SDK y cuáles RPC de cada servidor.

Para cada operación especifica entrada/salida, autenticación/autorización,
precondiciones, errores, timeout, idempotencia, paginación o streaming,
persistencia y semántica de confirmación. Incluye request_id, file_id,
block_id, versión, offset, tamaño, checksum y token de lock donde apliquen.
Una misma request_id con contenido distinto debe rechazarse.

Documenta las cinco relaciones del PDF: Cliente-ControlNode,
Cliente-DataNode, ControlNode-ControlNode, ControlNode-DataNode y
DataNode-DataNode. Si el control coordina a través de etcd, representa
ControlNode-etcd-ControlNode y los peers de etcd, explicando esa mediación.
Cada nodo expone una API; el SDK oculta su ubicación al usuario.

Diseña interfaces reemplazables para metadatos, almacenamiento de bloques,
coordinación y transporte, conservando un único proceso servidor para
el primer hito. Define modelos de usuario/grupo/ACL, directorio, archivo,
manifiesto, versión de bloque, ubicación, nodo, operación y handle/lock.

Prepara TLS de desarrollo, identidad de nodos y esquema de secretos.
Configura deadlines y reintentos acotados; solo reintenta mutaciones con
idempotencia y resolución del resultado incierto.

Entrega proto/, entorno ejecutable y docs/protocolos.md con una tabla
origen/destino/operación/protocolo/seguridad/error. Prueba serialización,
errores relevantes y una RPC real. No declares funcionalidad aún no hecha.
```

Los deadlines y reintentos requieren configuración deliberada; no sustituyen el manejo de operaciones cuyo resultado quedó incierto. [Deadlines de gRPC](https://grpc.io/docs/guides/deadlines/), [reintentos de gRPC](https://grpc.io/docs/guides/retry/).

## 7. Etapa 3: monolito C/S con RF1 y RF2 completos

**Resultado esperado:** hito 1 de la semana 8.

```text
Ejecuta la ETAPA 3. Implementa un cliente y un único proceso servidor
modular que se comuniquen por red. Este hito es monolítico C/S.

Completa RF1: ls, cd, mkdir, rmdir y rm, con espacio jerárquico remoto.
Implementa una shell interactiva con directorio actual por sesión;
resuelve rutas relativas/absolutas, . y .. sin escapar del espacio permitido.
No cambies el directorio real del servidor para implementar cd.
Define errores de inexistencia, duplicados, tipo incorrecto y permisos.

Completa RF2: send/receive con alias put/get, archivos binarios, streaming,
integridad y publicación atómica. No cargues el archivo completo en RAM.
Permite múltiples clientes y conserva archivos, directorios y usuarios
tras reiniciar el servidor. Una transferencia fallida no deja un archivo
completo aparente ni destruye la versión anterior.

Incluye autenticación user/password con hash adecuado, permisos básicos
por usuario y TLS. Implementa desde ahora una interfaz de cifrado de
bloques y una implementación con biblioteca mantenida para persistir bytes
cifrados. Mantén extensibles los permisos para grupos/ACL de la etapa 8.
El almacenamiento de este hito es local al servidor: documenta ese límite.

Ejecuta pruebas cliente-servidor reales: árbol de directorios y cd,
put/get de texto y binario comparando SHA-256, archivo vacío, archivo
mayor que el búfer, rm/rmdir, usuario ajeno rechazado, transferencia
interrumpida y persistencia después de reiniciar. Comprueba que el
cliente no necesita un volumen compartido con el servidor.

Entrega demo reproducible y docs/hito1.md con comandos, resultados y
límites. Conserva una referencia identificable de esta versión en Git
según el flujo existente del repositorio. No adelantes la distribución
antes de tener RF1 y RF2 completos y verificados.
```

## 8. Etapa 4: distribución por bloques y comunicaciones S/S

**Resultado esperado:** hito 2 de la semana 10, con lectura y escritura realmente distribuidas.

```text
Ejecuta la ETAPA 4 a partir del monolito verificado.

Separa ControlNode y DataNode en procesos desplegables independientes,
reutilizando la lógica existente. Conserva la CLI y el SDK. Inicia un
ControlNode y al menos tres DataNodes con volúmenes separados.
Documenta que la alta disponibilidad del control se completa en etapa 7.

Implementa registro dinámico de DataNodes, heartbeats, inventario de
bloques y selección de nodos sanos según capacidad/carga. El ControlNode
mantiene rutas, tamaños, versiones, orden de bloques, checksums y sus
ubicaciones. Nunca deduzcas ubicaciones antiguas recalculando un hash
sobre una lista de nodos que pudo cambiar.

Divide archivos en bloques configurables, inicialmente 4 MiB. put/send
obtiene un plan del ControlNode y transmite bloques a diferentes DataNodes
con concurrencia limitada. get/receive consulta un manifiesto y obtiene
bloques desde varios DataNodes, verifica integridad y reconstruye el orden.
Usa fragmentos gRPC menores que el bloque y aplica backpressure.
El ControlNode no recibe todo el contenido para redistribuirlo.

Publica el archivo mediante commit de metadatos cuando todos sus bloques
estén confirmados según la política vigente del hito. Mantén estado de
operación, abort y limpieza de bloques provisionales. Protege cada acceso
a bloque con autorización emitida por el control o comprobación equivalente;
conocer un block_id no debe permitir leerlo o sustituirlo.

Las ubicaciones se resuelven al operar. Los nodos informan endpoints
alcanzables por el cliente: distingue direcciones internas de las de acceso
C/S y evita devolver localhost o nombres exclusivos de Docker fuera de él.

Demuestra con un archivo de varios bloques, preferiblemente 64 MiB o más:
bytes escritos y leídos en al menos dos DataNodes, SHA-256 final idéntico,
concurrencia acotada y ausencia de volumen compartido entre nodos.
Añade un DataNode sin editar el cliente y verifica que recibe bloques.
Prueba también archivo vacío, menor que un bloque, tamaño exacto y último
bloque parcial, nodo que no responde y transferencia abortada.

Actualiza diagramas, protocolos y docs/hito2.md. Si usas temporalmente
una copia por bloque, marca la falta de tolerancia a su pérdida como
pendiente de etapa 6; no presentes ese modo como cumplimiento de RNF2.
```

## 9. Etapa 5: RF3, acceso parcial y concurrencia

**Resultado esperado:** API real de acceso al contenido, con semántica consistente y comprobable.

```text
Ejecuta la ETAPA 5: implementa RF3 sin romper RF1/RF2.

Expón open(path, mode), close(handle), read(handle, offset, length),
write(handle, offset, data), lock y unlock mediante SDK y contratos
documentados. Define modos, EOF, offsets inválidos, crecimiento y
escritura más allá de EOF. Si soportas huecos, su lectura devuelve ceros;
si no, recházalos explícitamente. No prometas POSIX completo.

El SDK coordina permisos, versiones y ubicaciones con el ControlNode;
los bytes de read/write viajan directamente entre cliente y DataNodes.
read accede únicamente a los bloques del rango necesario. write modifica
solo bloques afectados usando copy-on-write: cada versión de bloque es
inmutable y un manifiesto publicado define una versión completa del archivo.
Cada write exitoso publica atómicamente su cambio; close libera recursos.
No devuelvas éxito de write si solo guardaste bytes en un búfer del cliente.
Un lector fija una versión al abrir; una nueva apertura después del commit
ve la versión vigente. El escritor actualiza su handle tras su propio commit.

Implementa locks con dueño, alcance, vencimiento y token de generación.
Permite lectores concurrentes y escritores sobre bloques distintos del mismo
archivo. Serializa conflictos sobre bloques compartidos. Adquiere múltiples
locks en orden determinista y limita la espera para evitar interbloqueos.
Integra lock explícito con los locks internos: deben usar la misma autoridad.
La autoridad inicial puede vivir en el ControlNode único, detrás de una
interfaz que se sustituirá por coordinación distribuida en etapa 7.

Evita actualizaciones perdidas: antes de publicar valida versiones de los
bloques afectados, vigencia de locks, existencia del archivo y revisión del
manifiesto. Si otro escritor cambió bloques distintos, combina los cambios
con el manifiesto vigente y reintenta de forma acotada. Un conflicto real
debe devolverse como tal, nunca sobrescribirse silenciosamente.

Conserva bloques de versiones usadas por handles abiertos mientras su
lease sea válido. Define expiración/renovación de handles y tombstones
de borrado para impedir commits sobre un archivo eliminado.

Prueba con al menos dos clientes: lecturas concurrentes; escrituras en
bloques distintos sin pérdida de cambios; escrituras solapadas; lector
abierto antes y después de un commit; operación que cruza límite de bloque;
write interrumpido; lock vencido; cierre del cliente y rm con archivo abierto.
Compara bytes esperados y demuestra que una actualización pequeña no
transfiere otra vez el archivo completo. Documenta semántica y límites.
```

## 10. Etapa 6: replicación y recuperación de datos

**Resultado esperado:** datos redundantes, recuperables y consistentes después de fallos.

```text
Ejecuta la ETAPA 6 sobre el DFS con acceso parcial.

Implementa replicación por versión de bloque con factor objetivo R=3,
en DataNodes de dominios de fallo distintos. Coloca bloques y sus nodos
iniciales de escritura de modo que un archivo utilice varios DataNodes.
Implementa transferencia DataNode-DataNode para replicación/reparación,
con identidad autenticada y validación de versión, tamaño y checksum.

Fija el protocolo de confirmación: cada bloque nuevo requiere al menos
W=2 copias durables verificadas en nodos distintos; el ControlNode valida
confirmaciones auténticas de los DataNodes, no un número afirmado por el
cliente. ACK durable implica datos y metadatos locales persistidos según
el mecanismo documentado. La tercera copia se completa y reconcilia.
Un commit publica el manifiesto solo después de cumplir estas condiciones
para todos los bloques nuevos y de validar los controles de concurrencia.

Mantén un registro idempotente de operación y resultado. Tras perder una
respuesta, el cliente consulta el estado antes de repetir una mutación.
Maneja caídas antes/después del ACK y antes/después de publicar metadatos.
No dejes que un timeout convierta dos intentos en dos escrituras distintas.

Implementa detección de nodos no disponibles, selección de otra réplica al
leer, detección de corrupción, re-replicación y reconciliación de inventarios.
Repara exclusivamente versiones válidas referenciadas por metadatos;
las versiones antiguas o provisionales no sustituyen a las confirmadas.
Coordina tareas de mantenimiento con la interfaz que tendrá autoridad
distribuida en etapa 7. Hazlas idempotentes.

Con solo tres DataNodes y uno caído no puedes mantener tres copias en
nodos vivos: reporta estado degradado y restaura R=3 cuando vuelva o
se añada un cuarto nodo. Si no puedes lograr W=2 para un bloque nuevo,
rechaza la escritura; no reduzcas la política silenciosamente.

Implementa limpieza de provisionales y borrado diferido seguro de bloques
sin referencias, respetando snapshots abiertos, uploads activos, tombstones
y trabajos de reparación. La replicación no reemplaza una política de backup.

Prueba caída de un nodo durante put y get, pérdida de respuesta de commit,
bloque corrupto, reinicio, regreso con inventario obsoleto y reparación
hacia un cuarto nodo. Verifica archivos confirmados, hashes, número real de
copias y ausencia de resurrección tras rm. Registra tiempos de detección y
recuperación medidos, junto con el estado normal/degradado/no disponible.
```

## 11. Etapa 7: disponibilidad del control y consistencia global

**Resultado esperado:** el control deja de depender de un servidor o disco único.

```text
Ejecuta la ETAPA 7. Elimina el punto único de fallo del control.

Despliega tres ControlNodes y un clúster etcd de tres miembros con
volúmenes independientes. En cloud, distribuye sus miembros entre VMs
distintas; tres contenedores en una VM solo prueban fallos de proceso.
Usa la API v3 oficial y dependencias verificadas. etcd contiene metadatos
y coordinación, no los bytes de los archivos.

Migra todo estado que deba sobrevivir a un ControlNode: espacio de nombres,
usuarios/grupos/ACL, manifiestos, registro de nodos y réplicas, request_id
y resultado de operaciones, handles/locks vigentes y tareas necesarias.
Elimina fuentes de verdad ocultas en memoria local o SQLite individual.
Prueba la migración preservando archivos y permisos del hito anterior.

Implementa publicación atómica usando transacciones y compare-and-swap.
Prepara estructuras inmutables y cambia una referencia raíz al confirmar.
Pagina listados/manifiestos y respeta límites de tamaño y número de
operaciones de etcd/RPC: no guardes un manifiesto ilimitado en una clave.
Define límites por write y manejo de conflictos sin perder cambios ajenos.

Los locks usan leases y fencing: valida en la transacción de publicación
la propiedad vigente, el token de generación y las versiones esperadas.
Un proceso cuyo lease expiró no puede publicar aunque siga ejecutándose.
La exclusión de mantenimiento también debe ser distribuida y los comandos
obsoletos no deben borrar o reemplazar datos que vuelvan a estar referenciados.

El SDK usa varios endpoints de ControlNode y conmutación automática.
Todos comparten la autoridad consistente; documenta la coordinación
ControlNode-etcd-ControlNode y la replicación entre miembros de etcd.
No uses elecciones independientes hechas con heartbeats que permitan
dos autoridades incompatibles. No agregues un balanceador único sin
analizar su impacto en la disponibilidad del acceso.

Demuestra tolerancia a la pérdida de un ControlNode y de un miembro etcd.
Con pérdida de mayoría, no confirmes mutaciones: devuelve error acotado.
Documenta si lecturas de snapshots ya abiertos pueden continuar y evita
presentar una caché potencialmente vieja como consulta consistente actual.

Prueba failover durante escritura y entre commit y respuesta; proceso
pausado que reanuda con lock vencido; dos escritores con distintos
ControlNodes; partición de red, pérdida/restauración de quórum y reinicio
completo conservando volúmenes. Comprueba archivos, ACL, versiones,
request_id y ausencia de escrituras perdidas o autoridades divergentes.
Documenta backup/restauración de metadatos y su relación con bloques y claves.
```

Los leases por sí solos no impiden que un cliente obsoleto siga actuando; deben combinarse con validaciones de versión al modificar el recurso protegido. Esa es la razón del control por generación en esta propuesta. [Locks y leases en etcd](https://etcd.io/docs/v3.5/learning/why/).

## 12. Etapa 8: seguridad integral y cierre del hito 3

**Resultado esperado:** disponibilidad, replicación, consistencia y seguridad verificadas para la semana 12.

```text
Ejecuta la ETAPA 8. Completa y verifica RNF6 sobre la arquitectura con HA.

Escribe un modelo de amenazas acotado: usuario sin autenticación, usuario
que intenta acceder a archivos ajenos, nodo no autorizado, interceptación,
alteración de bloques y acceso a discos/copias sin sus claves. Explica los
límites ante compromiso total de un nodo legítimo con acceso a claves.

Implementa TLS con verificación de CA y nombre del servidor en C/S;
mTLS y autorización por rol en S/S, incluyendo ControlNode-DataNode,
DataNode-DataNode, acceso a etcd y replicación entre peers de etcd.
Un certificado válido no debe conceder todas las operaciones internas.
Separa APIs de cliente de APIs de administración/registro/replicación.

Completa usuarios, grupos y ACL sobre archivos/directorios: propietario,
lectura/escritura y recorrido de directorios. Revisa permisos en cada
operación sensible, incluido acceso directo a bloques. Usa contraseñas
con Argon2id mediante biblioteca; sesiones/tokens con caducidad y cierre.
Implementa administración mínima reproducible de usuarios/grupos/ACL.
Define y prueba el efecto de revocar permisos sobre handles y tokens.

Los permisos de acceso a DataNode deben limitar sujeto, operación,
archivo/bloque, versión y vigencia. Rechaza tokens manipulados, vencidos
o reutilizados para recursos/operaciones distintos. Protege registro de
nodos para que un cliente no pueda incorporarse como DataNode confiable.

Cifra bloques persistidos con una biblioteca de cifrado autenticado,
por ejemplo AES-GCM. Garantiza unicidad de nonce por clave; asocia
identificadores y versión mediante datos autenticados cuando corresponda.
Define custodia, distribución, identificador de clave, rotación y recuperación.
Resuelve explícitamente cómo una réplica puede descifrar tras un failover:
copiar ciphertext sin disponer de las claves necesarias no da disponibilidad.

Protege temporales, metadatos persistidos, snapshots y backups mediante
cifrado de aplicación o volúmenes cifrados, según la plataforma. TLS de
etcd no implica cifrado de sus archivos en disco. Conserva las claves fuera
del repositorio y del volumen de datos que protegen; no las muestres en logs.
Evita que su recuperación dependa de un único servidor en ejecución.

Prueba usuario/grupo autorizado y ajeno; recorrido no permitido;
block_id conocido sin permiso; token inválido; nodo falso; certificado no
confiable; bloque alterado; y lectura tras reiniciar/reemplazar un nodo con
el material de claves correcto. Verifica configuración real del cifrado
en reposo y tránsito; buscar texto con strings no basta para demostrarlo.

Entrega docs/seguridad.md y docs/hito3.md, con evidencias de etapas 5-8.
2FA y API keys adicionales son extensiones, salvo aclaración del docente.
No cierres el hito si HA, consistencia o cifrado solo están descritos.
```

gRPC admite credenciales de transporte y de llamada; etcd permite autenticación por certificados tanto para clientes como para peers. [Autenticación de gRPC](https://grpc.io/docs/guides/auth/), [seguridad de transporte de etcd](https://etcd.io/docs/v3.6/op-guide/security/).

Argon2id es una opción recomendada para proteger contraseñas. AES-GCM requiere respetar la unicidad de nonce bajo una misma clave; debe usarse a través de una biblioteca y con gestión explícita de claves. [Contraseñas: OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [cifrado autenticado: cryptography](https://cryptography.io/en/stable/hazmat/primitives/aead/).

## 13. Etapa 9: despliegue académico sobre Internet

**Resultado esperado:** ejecución en VMs independientes y acceso de un cliente externo.

```text
Ejecuta la ETAPA 9 con AWS Academy o GCP académico según el entorno real.
La preparación de cuentas/capacidad debió comenzar en la etapa 1.

Diseña y realiza un despliegue reproducible en VMs Linux. Usa al menos
tres VMs independientes para probar pérdida de un host. Una configuración
académica posible aloja por VM un ControlNode, un DataNode y un miembro
etcd, con recursos y volúmenes propios. Añade capacidad temporal para
el cuarto DataNode y la prueba de expansión/reparación si está disponible.
Aclara que colocalizar roles correlaciona sus fallos y compite por recursos.

Mantén comunicaciones S/S por direcciones privadas en una VPC del
proveedor elegido. Define cómo entra el cliente desde Internet: endpoints
C/S autorizados con TLS, o acceso por VPN. Elige una modalidad y termina
su configuración. Si los DataNodes solo tienen direcciones privadas,
el cliente debe tener una ruta real a ellas por la modalidad elegida.
No devuelvas endpoints inalcanzables ni expongas APIs internas por accidente.

El SDK debe conservar varios puntos de entrada de control y resolver
DataNodes dinámicamente. Si añades VPN, proxy o balanceador, resuelve
su redundancia o acceso alternativo: no introduzcas un punto único de
fallo que invalide la disponibilidad demostrada desde el cliente.

Entrega inventario, diagrama de VMs/red, tabla de puertos y flujos,
reglas de acceso, persistencia, certificados/secretos, procedimientos
de arranque, actualización, recuperación y apagado. Usa scripts,
cloud-init, Ansible o IaC según lo que el entorno permita; selecciona
una vía sencilla y reproducible. Docker Compose de un host no distribuye
por sí mismo contenedores entre las VMs: configura cada host explícitamente.

Desde una máquina cliente externa ejecuta RF1, RF2 y RF3; demuestra que
un archivo usa varios DataNodes. Detén un host y repite operaciones que
deban seguir disponibles. Conserva evidencia de hosts distintos, versión
del código, tiempos, comandos y resultados sin publicar secretos.

Si falta acceso/capacidad real, termina scripts, inventario parametrizado
y guía de ejecución; marca la validación cloud como BLOQUEADA POR ENTORNO
y señala lo necesario para completarla. No conviertas una prueba local
en evidencia sobre Internet ni inventes direcciones o recursos creados.
Entrega docs/despliegue.md con el estado real de cada verificación.
```

En AWS, una VPC permite organizar la red virtual, subredes y conectividad. La combinación concreta de exposición C/S y tráfico S/S privado es una decisión del proyecto que debe quedar configurada y probada. [Documentación de Amazon VPC](https://docs.aws.amazon.com/vpc/latest/userguide/what-is-amazon-vpc.html).

## 14. Etapa 10: pruebas integrales, rendimiento y escalabilidad

**Resultado esperado:** evidencias medibles para todos los requisitos y material válido para el informe.

```text
Ejecuta la ETAPA 10. Consolida las pruebas existentes y agrega las que
falten por requisito; no repitas pruebas sin una razón concreta.

Construye una matriz ejecutable con caso, requisito, precondición,
comando, resultado esperado, resultado real y ruta de evidencia.
Ejecuta pruebas integrales con procesos/conexiones reales y datos de
prueba generados por scripts. Separa pruebas locales y cloud.

Verifica al menos:
- RF1: árbol de directorios, cd, errores, permisos y persistencia.
- RF2: archivos vacíos, binarios, pequeños y grandes; integridad extremo
  a extremo, aborto y reintento idempotente de operaciones inciertas.
- RF3: offsets, cruces de bloque, acceso parcial, locks, versiones,
  concurrencia en bloques distintos y conflictos sobre el mismo bloque.
- Distribución: un archivo grande escrito y leído en varios DataNodes,
  sin pasar todos los bytes por el ControlNode y sin volumen compartido.
- Disponibilidad: caída de DataNode, ControlNode, miembro etcd y host;
  pérdida de quórum, corrupción, reinicios y restauración de réplicas.
- Seguridad: pruebas positivas/negativas de usuario, grupo, ACL,
  acceso directo a bloques, certificados, cifrado y recuperación de claves.
- Transparencia: cambio/fallo/incorporación de nodos sin modificar rutas
  lógicas de archivos ni editar una tabla de ubicaciones en el cliente.

Mide escalabilidad en sus tres dimensiones: usuarios concurrentes,
número de archivos y tamaño de archivo. Usa una batería ajustada a los
recursos: 1/5/10 clientes; 100/1.000/10.000 archivos; y 1 MiB/64 MiB/1 GiB.
Los valores son metas propuestas, no imposiciones del PDF. Registra
explícitamente niveles que no se puedan ejecutar.

Compara distribución serial/paralela y crecimiento de tres a cuatro
DataNodes. Mantén constantes replicación, cifrado, carga y recursos al
comparar; si cambian, declara el factor de confusión. No uses menor
durabilidad o seguridad para atribuir al diseño una mejora de rendimiento.

Registra throughput útil, latencia p50/p95, errores, memoria pico, CPU,
tráfico por nodo, distribución de bloques y tiempos de detección,
failover y reparación. Distingue bytes útiles de tráfico de réplicas.
Controla caché, repeticiones y versión/configuración de cada corrida.

Analiza límites: memoria acotada, paginación de metadatos, presión de
etcd, capacidad libre, colocalización y carga del ControlNode. Añadir
servidores no prueba por sí mismo escalabilidad ni garantiza speedup.
Compara con las metas de la etapa 1, corrige incumplimientos y explica
resultados adversos. Nunca presentes proyecciones como medidas reales.

Entrega scripts reproducibles, datos brutos CSV/JSON, gráficas derivadas
de esos datos y docs/pruebas-resultados.md. Actualiza la matriz de
requisitos con evidencia concreta; conserva como pendientes los casos
que no se hayan ejecutado o no hayan pasado.
```

## 15. Etapa 11: entregables y auditoría final

**Resultado esperado:** paquete completo de entrega para la semana 13.

```text
Ejecuta la ETAPA 11. Audita el resultado contra el PDF original completo,
las aclaraciones registradas del docente y docs/matriz-requisitos.md.

Revisa cada RF/RNF y requisito transversal usando diseño, implementación,
prueba y evidencia real. Corrige los vacíos que puedas resolver. No declares
cumplimiento completo si faltan pruebas, despliegue, video o funcionalidad.
RNF8 se registra como sin adiciones si no existe aclaración posterior.

INFORME TÉCNICO
Genera un informe final PDF o Word y conserva su fuente editable. Incluye:
objetivo y marco teórico breve; servicio y problema; requisitos;
arquitectura C/S/S2S y diagramas; protocolos/APIs; algoritmos de
particionamiento, distribución y replicación; consistencia y concurrencia;
seguridad; entorno nativo/Docker y despliegue IaaS; metodología de pruebas,
resultados y análisis; limitaciones y referencias. Distingue lo implementado
de mejoras futuras. Verifica visualmente tablas, figuras y páginas del
archivo exportado. Un Markdown sin exportar no reemplaza este entregable.

REPOSITORIO GITHUB
Completa README con requisitos previos, instalación, compilación de
contratos, arranque local/cloud, configuración sin secretos, ejemplos
CLI/SDK, pruebas, arquitectura, estructura y solución de errores comunes.
Incluye dependencias fijadas, scripts y referencias de los hitos. Verifica
la reproducción desde un checkout limpio. Comprueba el remoto GitHub y
que los archivos necesarios estén efectivamente disponibles según el
flujo autorizado del repositorio. Si no hay acceso al remoto, conserva
los cambios y documenta exactamente lo pendiente; no inventes una URL.

VIDEO DE 10 A 15 MINUTOS
Prepara un guion y una demo determinista de aproximadamente 13 minutos:
00:00-01:00 objetivo y alcance; 01:00-03:00 arquitectura y comunicaciones;
03:00-05:00 RF1/RF2 y distribución de bloques;
05:00-07:00 RF3 y concurrencia; 07:00-10:00 fallo y recuperación;
10:00-11:30 seguridad; 11:30-13:00 despliegue, resultados y límites.
Utiliza archivos/cuentas de demo y comandos comprobados. El video puede
mostrar ejecución en vivo o simulada, como permite el PDF; identifica cuál
es y no presentes simulación como evidencia de despliegue real.
Genera la grabación si el entorno lo permite; de lo contrario entrega
guion, comandos y lista de tomas, dejando la grabación como pendiente
explícito del equipo. Un guion no equivale al video entregado.

AUDITORÍA DE LA RÚBRICA
Evalúa por nombre: definición/diseño 15%; comunicaciones 15%; diseño
para escalabilidad 15%; alta disponibilidad 15%; replicación/consistencia
15%; seguridad 15%; video/informe final 10%. No inventes subcriterios
donde el PDF contiene puntos suspensivos ni garantices una calificación.

Entrega docs/auditoria-final.md con enlaces reales a artefactos/evidencias,
tabla CUMPLE/PARCIAL/PENDIENTE por requisito y pendientes concretos.
Presenta el informe exportado, repositorio y video con su estado real.
```

## 16. Matriz de cobertura del enunciado

Esta tabla verifica la cobertura de **los prompts**, no certifica una implementación que todavía no se ha realizado. Las etiquetas de requisitos se conservan como aparecen en el PDF; las filas adicionales representan obligaciones de sus otras secciones.

| Requisito | Fuente | Etapas | Evidencia que debe producir el proyecto |
| --- | --- | --- | --- |
| RF1: gestión jerárquica | p. 1 | 3, 4, 8, 10 | CLI con ls/cd/mkdir/rmdir/rm, errores, permisos y persistencia. |
| RF2: transferencia | p. 1 | 3, 4, 6, 10 | send/receive o put/get, archivos completos, hashes y transferencias interrumpidas. |
| RF3: acceso | p. 1 | 5, 7, 10 | API por offset, open/close/read/write/lock y prueba de actualización parcial. |
| RNF1: escalabilidad | pp. 1-2 | 1, 4, 7, 9, 10 | Variación de usuarios, cantidad/tamaño de archivos y nodos; análisis de límites. |
| RNF2: disponibilidad | p. 2 | 6, 7, 9, 10 | Pérdida de nodo de datos, control y host; recuperación sin perder archivos confirmados dentro del modelo de fallos. |
| RNF3: consistencia | p. 2 | 5, 6, 7, 10 | Commits atómicos, versiones, locks y fallos/particiones sin actualizaciones perdidas. |
| RNF4: particionamiento | p. 2 | 4, 6, 10 | Bloques de un mismo archivo en nodos distintos y tráfico de lectura/escritura distribuido. |
| RNF5: rendimiento/concurrencia | p. 2 | 4, 5, 10 | Clientes concurrentes, acceso dentro de un archivo, mediciones y memoria acotada. |
| RNF6: seguridad | p. 2 | 2-10, cierre en 8 | TLS/mTLS, identidad, ACL usuario/grupo, cifrado en reposo, claves y pruebas negativas. |
| RNF7: transparencia | p. 2 | 3, 4, 7, 9, 10 | Rutas lógicas y resolución dinámica ante crecimiento, cambio y caída de nodos. |
| RNF8: aclaraciones | p. 2 | 1, 11 | Registro de cambios; sin nuevas exigencias si no hay texto adicional. |
| Opción 1 C/S y composición S/S | p. 2 | 1, 4, 7, 9 | Servicio autónomo; separación de roles; red privada interna e interfaces C/S. |
| Definición formal y arquitectura | p. 4 | 1, 11 | Especificación del equipo, decisiones y diagramas coherentes con el código. |
| Comunicaciones sobre Internet y cinco relaciones | pp. 4-5 | 2, 4, 6, 7, 9 | Protocolos/APIs, flujos directos o mediados, errores y pruebas en red. |
| VMs AWS Academy/GCP; ejecución nativa/Docker; API por nodo | p. 5 | 2, 4, 7, 9 | Inventario, despliegue reproducible y ejecución en hosts independientes. |
| Informe PDF o Word | p. 5 | 11 | Documento exportado, revisado, con las siete áreas de contenido requeridas. |
| Código en GitHub documentado | pp. 5, 7 | 2-11 | Repositorio real, README y reproducción desde checkout limpio. |
| Video de 10-15 minutos | pp. 5, 7 | 11 | Grabación final con explicación y demostración; guion como preparación. |
| Especificación e hitos 1/2/3 y entrega final | p. 6 | 1 / 3 / 4 / 8 / 11 | Evidencia conservada por hito y correspondencia con semanas 7/8/10/12/13. |
| Rúbrica completa: 100% | pp. 6-7 | 10, 11 | Auditoría de los seis criterios de 15% y del criterio final de 10%. |

## 17. Prompt para retomar una sesión

Si continúas en una sesión nueva, vuelve a aportar el prompt maestro y usa este bloque con el número de etapa correspondiente:

```text
Retoma DFSha opción 1 C/S. Lee las instrucciones del repositorio,
docs/estado.md, docs/matriz-requisitos.md y las decisiones registradas.
Comprueba el estado real del código y las evidencias antes de asumir
que una etapa terminó. Conserva los cambios existentes.

Continúa la etapa [NÚMERO], cuyo prompt adjunto a continuación.
Resuelve sus pendientes y dependencias indispensables; no reinicies
el proyecto ni avances a otras etapas sin terminar sus criterios.
No marques pruebas o entregables como realizados sin evidencia.
```

## 18. Comprobación rápida antes de entregar

- ¿RF1/RF2 funcionan y quedó evidencia del monolito del hito 1?
- ¿RF3 modifica y lee rangos, con concurrencia y locks comprobables?
- ¿Un archivo grande se escribe y lee mediante varios DataNodes?
- ¿La pérdida de un host deja disponibles las operaciones previstas y los archivos confirmados?
- ¿Control, metadatos, réplicas, claves y acceso al servicio tienen una estrategia coherente de redundancia?
- ¿Se rechazan publicaciones obsoletas y escrituras sin las confirmaciones necesarias?
- ¿Funcionan cifrado, autenticación, permisos usuario/grupo y seguridad entre nodos?
- ¿Las ubicaciones se resuelven dinámicamente sin cambiarlas a mano en el cliente?
- ¿Hay evidencia de ejecución sobre Internet en VMs académicas?
- ¿El informe está exportado, GitHub es reproducible y el video real dura 10-15 minutos?

Si alguna respuesta depende de una función futura, una prueba no ejecutada o un archivo aún no generado, se conserva como pendiente en la auditoría final.
