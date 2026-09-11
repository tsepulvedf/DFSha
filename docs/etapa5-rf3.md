# Etapa 5: acceso parcial y concurrencia

Estado al 2026-09-11: **E5 COMPLETA en Windows local**, con R=1/W=1.
Las pruebas de este cierre acreditan RF3; los resultados históricos de H2 se conservan separados.
Fuente: PDF original de siete páginas, leído íntegramente el 10 de septiembre de 2026
(SHA-256 `0ec8cc4cf92f9cf9345d5cf147d096a9cc74f78146aabce823d3890a31b446bf`).
RF3 (p. 1) exige acceso; las reglas siguientes concretan decisiones del equipo y
el prompt actualizado, no texto adicional atribuido al docente. Q01–Q07 siguen pendientes.

## Decisiones de implementación

- D36: SQLite sigue siendo la autoridad única. Una autoridad de leases detrás de
  una interfaz sustituible decide locks y fencing dentro de transacciones breves.
  La preparación y los streams ocurren fuera de esas transacciones.
- D37: la identidad estable del servicio autentica sesiones y resultados; una
  época de arranque independiente invalida handles y locks. Los vencimientos de
  RF3 se deciden con tiempo monotónico del control, nunca con el reloj del cliente.
- D38: `r`, `r+`, `w`, `w+`, `x`, `x+`; `w` publica truncado al abrir. Snapshots
  fijados, pin atómico, avance exclusivo del handle escritor tras su commit.
  Truncado y overwrite aumentan content_epoch; un parche aumenta file_version.
- D39: write sobrescribe hasta 16 MiB atómicos; no inserta, no crea huecos y no
  se divide silenciosamente. Crecimiento requiere exclusión de tamaño y base
  todavía vigente. Bloques distintos se fusionan sobre el manifiesto actual;
  cambios incompatibles en el mismo bloque producen conflicto.
- D40: PatchBlock transmite solamente el delta. El DataNode autentica la base,
  calcula el resultado y crea otro objeto cifrado inmutable. Reserva el objeto
  completo, no solamente el delta. Fragmentos de transporte: 256 KiB.
- D41: lecturas parciales transportan únicamente el rango autorizado. Un hash
  de bloque completo se compara sólo al recibir ese bloque completo. AES-GCM
  se valida dentro del DataNode antes de exponer bytes; TLS protege el rango.
  Tras un parche no se inventa el SHA-256 del archivo completo: el manifiesto
  contiene los hashes autoritativos de sus bloques y su propio hash.
- D42: locks parciales exclusivos redondeados a bloques, máximo 16 MiB; ámbito
  completo explícito. Dueño session/handle, fencing por adquisición y arranque.
  Lease inicial 30 s (renovación 10), handle 120 s (renovación 40), máximo 24 h.
  El commit verifica propiedad, generación y vigencia dentro de su transacción.
- D43: R=1/W=1; control único, tres DataNodes de laboratorio. Replicación
  automática, HA y seguridad integral siguen en etapas 6, 7 y 8.
- D44: continuidad H2 ante respuestas de heartbeat perdidas. El DN conserva su
  registro y aumenta la secuencia tras errores transitorios; una respuesta
  VERSION_CONFLICT/NOT_FOUND obliga a reconciliar. La colocación nueva exige
  READY y métricas frescas. Una ubicación ya confirmada o reservada puede seguir
  usándose en SUSPECT, con autorización online y generación válida; STARTING y
  UNAVAILABLE siguen rechazados. No se crean copias ni se cambia de versión para
  ocultar un fallo. Dos mediciones fallidas y la corrección se conservan como evidencia.

## Publicación implementada y criterio de aceptación

```mermaid
sequenceDiagram
    participant C as Cliente
    participant CN as Control / SQLite
    participant DN as DataNode
    C->>CN: BeginWrite(base, rango, intención)
    CN->>CN: Validar handle, reservar y adquirir locks
    CN-->>C: Plan, versiones candidatas y fencing
    C->>DN: PatchBlock(delta autorizado)
    DN->>DN: Autenticar base, COW, cifrar, fsync y recibo
    DN->>CN: Confirmación durable autenticada
    C->>CN: CommitWrite(misma operación)
    CN->>CN: BEGIN IMMEDIATE; verificar fencing, tombstone, ACL y bases
    CN->>CN: Fusionar sobre manifiesto vigente; publicar resultado y handle; COMMIT
    CN-->>C: Resultado confirmado
```

La prueba con dos barreras ya ejecutó la preparación de A1 y B1 antes de publicar:
desde [A0,B0] los commits producen [A1,B0] y [A1,B1]. La regresión final y la
medición están aprobadas; los resultados y sus límites se registran abajo.

## Resultados del cierre

[Verificación final](evidencias/etapa5/20260911T045117Z/result.json),
[casos y propiedades XML](evidencias/etapa5/20260911T045117Z/pytest.xml):
**114 aprobadas en 647,27 s**, sin fallos, errores ni omisiones. Comprende la
regresión disponible H1/H2, contratos, seguridad y doce casos RF3 contando los
tres perfiles parametrizados. No se suman las ejecuciones anteriores.

| Comprobación | Resultado ejecutado |
| --- | --- |
| Modos y lecturas | r/r+/w/w+/x/x+, a rechazado, permisos, EOF/cero, rangos inválidos y cruces de bloque. |
| Writes y snapshots | Delta máximo 16 MiB, huecos/overflow rechazados, crecimiento, bytes exteriores conservados, avance exclusivo del writer y lector antiguo estable. |
| Concurrencia | Dos clientes preparan con barreras antes de cualquier commit; [A1,B1] final. Conflictos del mismo bloque, base antigua, tamaño y locks completos/parciales. |
| Fencing y recuperación | A pausado expira, B publica, A no publica ni libera B; renovación de fences; reinicio invalida handles y conserva resultados. |
| Atomicidad y borrado | Aborto multibloque invisible, fallo antes de publicar, respuesta perdida tras commit, idempotencia/mismatch, rm/recreación y overwrite con snapshots. |
| Red y seguridad | CLI/shell y SDK reales; delta directo, rango autorizado, write-only, revocación, corrupción, stream incompleto, falta de espacio y fuente única caída. |
| Base remota | Copia S/S autorizada por capacidad, parche en destino y lectura con origen detenido; no política automática de replicación. |
| Perfiles y reloj | Cruces con B=4/64/128 MiB. Caso aislado SQLite confirma que hints de reloj civil no vencen pins/reservas monotónicas; no cuenta como prueba de red. |
| Toolchain y paquete | pip check, generación/importación de 34 módulos, 56 RPC; wheel instalado y smoke RF3 de 8 MiB desde site-packages. |

[Medición final](evidencias/etapa5/20260911T045117Z/measurement.json): archivo de
536870912 bytes (512 MiB), B=67108864, fragmentos=262144, R=1/W=1, tres sesiones
SDK en un proceso cliente y cuatro procesos servidor independientes. Un parche
de 4096 bytes tardó **3,734 s**. Contadores de contenido de ese parche aislado:

| node_id | Cliente→DN | DN→cliente | DN→DN enviado / recibido |
| --- | ---: | ---: | ---: |
| 637ed799-99f2-48c8-9f1f-b316ceff97fb | 0 | 0 | 0 / 0 |
| 533fd599-3fad-404b-8c29-75ace0416d55 | 0 | 0 | 0 / 0 |
| 15319505-38c3-40b7-8b41-aa3d00d2d73b | 4096 | 0 | 0 / 0 |

Control: **cero bytes de contenido**, con tráfico real de metadatos y autorización.
En esta medición la base era local. El DN procesó internamente 268435456 bytes
de base (cuatro pasadas), 134217728 de resultado (dos pasadas) y almacenó
67114395 bytes cifrados nuevos. Ese coste no es tráfico cliente ni tamaño del delta.
La copia S/S de base remota se acredita en otro caso del XML, no en esta tabla.

SHA-256 original:
`c047731a3c134f3d34286d608e9c173027d50f43ab9d2064f3c360939977e908`.
SHA-256 esperado y descargado tras el parche aislado:
`33dd21353ac79226f9ea36aa5bf30804a4226533bdc6fcd626ebd0e0661abe9d`.
Después, dos preparaciones concurrentes publicaron versiones **3 y 4** y una
nueva lectura confirmó ambos cambios (`concurrent_patches_verified=true`).

Máximos residentes medidos por proceso: cliente **66637824 bytes (63,6 MiB)**,
control **67108864 (64,0 MiB)** y DN máximo **58458112 (55,8 MiB)**. Se cumplen
las metas 256/512 MiB en esta ejecución. No extrapolar a otros perfiles ni a
clientes en procesos separados; la [repetición H2](evidencias/etapa5/h2-measurement-fixed.json)
sí ejecutó tres procesos cliente y aprobó sus hashes/metas después de D44.
Las dos mediciones H2 fallidas siguen en el [inventario](evidencias/etapa5/README.md).

## Contrato efectivo y responsabilidades

El perfil nuevo se activa con `rf3_enabled=true` en el ControlNode y DataNodes.
La inicialización del laboratorio escribe esa configuración mediante `--rf3`.
Las raíces históricas H1/H2 no se convierten. La lógica RF1/RF2 sigue heredándose
de los mismos manejadores; el perfil E5 añade las reglas de acceso y la autoridad
común de exclusión para write, truncado y overwrite.

| Operación | Regla efectiva |
| --- | --- |
| open r / r+ | Archivo existente; lectura / lectura y escritura. Snapshot y pin atómicos. |
| open w / w+ | Crear o publicar vacío al abrir; escritura / lectura y escritura. Si existe, valida permisos del archivo. Crear exige wx del padre. |
| open x / x+ | Crear exclusivamente; ALREADY_EXISTS si el nombre existe. No se admite a. |
| BeginRead / EndRead | Comandos que ocupan/liberan el handle durante una lectura; evitan write y close incompatibles. SDK iter_read los compone. |
| read / iter_read | Bytes desde cero; rangos sin desbordamiento de entero de 63 bits. Cero o posición >=EOF devuelve vacío tras validar el handle. Cruce de EOF se recorta. read materializa hasta 16 MiB; iter_read admite rangos mayores. |
| BeginWrite | Comprueba modo, ACL, content_epoch, base de cada bloque, tamaño, exclusión y reservas en una transacción. Admite <=16 MiB y <=5 partes contiguas. |
| PatchBlock | Solo el delta por TLS. Base local autenticada o copia S/S ordenada por el control si la colocación requiere otro destino. No concede READ_DATA al escritor. |
| CommitWrite | W=1 verificado mediante recibos mTLS persistidos. Comprueba bases, tamaño y fencing en BEGIN IMMEDIATE; fusiona sobre la raíz actual y publica todo el rango o nada. |
| AbortWrite / GetOperation | Aborto explícito de preparación y consulta de PREPARING/COMMITTED/ABORTED/EXPIRED; resultado confirmado persistente. Sin control no se afirma un aborto: OUTCOME_UNKNOWN. |
| lock / unlock / renew | Parcial exclusivo redondeado a bloques, longitud positiva <=16 MiB, o ámbito completo explícito. Espera inicial 0 y máximo 5 s. Dueño sesión/handle, generación y época. Unlock de una operación activa produce LOCK_BUSY. |
| close | Idempotente para su dueño. Libera pins/locks; no publica bytes. HANDLE_BUSY si quedan operaciones. El SDK espera llamadas de alto nivel sobre ese handle mediante una guarda local adicional. |

El write vacío comprueba modo, ACL, offset (incluido rechazo de huecos), identidad y
snapshot; registra resultado de cero bytes sin cambiar versión. No hay append
atómico ni inserción. Los locks futuros fuera de EOF no cambian tamaño.

Cada write parcial aumenta file_version y conserva content_epoch. Truncado y
overwrite aumentan ambos; un writer anterior falla con VERSION_CONFLICT. Otros
handles mantienen sus snapshots, incluso tras rm. Recrear el nombre asigna otro
file_id; un writer preparado contra el tombstone no puede publicar.

## Identidad, reintento e integridad

El ledger conserva el alcance estable `época de servicio:usuario:request_id`, método,
digest de intención y respuesta cifrada. La intención canónica sigue D30: JSON
Protobuf ordenado, excluyendo contexto, contraseña, capability y hints de expiración.
BeginWrite incluye handle, snapshot base, offset, longitud, SHA-256 del delta,
partición y SHA-256 por parte, además de fences explícitos. PatchBlock liga operación,
base, versión candidata, rango/digest de su delta y fence. CommitWrite liga la misma
operación, cambios/recibos y revisión del handle. Otro método/contenido bajo el mismo
request_id produce IDEMPOTENCY_MISMATCH.

El SDK conserva la identidad al reintentar y consulta GetOperation después de una
respuesta de commit incierta. La consulta devuelve la intención original de write;
permite recuperar un resultado confirmado con el mismo usuario aun después de
expirar el handle, sin ejecutar la escritura ni renovar derechos. Una sesión ajena
no obtiene el resultado de otro usuario. Las partes se validan individualmente en
los DNs; el digest global del delta también fija la intención del cliente.

En lectura, el control proporciona identidad, posición, longitud y SHA-256
autoritativos del bloque. El DataNode valida AES-GCM y hash de la base completa
antes de enviar el primer fragmento. Solo envía el rango concedido. El cliente
compara el SHA-256 autoritativo cuando obtiene el bloque completo; una fracción
queda protegida por autenticación del almacenamiento y TLS, sin inventar una
comparación con el hash completo. Fallar un destino permite resolver otro de la
misma versión. STALE_HANDLE interrumpe; no se reabre automáticamente otra versión.

Después de un parche, file_sha256 queda ausente: el control no descarga los bytes
para calcularlo. RF2 verifica cada bloque y el hash del manifiesto, calcula el
hash de lo descargado y compara el hash global solo si estaba presente (subidas
completas). Las pruebas comparan además con un SHA-256 esperado calculado localmente.

## Tiempo, limpieza, recursos y seguridad

SQLiteLeaseAuthority implementa el puerto LeaseAuthority; la coordinación por
etcd sigue pendiente de E7. El reloj de leases es monotónico y solo se interpreta
con su época de arranque. El contador persistido de arranque avanza y se genera
otra identidad de época; todos los handles anteriores se cierran y locks se
invalidan. La identidad estable del servicio, sesiones y ledger se conservan.
Esta separación respeta la semántica de [time.monotonic de Python](https://docs.python.org/3.12/library/time.html#time.monotonic).
Los commits serializan sus decisiones con [BEGIN IMMEDIATE de SQLite](https://www.sqlite.org/lang_transaction.html),
sin mantener la transacción durante el transporte.

Locks: 30 s / renovación cada 10 s durante write; handles: 120 s, máximo 24 h.
La renovación de lectura del SDK conserva inicialmente el intervalo H2 de 30 s
(más frecuente que la propuesta de 40 s). Un stream autorizado está limitado por
su deadline 30/120/240 s y el vencimiento de la autorización emitida; renovar el
handle no amplía retroactivamente un grant ya emitido. Requiere nueva autorización
si debe reiniciarse. Un lease vencido nunca se revive; la publicación siempre
revalida propiedad y generación. Para uploads completos se conserva la renovación
H2 de 5 minutos, con exclusión completa de la misma autoridad.

Limpieza, pins y reservas RF3 consultan la misma vigencia monotónica. El campo
expires_at_unix_ms es un hint de transporte; no puede vencer por sí solo un lock,
liberar su reserva ni borrar el snapshot que todavía mantiene un handle válido.
El test aislado de SQLite/autoridad comprueba este caso; no se cuenta como tráfico
distribuido. Renovar un fence cambia su hint de vencimiento, nunca su identidad:
PatchBlock y CommitWrite comparan dueño/generación/época/ámbito ignorando ese hint.

Admisión global en cada DN: cuatro unidades; perfiles 4/64/128 MiB consumen 1/2/4.
El delta de una llamada ocupa <=16 MiB y se admite antes de acumularlo: como máximo
cuatro buffers de delta de ese tamaño, más fragmentos/criptografía y sobrecarga.
No se almacena un bloque de 128 MiB entero en memoria. El parche procesa la base
dos veces para calcular primero el hash y después cifrar el resultado; cada lector
verificado hace su validación completa antes de entregar bytes. La métrica de base
procesada cuenta esas cuatro pasadas. Se reserva un objeto completo más su formato
cifrado; si se requiere base remota también se reserva la copia S/S.

La recolección conserva snapshots vivos, handles, versiones candidatas activas y
fuentes de tareas S/S. Expirar una autorización de transporte no ordena borrar un
bloque. Las preparaciones abortadas quedan invisibles y se retiran mediante tareas
idempotentes del control. Las claves persistentes y AES-GCM son los de H2: no se
generan claves sustitutas para volúmenes existentes. SQLite, inventarios y WAL no
están cifrados por SQLite; dependen de ACL del host y futura protección de volumen.
Los logs admiten campos seguros y no contenido/tokens; backups cifrados y seguridad
integral siguen pendientes de E8. TLS/mTLS local no acredita Internet ni HA.

## Reproducción en PowerShell

Desde `F:\DFSha`, con el entorno ya instalado (sin cambiar dependencias):

```powershell
.\.venv-win\Scripts\python.exe scripts/verify_stage5.py --measure
.\.venv-win\Scripts\python.exe scripts/lab_hito2.py init --rf3 --root .runtime/demo-e5
.\.venv-win\Scripts\python.exe scripts/lab_hito2.py start --root .runtime/demo-e5
.\.venv-win\Scripts\python.exe -m dfsha.client.cli --config .runtime/demo-e5/client.toml --session-file .runtime/demo-e5/user/session.json login admin
.\.venv-win\Scripts\python.exe -m dfsha.client.cli --config .runtime/demo-e5/client.toml --session-file .runtime/demo-e5/user/session.json shell
```

Contraseña del laboratorio: `development-password`. Se solicita por terminal;
no usarla fuera del entorno local. Preparar un delta local pequeño, por ejemplo
con `Set-Content -NoNewline .runtime/delta.txt 'hola'`, y ejecutar en la shell:

```text
open /demo x+ writer
write writer 0 .runtime/delta.txt
open /demo r reader
lock writer owned --offset 0 --length 1
renew-lock owned
unlock owned
read reader 0 4 .runtime/read.txt
renew-handle reader
close reader
close writer
exit
```

`write` imprime operation_id; `operation <operation_id>` consulta el resultado.
Para una identidad elegida antes de enviar: `write writer 0 .runtime/delta.txt
--request-id <UUID>`. Los alias de handles/locks se guardan en el archivo privado
de sesión y funcionan también con invocaciones CLI separadas. Los handles expiran;
conservar el archivo de sesión no extiende su vigencia.

```powershell
.\.venv-win\Scripts\python.exe scripts/lab_hito2.py stop --root .runtime/demo-e5
.\.venv-win\Scripts\python.exe scripts/verify_stage4.py --measure
.\.venv-win\Scripts\python.exe scripts/verify_stage3.py --measure
```

El test `test_parallel_disjoint_merge_and_conflict` es la demo SDK reproducible
de dos handles y barreras; `test_multiblock_atomic_abort_and_idempotency` provoca
respuesta perdida y consulta el resultado; `test_fencing_successor_restart_and_persistent_result`
demuestra el rechazo del escritor pausado y reapertura tras reinicio.

Para preparar manualmente los dos bloques del ejemplo SDK, antes de entrar en la
shell puede crear un archivo local de ceros sin cargarlo entero en memoria:

```powershell
$demoStream = [System.IO.File]::Create((Join-Path $PWD '.runtime/two-blocks.bin'))
$demoStream.SetLength(8388608)
$demoStream.Dispose()
```

En la shell: `send .runtime/two-blocks.bin /large`. Sobre ese archivo, `open /large
r+ a`, `open /large r+ b` y `open /large r reader` crean tres snapshots; `lock a
held --offset 0 --length 1` hace que `lock b conflict --offset 1 --length 1`
produzca LOCK_CONFLICT, aunque los bytes sean distintos. `unlock held` libera
solamente la adquisición de a. Los tests con barreras acreditan la preparación
concurrente que una secuencia de comandos de shell no demuestra por sí sola.

Ejemplo SDK para un archivo existente `/large` con al menos dos bloques:

```python
from concurrent.futures import ThreadPoolExecutor
from dfsha.client.sdk import Client

client = Client('localhost:<puerto-del-control>', '.runtime/demo-e5/client-trust')
client.login('admin', 'development-password')
a, b, reader = client.open('/large', 'r+'), client.open('/large', 'r+'), client.open('/large')
size = a.snapshot.block_size_bytes
pa = client.begin_write(a, 0, b'A')
pb = client.begin_write(b, size, b'B')
with ThreadPoolExecutor(2) as pool:
    fa = pool.submit(client.prepare_blocks, a, pa, b'A')
    fb = pool.submit(client.prepare_blocks, b, pb, b'B')
    ca, cb = fa.result(), fb.result()
client.commit_write(a, pa, ca)
client.commit_write(b, pb, cb)  # Conserva A y añade B sobre el manifiesto vigente.
assert client.read(b, 0, 1) == b'A'
assert client.read(b, size, 1) == b'B'
# reader conserva el snapshot anterior; a conserva el que publicó A.
for handle in (a, b, reader):
    client.close(handle)
client.shutdown()
```

Usar el endpoint real de `.runtime/demo-e5/client.toml`; el marcador no es una URL
desplegada. La API de preparación explícita sirve para esta demostración; quien
la usa debe renovar sus fences durante pausas largas o abortar la operación.
`client.write` compone preparación/renovación/commit automáticamente.

## Estado de las comunicaciones

| Relación | E5 |
| --- | --- |
| Cliente–ControlNode | TLS; namespace, sesiones, planes, snapshots, read leases, locks y commits. Cero contenido de archivo. |
| Cliente–DataNode | TLS; PutBlock, PatchBlock y GetBlock con autorización online por recurso/rango. |
| ControlNode–ControlNode | PENDIENTE E7; solo existe un control autoritativo. |
| ControlNode–DataNode | mTLS; registro, heartbeats, recibos, autorizaciones y tareas, reutilizados de H2. |
| DataNode–DataNode | Copia cifrada por streaming y tarea limitada; también sirve para trasladar una base de parche. No reparación automática. |

E6 será replicación R=3/W=2 y recuperación de datos; E7, HA del control/metadatos.
Con R=1, perder la única base produce indisponibilidad. Los procesos locales
no demuestran tolerancia a pérdida del host. Linux, Internet y cloud se mantienen
sin acreditar en esta sesión. El perfil 128 MiB solo tiene validación funcional,
no una declaración de optimización ni benchmark comparativo.
