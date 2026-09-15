# DFSha — Contratos de comunicación v1

**Perfil E7 verificado en Windows local:** [contratos y configuración HA](etapa7-ha-control.md).
Se conservan RPC v1 y numeración. Health añade disponibilidad de metadatos,
instancia y revisión; estar vivo no equivale a tener mayoría disponible.
SDK/CLI admiten `public_targets`; DataNodes, `control_internal_targets` e
identidades administrativas de los controles. Los datos mantienen transporte
directo C↔DN y DN↔DN. E7 usa presupuesto de 15 s para consultas/comandos de
control; el perfil histórico conserva 5 s. SealManifest y streams conservan sus
límites específicos. Cada conmutación conserva solicitud, request_id e intención.
Los internos de PatchBlock también utilizan el presupuesto configurado del control.

**E6 implementada:** [política y tareas](etapa6-replicacion.md); extensiones
aditivas, sin reutilizar números. 58 RPC; el catálogo separa perfiles históricos.

| RPC | Solicitud → respuesta | Acceso / efectos | Límite y confirmación |
| --- | --- | --- | --- |
| ClusterAdministrationService.GetProtection | ProtectionRequest(path u operation_id, snapshot_id opcional, page) → ProtectionStatus | Consulta TLS con sesión; ACL de lectura para archivo o propietario de operación; snapshot retenido exige handle propio | Unary 5 s; ≤64 bloques/página; estado por página, próximo cursor, W alcanzado y copias elegibles; NOT_FOUND, STALE_HANDLE, PERMISSION_DENIED |
| ClusterAdministrationService.PromoteProtection | PromoteProtectionRequest(path, expected_policy_revision) → MutationResult | Comando TLS, admin; eleva política y registra promoción; cancela operaciones antiguas | Unary 5 s; request_id/digest idempotente; respuesta confirma barrera, no copias obtenidas. VERSION_CONFLICT, PERMISSION_DENIED; progreso por GetProtection |

VerifyReceipt añade `verify_content=6`; ReplicateBlock añade `replace_receipt_id=10`
para comparar la instancia antes de cuarentena. DeleteRetiredBlock añade
`expected_receipt_id=7`: compara la instancia física bajo pin exclusivo antes
de borrar y revalida autorización; VERSION_CONFLICT preserva la copia reemplazada.
ReportTask utiliza su Fence ya
previsto: dueño/época/generación se comprueban dentro de la transacción que registra
la copia. UploadPlan.minimum_durable=7 y WritePlan.minimum_durable=5 permiten al
SDK esperar W; un cliente anterior no puede saltarse la validación en commit.

**Perfil RF3 E5:** aplicar [semántica efectiva](etapa5-rf3.md) y las extensiones
al final de este documento. Catálogo histórico E5: 56 RPC; los estados H1, H2 y RF3
se distinguen en rpc-catalog.json. Las cifras siguientes se conservan como historial.

**Estado histórico E3:** aplicar [contrato operativo H1](protocolos-hito1.md), que
define los métodos implementados, perfiles, cifrado, digest y plazos actuales.
Las tablas siguientes conservan el diseño y registro de E2; sus propuestas
incompatibles quedan sustituidas explícitamente por H1. El catálogo JSON ya
describe H1: 51 RPC, 27 funcionales locales, tres diagnósticas y 21 futuras.

2026-09-08 · Etapa 2. Este documento formaliza decisiones del equipo, no añade requisitos al PDF. Fuentes: [arquitectura](arquitectura.md), [semántica del servicio](especificacion.md), [contratos fuente](../proto/dfsha/v1/) y [fuentes oficiales de etcd](../third_party/README.md). Los contratos futuros compilan; su implementación sigue **PENDIENTE**. Solo las tres RPC de DiagnosticService están implementadas. Todos los métodos futuros registrados devuelven `UNIMPLEMENTED / NOT_IMPLEMENTED_STAGE2`, incluso con solicitudes vacías: no aparentan autenticación, listados ni persistencia funcionales.

## 1. Relaciones, servicios y estado

| Relación | Origen → destino y servicios | Seguridad prevista y errores | Estado E2 |
| --- | --- | --- | --- |
| COM-01 | CLI/SDK → CN: AuthenticationService, IdentityService, NamespaceService, UploadService, FileAccessService. | TLS con CA/SAN; sesión y ACL; errores de identidad, rutas, revisión, lease y publicación definidos abajo. | 31 RPC de contrato; negocio UNIMPLEMENTED. Diagnóstico TLS cliente/servidor real por separado. |
| COM-02 | CLI/SDK → DN: BlockService.PutBlock, PatchBlock, GetBlock. | TLS; sesión **y** permiso opaco restringido por recurso/rango/DN. DN consulta autoridad interna. | Tres RPC UNIMPLEMENTED; streaming real solo de diagnóstico sintético. |
| COM-03 | CN → etcd → otros CN: KV, Txn, Lease, Lock, Watch; miembros etcd se comunican entre sí. | mTLS y RBAC, consultas linealizables y condiciones dentro de Txn; sin mayoría, error controlado. | Contratos oficiales y prueba Python↔un etcd real. No hay CN múltiples, consenso/failover probado ni RPC directa CN–CN. Q05 pendiente. |
| COM-04 | DN → CN: NodeRegistryService e InternalAuthorizationService. CN → DN: StorageAdministrationService. | mTLS; identidad de nodo y rol; fencing, recibos comprobados con el DN emisor; errores de autorización/capacidad/retiro. | Once RPC UNIMPLEMENTED. Listener interno exige certificado de cliente en prueba real. |
| COM-05 | DN → DN: ReplicaService.StoreReplica/GetReplica, por tarea autorizada del CN. | mTLS y permiso de tarea, origen/destino y fence; contenedor cifrado íntegro. | Dos RPC UNIMPLEMENTED; no hay replicación de bloques. |

La coordinación mediada es `CN1 --Txn/Lease--> etcd --Watch/Range--> CN2/CN3`. Watch notifica; Range/Txn consistente decide. Los tres miembros etcd y tres controles de D06 se implementarán/probarán en E7. El servidor E2 aloja servicios públicos e internos en un proceso modular con dos listeners loopback. `MetadataStore`, `Coordinator`, `BlockStore` y `Authorizer` son interfaces Python sin lógica de negocio. El arranque no importa ni conecta el cliente de prueba etcd y no requiere un servicio etcd: H1 usará SQLite y bloques locales.

## 2. Reglas comunes obligatorias

Cada fila de las tablas siguientes se interpreta junto con estas reglas, su perfil de autorización, política de reintento y catálogo de errores. Son obligatoriedad **semántica**: proto3 no incorpora `required`. Las validaciones de negocio corresponden a las etapas de implementación; E2 valida solo los datos de diagnóstico.

| Campo/tamaño | Regla |
| --- | --- |
| Versionado | Paquete `dfsha.v1`, ruta `/<paquete>.<Servicio>/<Método>`. No reutilizar números de campos/enums retirados: reservarlos. Cambios aditivos opcionales mantienen v1; cambios de significado requieren v2. No editar módulos generados. |
| `RequestContext` / C | `request_id` UUID canónico minúsculo, `user_id` igual al sujeto autenticado (usuario o nodo), `service_epoch` UUID vigente. En mutaciones idempotentes `intent_sha256` de 32 bytes. Lecturas llevan los tres IDs; digest vacío. No basta declarar un user_id para autenticarse. Login y diagnóstico tienen su propio request_id. |
| Identidades | UUID canónico para file_id, operation_id, handle_id, block_version_id, lock_id, receipt_id, task_id, report_id, inventory_id y session_id. Node/user/group IDs estables también UUID; el bootstrap de usuarios etcd usa sus nombres oficiales separados. Nunca reutilizar file_id ni block_version_id. IDs de página/cursor son opacos ASCII, máximo 512 bytes. |
| Versiones | content_epoch, file_version, revisión, boot_generation y fencing positivos cuando existe objeto. Cero significa ausente/objeto nuevo solo cuando la fila lo permite. Rechazar desbordamientos; offsets/tamaños de archivo hasta `2^63−1`, suma offset+length comprobada. Las metas 1 GiB/10 clientes no son resultados ni límites impuestos por el PDF. |
| Rutas | PathRef.path UTF-8 NFC, 1..4096 bytes; componentes ≤255 bytes y profundidad ≤32; `/`, `.` y `..` según S4; sin NUL ni `\`. Relativa exige cwd_path absoluto y cwd_id vigente. Absoluta omite cwd; el servidor valida traversal/ACL, nunca abre una ruta del host construida directamente con la cadena del usuario. |
| Paginación | PageRequest.limit 1..100; ResolveBlocks lo limita a 64. Cursor ligado a actor, revisión y consulta, nunca lista ilimitada. List falla LIST_CHANGED si cambia revisión entre páginas. Páginas de manifiesto/inventario ≤64 entradas y ≤64 KiB serializados; tamaño dominante, no solo conteo. |
| Tamaños de datos | Bloque lógico **4 MiB** máximo; fragmento de red **256 KiB** máximo; write lógico **16 MiB** máximo (puede afectar cinco bloques por desalineación). Un mensaje gRPC ≤1 MiB incluidos encabezados: ninguno contiene un bloque/write completo. Buffer de diagnóstico O(fragmento); no se ha medido RSS ni rendimiento del DFS. |
| Integridad | SHA-256 = exactamente 32 bytes, incluso archivo vacío tiene hash de cadena vacía. BlockRef no vacío lleva longitud 1..4 MiB. Snapshot de archivo vacío no tiene bloques. Checksums describen el contenido indicado, nunca una cadena hexadecimal dentro de bytes. |
| Stream de carga | Un encabezado obligatorio, luego cero o más chunks; no repetir encabezado. Chunks de 1..256 KiB, offsets contiguos desde cero **dentro del stream**, total exacto. Cero chunks solo para diagnóstico vacío; no se crea un bloque vacío. EOF prematuro, excesos o checksum incorrecto fallan sin publicar. |
| Stream de lectura | Encabezado primero (BlockService/ReplicaService); chunks contiguos desde cero respecto al rango. DiagnosticService.GenerateStream solo envía chunks, sin encabezado, de patrón conocido. Nunca mezclar identidades/versiones entre fragmentos o reintentos. |
| Sesiones/permisos | Tokens aleatorios opacos de 32 bytes. Metadata gRPC `authorization: Bearer <base64url sin padding>` para sesión; capabilities de bloque/tarea en campo bytes. No URLs con secretos, ni tokens, contraseñas, claves o cuerpos en logs. TLS protege metadata. Credenciales se renuevan sin cambiar intención. |
| ACL | owner_id/group_id, permisos 0..7 (r=4,w=2,x=1), ≤64 concesiones adicionales; IDs únicos ordenados; denegación por defecto. Grupo ≤100 miembros por sustitución CAS inicial; nombres usuario/grupo NFC 1..64 bytes. Contraseña 12..1024 bytes UTF-8, no normalizarla ni registrarla. Los costes Argon2id son parámetros de equipo, no RNF6 completo. |
| Deadlines | Cada RPC tiene plazo total en las tablas, incluye conexión/transporte. SDK propaga plazo restante a subllamadas; no reinicia tiempo indefinidamente. Diagnóstico rechaza ausencia de deadline o >30 s; máximo de stream futuro de bloque 15 s, aun si expira la capacidad durante un stream ya autorizado. |

### Autorización por perfiles

- **D**: diagnóstico público limitado a loopback con TLS; interno además certificado de la CA de desarrollo. No autentica usuarios del DFS ni asigna roles productivos.
- **L**: Login TLS, sin sesión previa; validar contraseña con Argon2id, límites de intentos/concurrencia. Mensaje genérico ante usuario o contraseña incorrectos.
- **U**: sesión válida, usuario habilitado y época vigente; propietario de sesión/handle/operación cuando aplica. Recorrer ancestros requiere `x`; lectura de archivo `r`, escritura `w`, listar directorio `r+x`, crear/borrar `w+x` en padre. Stat verifica traversal y permiso sobre recurso. Locks requieren capacidad de escritura. Permisos de snapshots se revalidan; un handle no evita revocación.
- **A**: U más administrador para gestionar cuentas/grupos; dueño o administrador para ACL. Validar IDs/membresía, revisión y denegación por defecto.
- **B**: U en DN más permiso opaco emitido por CN para acción/file_id/bloque/versión/offset/longitud/DN/operación/handle. DN llama AuthorizeBlock por mTLS. `PatchBlock` permite modificar sin revelar base a un usuario que tenga solo escritura; lectura interna de base autorizada separadamente.
- **N**: mTLS con certificado de nodo activo, identidad coincidente, rol permitido, boot_generation y época vigentes. Registro debe partir de inventario administrativo permitido, no confiar en un node_id autodeclarado. Registro/heartbeat/reportes DN→CN; verificación/tareas CN→DN.
- **T**: N más permiso de tarea y fence, origen/destino/versiones exactos. CN valida que la tarea sigue viva; conocer un block_id no concede acceso. Denegación de introspección es PERMISSION_DENIED; no una respuesta falsa de éxito.

### Reintentos, identidad e intención

Políticas referidas por cada fila:

- **Q**: lectura repetible, máximo tres intentos con backoff exponencial inicial 100 ms, tope 1 s y jitter, dentro del plazo total. Solo UNAVAILABLE y fallos transitorios identificados; no repetir denegaciones/conflictos. Repetir un stream significa abrir uno nuevo para el **mismo snapshot/rango**, descartando el intento incompleto; no concatenar sin validar posición. gRPC tiene retries automáticos desactivados en E2.
- **M**: mutación con registro persistido de intención/resultado. Ante respuesta perdida, consultar GetOperation por el request_id original; repetir solo con identidad e intención idénticas. Cada sub-RPC tiene su propio request_id y conserva operation_id de la transferencia/write. Máximo de intentos/plazo de Q; si no se conoce resultado, OUTCOME_UNKNOWN, nunca asumir que no se aplicó.
- **S**: stream idempotente por identidad de objeto/operación/tarea e intención; reenvía desde offset cero al mismo destino. ACK durable previo se recupera, no se vuelve a modificar un bloque inmutable. Elegir otro destino exige otro request_id/capability aunque conserve operation_id y versión lógica. No resumir a un offset arbitrario en E2/v1.
- **N0**: no repetir automáticamente Login/RefreshSession; podría crear/rotar otra sesión. Request_id es correlación. Ante respuesta perdida se vuelve a autenticar con una solicitud nueva; no inventar éxito.

La clave de deduplicación futura es `(service_epoch, sujeto autenticado, request_id)` **en todo el servicio**, también entre métodos/destinos. El ledger guarda método y destino lógico, digest, estado, resultado y referencias. Usar esa clave para otro método, destino o contenido produce `ALREADY_EXISTS / IDEMPOTENCY_MISMATCH`; no es un reintento válido. DNs deben reservar/consultar esa identidad por la autoridad compartida al autorizar; SQLite proporciona el mismo contrato dentro de H1. E2 no implementa el ledger.

Representación de intención v1: JSON UTF-8 compacto, claves ASCII ordenadas lexicográficamente, sin espacios, strings de texto normalizados NFC (salvo secretos), escapes JSON estándar sin convertir Unicode a ASCII. Enteros se representan como cadenas decimales sin signo/cero inicial salvo `0`, bytes como base64url sin padding, enums por nombre, booleanos JSON, ausentes opcionales como `null`, listas ordenadas. No usar floats ni confiar en serialización Protobuf «determinista» como canonización entre lenguajes.

El objeto superior tiene `schema="dfsha.intent.v1"`, `method` con nombre completo, `actor`, `service_epoch`, `destination` (servicio de control o node_id concreto) e `intent`. `intent` incluye **todos** los campos semánticos de solicitud/encabezado y sus submensajes: ruta/cwd normalizados, destinatarios lógicos, IDs, modos, revisiones/base, epochs, offsets/longitudes, hashes de payload/manifiesto, ACL/membresías, page_index, total, fence (lock_id, generación, lease, recursos), retiro y tareas. Listas de conjuntos se ordenan por identidad/índice sin duplicados; chunks no forman JSON: su digest SHA-256 y longitud en encabezado comprometen todos los bytes y orden. Para streams de réplica también se incluyen ciphertext hash/longitud, key_id y destino.

Excluir únicamente `RequestContext` (actor/época ya arriba), request_id, tokens/capabilities/password, datos de routing `client_endpoint/private_endpoint` cuando sean solo ubicaciones resueltas, marcas de expiración renovables, y metadata de red/deadline. **RegisterNode sí incluye los endpoints que registra**: son su intención, no routing incidental. Las revisiones/generaciones de fence nunca se excluyen. Cambiar base, destino, offsets, contenido o fence necesita solicitud nueva; refrescar la capacidad para la misma operación no. El servidor recalcula y compara `intent_sha256` antes de efectos. Si una operación expiró, devuelve OPERATION_EXPIRED; los registros compactos de resultado/deduplicación y tombstones se conservan **durante la vida del proyecto**, como A3/D14. La presión de cuota rechaza nuevas operaciones antes de eliminar esa protección. Borrar un ledger no autoriza repetir efectos.

Excepción necesaria de secretos: el digest público de CreateUser excluye password; el registro guarda además un **verificador Argon2id con sal propia** de esa contraseña. Un retry solo coincide si digest **y verificación del secreto** coinciden, aun si luego cambió la contraseña del usuario. No almacenar SHA-256 rápido de contraseñas ni usarlo como compromiso público. Login/RefreshSession no usan M. Este comparador dual y límites de intentos quedan pendientes junto a autenticación en E3/E8; no confundir la prueba aislada de Argon2 con su implementación.

### Errores estables

Las filas incluyen motivos específicos además de los comunes. Los errores de aplicación usan código gRPC y trailer binario `dfsha-error-bin` con ErrorDetail (`reason`, request_id validado, retryable). Nunca analizar texto libre. Errores de transporte/handshake, tamaño de mensaje y cancelación pueden llegar **sin trailer**: el cliente conserva el StatusCode, sin atribuirlo a una operación confirmada.

| Código gRPC | Motivos estables y efecto |
| --- | --- |
| INVALID_ARGUMENT | INVALID_ARGUMENT, UNSUPPORTED_MODE, SPARSE_WRITE_UNSUPPORTED: campos/rangos/modos inválidos; no cambiar intención y repetir. |
| UNAUTHENTICATED / PERMISSION_DENIED | Motivo homónimo: sesión ausente/inválida frente a identidad válida sin permiso. El handshake mTLS puede fallar antes con UNAVAILABLE. |
| NOT_FOUND / ALREADY_EXISTS | NOT_FOUND / ALREADY_EXISTS; ALREADY_EXISTS también IDEMPOTENCY_MISMATCH. |
| FAILED_PRECONDITION | NOT_DIRECTORY, IS_DIRECTORY, DIRECTORY_NOT_EMPTY, ROOT_PROTECTED, CWD_GONE, STALE_HANDLE, LOCK_EXPIRED, OPERATION_EXPIRED, NOT_RETIRED. No publicar tras el fallo. |
| ABORTED | VERSION_CONFLICT, LIST_CHANGED, LOCK_CONFLICT, HANDLE_BUSY, LOCK_BUSY. Volver a resolver y emitir una intención nueva si corresponde; no sobrescribir cambios ajenos. |
| RESOURCE_EXHAUSTED | LIMIT_EXCEEDED, NO_SPACE. Transporte puede emitir el código sin detalle al exceder 1 MiB. |
| UNAVAILABLE | SERVICE_UNAVAILABLE, INSUFFICIENT_REPLICAS, METADATA_QUORUM_LOST, DATA_UNAVAILABLE. W de datos y mayoría de metadatos son verificaciones distintas. |
| DEADLINE_EXCEEDED / CANCELLED | DEADLINE_EXCEEDED u OUTCOME_UNKNOWN cuando el servidor logra producir detalle; CANCELLED de transporte conserva su código. Un timeout de conexión a proceso detenido es un error controlado y no una respuesta del servidor. Consultar M; no declarar fracaso definitivo del commit. |
| DATA_LOSS | DATA_LOSS, CHECKSUM_MISMATCH: rechazar objeto/rango; resolver otra copia del mismo snapshot, registrar corrupción y reparar posteriormente. |
| UNIMPLEMENTED | NOT_IMPLEMENTED_STAGE2 en todas las RPC futuras. No consultar otro nodo esperando implementación inexistente. |

## 3. Catálogo completo de RPC propias

Tipos exactos en los `.proto`; tipos abreviados debajo siempre pertenecen a `dfsha.v1`. `C` representa RequestContext obligatorio. Parámetros no citados como opcionales son obligatorios salvo booleanos/contadores cero válidos expresamente definidos. En respuestas, IDs/revisiones/valores confirmados son obligatorios; cursores solo si hay continuación. `Unary` significa unary→unary; `C-stream` stream→unary; `S-stream` unary→stream. Los campos de contexto, límites comunes, autorización y errores de §2 forman parte de **cada** fila. Todas las filas salvo DiagnosticService están PENDIENTES de implementación y prueban UNIMPLEMENTED en E2.

### Diagnóstico (EJECUTADO)

| Servicio.RPC · origen/destino | Solicitud → respuesta; campos y límites | Seguridad | Tipo/plazo/retry | Confirmación y errores específicos |
| --- | --- | --- | --- | --- |
| DiagnosticService.Health · cliente→listener público/interno | HealthRequest(request_id) → HealthResponse(request_id,version,listener,diagnostic_ready,filesystem_implemented=false,metadata_backend=sqlite-planned). | D | Unary / 5 s / Q | Proceso y canal disponibles; no comprueba RF, disco ni etcd. UUID inválido: INVALID_ARGUMENT. |
| DiagnosticService.StreamDigest · cliente→listener | DiagnosticFrame(header(request_id,total_bytes,sha256),chunks) → DigestResult(received_bytes,sha256,chunks,max_chunk_bytes). Total 0..64 MiB. | D | C-stream / 15 s / repetir prueba nueva | ACK de cómputo incremental, **sin persistir**. INVALID_ARGUMENT por orden/total; LIMIT_EXCEEDED por chunk/total; CHECKSUM_MISMATCH por hash. |
| DiagnosticService.GenerateStream · cliente→listener | GenerateRequest(request_id,total_bytes 0..64 MiB,chunk_bytes 1..256 KiB) → DiagnosticChunk(offset,data). Byte en posición i = i mod 256. | D | S-stream / 15 s / Q | Fin correcto solo tras longitud/hash esperado del patrón. LIMIT_EXCEEDED; cancelación/deadline interrumpe. |

### Identidad y espacio de nombres (COM-01)

| Servicio.RPC · cliente→CN | Solicitud → respuesta; campos/límites adicionales | Autorización | Tipo/plazo/retry | Confirmación futura y motivos adicionales |
| --- | --- | --- | --- | --- |
| AuthenticationService.Login | LoginRequest(request_id,username,password) → Session(session_id,user_id,token32,expires_at,service_epoch). | L | Unary / 5 s / N0 | Sesión emitida; UNAUTHENTICATED sin revelar si existe usuario. |
| AuthenticationService.Logout | SessionRequest(C,session_id) → MutationResult. | U, propia sesión | Unary / 5 s / M | Revocación persistida; retry del mismo resultado accesible con identidad aún comprobable, sin reactivar sesión. |
| AuthenticationService.RefreshSession | SessionRequest(C,session_id) → Session. | U, propia sesión | Unary / 5 s / N0 | Rotación atómica y revocación del token anterior; no devuelve secretos en ledger público. |
| IdentityService.CreateUser | CreateUserRequest(C,username,password) → User. | A administrador | Unary / 5 s / M + verificador secreto | Cuenta/hash persistidos; ALREADY_EXISTS, IDEMPOTENCY_MISMATCH. Sin cambio de contraseña implícito. |
| IdentityService.SetUser | SetUserRequest(C,user_id,disabled,expected_revision) → User. | A administrador | Unary / 5 s / M | CAS habilitar/deshabilitar; VERSION_CONFLICT, NOT_FOUND. |
| IdentityService.CreateGroup | CreateGroupRequest(C,name) → Group. | A administrador | Unary / 5 s / M | Grupo nuevo vacío **cuando se implemente**; ALREADY_EXISTS. |
| IdentityService.SetGroupMembers | SetGroupMembersRequest(C,group_id,user_ids ≤100,expected_revision) → Group. | A administrador | Unary / 5 s / M | Sustitución CAS completa del conjunto, incluyendo vacío; NOT_FOUND, VERSION_CONFLICT. |
| IdentityService.GetAcl | GetAclRequest(C,path) → Acl. | U traversal + recurso | Unary / 5 s / Q | Lectura de revisión de autorización, NOT_FOUND. |
| IdentityService.SetAcl | SetAclRequest(C,path,acl,expected_revision) → MutationResult. | A dueño/admin | Unary / 5 s / M | ACL/grupo/dueño validados y revisión publicada; VERSION_CONFLICT. |
| NamespaceService.List | ListRequest(C,path,page) → ListResponse(entries≤100,next_cursor,directory_revision). | U, r+x directorio | Unary / 5 s / Q | Página de una revisión; LIST_CHANGED, NOT_DIRECTORY, CWD_GONE. |
| NamespaceService.Stat | PathRequest(C,path) → Entry(object_id,name,kind,size,revision,snapshot si archivo). | U | Unary / 5 s / Q | Metadatos consistentes; NOT_FOUND, CWD_GONE. |
| NamespaceService.Mkdir | PathRequest(C,path) → Entry. | U, w+x padre | Unary / 5 s / M | Crear un directorio, sin `-p` implícito; ALREADY_EXISTS, NOT_DIRECTORY. |
| NamespaceService.Rmdir | PathRequest(C,path) → MutationResult. | U, w+x padre | Unary / 5 s / M | Retiro atómico del directorio vacío; DIRECTORY_NOT_EMPTY, ROOT_PROTECTED, NOT_DIRECTORY. |
| NamespaceService.Remove | PathRequest(C,path) → MutationResult. | U, w+x padre | Unary / 5 s / M | Tombstone/file_id retirado; snapshots abiertos retenidos, escritores invalidados; IS_DIRECTORY, ROOT_PROTECTED, NOT_FOUND. |

### Transferencia completa y acceso parcial (COM-01)

| Servicio.RPC · cliente→CN | Solicitud → respuesta; campos/límites adicionales | Autorización | Tipo/plazo/retry | Confirmación futura y motivos adicionales |
| --- | --- | --- | --- | --- |
| UploadService.BeginUpload | BeginUploadRequest(C,path,overwrite,total_bytes,file_sha256,expected_snapshot si reemplazo) → UploadPlan(operation,file_id,content_epoch,fence,block_bytes=4 MiB,expiry). | U w archivo / w+x padre nuevo | Unary / 5 s / M | Reserva invisible, lock completo/época de contenido; no archivo completo. ALREADY_EXISTS, VERSION_CONFLICT, LOCK_BUSY. |
| UploadService.RenewUpload | OperationRequest(C,operation) → UploadPlan con vencimiento renovado. | U dueño de operación/sesión, permisos vigentes | Unary / 5 s / M | Renueva TTL 300 s, máximo vida 1 h; no revive abortados/vencidos. OPERATION_EXPIRED, PERMISSION_DENIED. Implementada H1. |
| UploadService.AllocateBlocks | AllocateBlocksRequest(C,operation,blocks≤64,fence) → BlockPlan. Bloques con ID/índice/tamaño/hash conocidos. | U dueño operación | Unary / 5 s / M | Reserva destino/capacidad y permisos; no ACK de datos. NO_SPACE, INSUFFICIENT_REPLICAS, LOCK_EXPIRED. |
| UploadService.StageManifestPage | StageManifestPageRequest(C,operation,page_index,blocks,page_sha256,fence) → PageReceipt. Índices únicos ordenados. | U dueño operación | Unary / 5 s / M | Página inmutable validada, invisible; CHECKSUM_MISMATCH, LOCK_EXPIRED. Recibos durables consultados por operation/bloque, no confiados del cliente. |
| UploadService.SealManifest | SealManifestRequest(C,operation,page_count,block_count,total_bytes,manifest_sha256,fence) → PageReceipt raíz. | U dueño operación | Unary / 15 s / M | Sellado de páginas fijadas; valida cobertura/tamaño y recibos W por bloque, sin publicación. CHECKSUM_MISMATCH, INSUFFICIENT_REPLICAS. Manifiestos grandes se sellan incrementalmente con trabajo acotado. |
| UploadService.CommitUpload | CommitUploadRequest(C,operation,seal,fence) → CommitResult(COMMITTED,snapshot,accepted_bytes,R,W,degraded). | U dueño operación | Unary / 5 s / M | Publicación atómica después de durabilidad y CAS; LOCK_EXPIRED, VERSION_CONFLICT, INSUFFICIENT_REPLICAS, METADATA_QUORUM_LOST. |
| UploadService.AbortUpload | OperationRequest(C,operation) → MutationResult. | U dueño operación | Unary / 5 s / M | Estado ABORTED si no confirmado; no borra versión anterior. VERSION_CONFLICT si ya COMMITTED. GC de staging diferida. |
| UploadService.GetOperation | GetOperationRequest(C,original_request_id u operation_id; ambos deben coincidir si presentes) → OperationStatus. CommitResult solo presente para publicaciones de archivo. | U dueño, N para tareas internas propias | Unary / 5 s / Q | Estado compartido autoritativo; para otras mutaciones COMMITTED permite recuperar su respuesta original repitiendo M. NOT_FOUND no prueba que petición en vuelo no vaya a llegar. OPERATION_EXPIRED para identidad retirada; nunca repetir automáticamente con ID nuevo. |
| FileAccessService.Open | OpenRequest(C,path,mode R/R_PLUS/W/W_PLUS/X/X_PLUS) → Handle(id,snapshot,mode,expiry,revision). | U según modo | Unary / 5 s / M | Fija snapshot; w/w+ publica vacío con exclusión/epoch; x/x+ crea exclusivamente. UNSUPPORTED_MODE, ALREADY_EXISTS, LOCK_BUSY. |
| FileAccessService.Close | HandleRequest(C,handle_id,expected_handle_revision) → MutationResult. | U dueño handle | Unary / 5 s / M | Libera handle/locks y referencias; **no confirma writes pendientes**. HANDLE_BUSY si hay write en curso, STALE_HANDLE. |
| FileAccessService.RenewHandle | HandleRequest(C,handle_id,expected_handle_revision) → Handle. | U dueño handle | Unary / 5 s / M | Renueva hasta TTL 60 s inicial; no modifica snapshot. STALE_HANDLE, VERSION_CONFLICT. |
| FileAccessService.BeginWrite | BeginWriteRequest(C,handle_id,base,offset presente,length presente 1..16 MiB,delta_sha256,fences≤5 o uno completo,parts 1..5) → WritePlan. Cada WritePart lleva block_index,block_offset,delta_offset,length,delta_sha256. | U w + dueño handle | Unary / 5 s / M | Reserva invisible, valida partición del delta sin huecos, bases tocadas y lock tamaño al crecer; SPARSE_WRITE_UNSUPPORTED, VERSION_CONFLICT, LOCK_EXPIRED, HANDLE_BUSY. write vacío se resuelve localmente tras validar handle, sin esta RPC. |
| FileAccessService.CommitWrite | CommitWriteRequest(C,operation,handle_id,changes 1..5,fences,expected_handle_revision) → CommitResult. Cada cambio base/replacement y 2..3 recibos según política final. | U w + dueño operación | Unary / 5 s / M | Une delta con raíz **vigente**, CAS/reintento interno de raíz si otros bloques cambiaron; actualización de handle y resultado en misma Txn. VERSION_CONFLICT en bloque solapado, LOCK_EXPIRED, INSUFFICIENT_REPLICAS, METADATA_QUORUM_LOST. |
| FileAccessService.AbortWrite | OperationRequest(C,operation) → MutationResult. | U dueño operación | Unary / 5 s / M | Descarta delta preparado; no revierte commits ajenos. VERSION_CONFLICT si ya COMMITTED. |
| FileAccessService.Lock | LockRequest(C,handle_id,whole_file o offset+length>0,wait_timeout_ms 0..5000) → Fence. Rango máximo cinco bloques; más exige lock completo. | U w + dueño handle | Unary / 6 s / M | Exclusión del conjunto ordenado atómica, TTL inicial 30 s; incluye lock de tamaño al crecer. LOCK_BUSY, STALE_HANDLE. Retardo de espera no altera recursos de la intención. |
| FileAccessService.Unlock | FenceRequest(C,fence) → MutationResult. | U dueño fence | Unary / 5 s / M | Libera solo misma generación/lease; LOCK_EXPIRED, LOCK_CONFLICT. No libera lock del sucesor. |
| FileAccessService.RenewLock | FenceRequest(C,fence) → Fence. | U dueño fence | Unary / 5 s / M | Renueva lease vivo, misma generación; no resucita lease vencido. LOCK_EXPIRED. |
| FileAccessService.ResolveBlocks | ResolveBlocksRequest(C,handle_id,snapshot,offset+length presentes,page≤64) → BlockPlan(snapshot,bloques/ubicaciones/permisos,next_cursor). | U r + dueño handle | Unary / 5 s / Q | Resolución dinámica del snapshot; rango se recorta en EOF, offset≥EOF devuelve plan vacío auténtico solo al implementarse. STALE_HANDLE, DATA_UNAVAILABLE. No tabla fija de ubicación cliente. |

### Bytes y coordinación de nodos (COM-02/04/05)

| Servicio.RPC · origen→destino | Solicitud → respuesta; campos/límites adicionales | Autorización | Tipo/plazo/retry | Confirmación futura y motivos adicionales |
| --- | --- | --- | --- | --- |
| BlockService.PutBlock · cliente→DN | PutBlockFrame(header(C,operation,block,fence,capability),chunks) → DurableReceipt. Total=block.size. | B WRITE_DATA | C-stream / 15 s / S | Copia local durable, hash verificado, no commit archivo; NO_SPACE, CHECKSUM_MISMATCH, LOCK_EXPIRED. |
| BlockService.PatchBlock · cliente→DN | PatchBlockFrame(header(C,operation,base,new_block_version_id,block_offset,delta_length 1..4 MiB,delta_sha256,fence,capability),chunks) → DurableReceipt con replacement y hash calculado por DN. | B WRITE_DATA + base interna autorizada | C-stream / 15 s / S | Crea bloque inmutable nuevo conservando bytes ajenos; tamaño=max(base.size,offset+delta)≤4 MiB; sin hueco. VERSION_CONFLICT, CHECKSUM_MISMATCH, NO_SPACE. Bloque completamente nuevo usa PutBlock. |
| BlockService.GetBlock · cliente→DN | GetBlockRequest(C,handle_id,snapshot,block,offset/length presentes y dentro del bloque,capability) → ReadBlockFrame(header, chunks). | B READ_DATA | S-stream / 15 s / Q | DN valida bloque completo antes de entregar rango; cliente valida §4. DATA_LOSS, DATA_UNAVAILABLE, STALE_HANDLE. |
| NodeRegistryService.RegisterNode · DN→CN | RegisterNodeRequest(C,node,capacity_bytes,free_bytes≤capacity,inventory_id) → NodeLease. Endpoints hostname/IP:puerto≤255 bytes y dominio de fallo permitido≤64 bytes. | N nodo inventariado | Unary / 5 s / M | Registro/revisión y boot_generation nueva; aún no replica ni declara inventario completo. PERMISSION_DENIED, VERSION_CONFLICT. |
| NodeRegistryService.Heartbeat · DN→CN | HeartbeatRequest(C,node_id,boot_generation,sequence creciente,free_bytes,active_streams) → NodeLease. | N propio DN | Unary / 3 s / M | Renueva liveness, propuesta cada 2 s/expira 10 s; no garantiza disco durable. VERSION_CONFLICT por generación/secuencia obsoleta. |
| NodeRegistryService.BlockReport · DN→CN | BlockReportRequest(C,node_id,boot_generation,report_id,page_index,receipts≤64,last_page) → MutationResult. Páginas≤64 KiB. | N propio DN | Unary / 5 s / M | Página registrada; inventario completo solo al último índice contiguo validado. CHECKSUM_MISMATCH, VERSION_CONFLICT. |
| NodeRegistryService.ReportDurable · DN→CN | ReportDurableRequest(C,receipt) → MutationResult. | N emisor recibo | Unary / 5 s / M | Registra ACK con boot/versión/hash; CN puede consultar VerifyReceipt, no confía en campos de cliente. OPERATION_EXPIRED, VERSION_CONFLICT. |
| NodeRegistryService.ReportTask · DN→CN | ReportTaskRequest(C,node_id,boot_generation,task,fence) → MutationResult. | N ejecutor autorizado | Unary / 5 s / M | Resultado de tarea registrado; FINISHED de réplica requiere recibo. LOCK_EXPIRED, VERSION_CONFLICT. |
| InternalAuthorizationService.AuthorizeBlock · DN→CN | AuthorizeBlockRequest(C,capability,session_token,action,node_id,block,offset,length,handle_id u operation_id; para patch además replacement_block_version_id,delta_sha256,fence) → AuthorizationDecision(subject_id,authz_revision,valid_until). Para PutBlock también fence vigente. | N propio DN + identidad U derivada token | Unary / 3 s / Q | Permiso consistente para stream limitado y plan exacto; PERMISSION_DENIED, UNAUTHENTICATED, STALE_HANDLE, LOCK_EXPIRED, METADATA_QUORUM_LOST. Nunca datos en esta RPC. |
| InternalAuthorizationService.AuthorizeInternal · DN→CN | AuthorizeInternalRequest(C,task_id,task_capability,action,source_node_id,destination_node_id,block,fence) → AuthorizationDecision. | T | Unary / 3 s / Q | Valida tarea/roles/origen/destino; PERMISSION_DENIED, LOCK_EXPIRED, OPERATION_EXPIRED. |
| StorageAdministrationService.VerifyReceipt · CN→DN | VerifyReceiptRequest(C,operation_id,receipt_id,block,expected_boot_generation) → DurableReceipt. | N control autorizado | Unary / 5 s / Q | Comprueba recibo/objeto durable persistido y coincidencia de identidad/hash. NOT_FOUND, DATA_LOSS, VERSION_CONFLICT. Un OK no impide fallo físico posterior. |
| StorageAdministrationService.ReplicateBlock · CN→DN ejecutor | ReplicateBlockRequest(C,task_id,block,source,destination,task_capability,fence) → TaskStatus. | T | Unary / 5 s / M | ACCEPTED/RUNNING solo admite tarea; **no suma copia** hasta FINISHED con recibo. NO_SPACE, LOCK_EXPIRED. Reparación usa esta misma RPC. |
| StorageAdministrationService.GetTask · CN→DN | GetTaskRequest(C,task_id) → TaskStatus. | N control autorizado | Unary / 5 s / Q | Estado durable propio; NOT_FOUND/OPERATION_EXPIRED, nunca FINISHED ficticio. |
| StorageAdministrationService.DeleteRetiredBlock · CN→DN | DeleteRetiredBlockRequest(C,task_id,block,retirement_revision,task_capability,fence) → TaskStatus. | T DELETE_RETIRED | Unary / 5 s / M | Solo objeto irreversiblemente retirado sin pins; FINISHED tras borrado durable/ausencia verificada de ese ID. NOT_RETIRED, LOCK_EXPIRED. |
| ReplicaService.StoreReplica · DN→DN destino | ReplicaFrame(header(C,task_id,block,ciphertext_length,ciphertext_sha256,key_id,task_capability,task_fence,destination_node_id),chunks) → DurableReceipt. Contenedor≤4 MiB+64 KiB. | T STORE_REPLICA | C-stream / 15 s / S | Copia verificada y durable del contenedor cifrado; CHECKSUM_MISMATCH, NO_SPACE, LOCK_EXPIRED. |
| ReplicaService.GetReplica · DN destino→DN origen | GetReplicaRequest(C,task_id,block,task_capability,task_fence,destination_node_id) → ReplicaFrame. | T READ_REPLICA | S-stream / 15 s / Q | Devuelve ciphertext de versión exacta y metadatos de cifrado; DATA_LOSS, DATA_UNAVAILABLE. Destino verifica hash y AEAD antes de ACK. |

### COM-03: contratos oficiales usados y semántica comprobada

No se redefine una API etcd propia. Los tipos, números, errores y servicios wire proceden de los contratos fijados en `third_party/`; el adaptador E2 accede directamente con gRPC, sin gateway/proxy y sin paquete Python etcd obsoleto. [etcd documenta CN del certificado para autenticación y roles por rango](https://etcd.io/docs/v3.6/op-guide/authentication/rbac/).

| API oficial · CN/probe→etcd | Solicitud/respuesta y límites adoptados por DFSha | Seguridad/plazo/reintento/confirmación |
| --- | --- | --- |
| etcdserverpb.KV.Put/Range/DeleteRange | PutRequest/Response, RangeRequest/Response, DeleteRangeRequest/Response; claves ≤1 KiB del prefijo autorizado; valores≤64 KiB, páginas≤64. Range sin serializable=true. | mTLS/RBAC; unary 3 s; Range Q, mutación con M/Txn en adaptación futura. Revisión de almacenamiento consistente, no commit del archivo por sí sola. |
| etcdserverpb.KV.Txn | TxnRequest(compare,success,failure) → TxnResponse(succeeded,header,responses). Diseño≤64 operaciones y≤1 MiB, revisar límite efectivo 128 ops/1.5 MiB etcd. | mTLS/RBAC; unary 3 s; comparación en transacción y resultado atómico. `succeeded=false` es resultado válido de condición rechazada, no error gRPC ni mutación aplicada. |
| etcdserverpb.Lease.LeaseGrant/LeaseRevoke/LeaseTimeToLive | Requests/Responses homónimos; ID int64, TTL segundos. Probe TTL=1/20; locks DFS propuestos 30 s. | mTLS/RBAC; unary 3 s; TTL puede ajustarse y expiración no es reloj exacto. Revoke solo lease propio. Grant no reintentar sin ID conocido. |
| etcdserverpb.Lease.LeaseKeepAlive | stream LeaseKeepAliveRequest(ID) ↔ stream LeaseKeepAliveResponse(ID,TTL). | mTLS/RBAC; stream con plazo renovado por sesión, no infinito; pendiente en adaptador distribuido, no prueba E2 de renovación. |
| v3lockpb.Lock.Lock/Unlock | LockRequest(name,lease)→LockResponse(key,header); UnlockRequest(key)→UnlockResponse. | mTLS/RBAC; unary 3 s en probe. Lock espera hasta deadline, mismo name/lease misma adquisición. Propiedad se compara por create_revision dentro de Txn; comparar antes no basta. |
| etcdserverpb.Watch.Watch | stream WatchRequest(create/cancel) ↔ WatchResponse(created/events/canceled/compact_revision). | mTLS/RBAC; prueba 5 s; Watch creado antes del Put, revision del evento comprobada. Al reconectar, retomar revisión o releer tras compactación; esa recuperación futura no está implementada. |
| etcdserverpb.Auth · bootstrap aislado | UserAdd/GrantRole, RoleAdd/GrantPermission, AuthEnable/Status, UserDelete/RoleDelete, mensajes homónimos `Auth…Request/Response`. | mTLS desde arranque; CN=root administra, dfsha-probe solo prefijo único, dfsha-denied sin permisos. Unary 3 s; bootstrap una vez en instancia nueva, no repetir ante estado desconocido. No tocar un clúster ajeno. |

Errores reales etcd de autorización `PERMISSION_DENIED`; TLS puede producir `UNAVAILABLE` antes de servicio; proceso detenido produce `UNAVAILABLE` o `DEADLINE_EXCEEDED` según detección/plazo del transporte. El wrapper conserva código y devuelve estado FALLIDO controlado. Los tests prueban conexión, CAS aceptado/rechazado, expiración, lock/unlock/fence obsoleto y Watch; no prueban HA, pérdida de mayoría, reconexión de Watch ni el MetadataStore definitivo.

## 4. Integridad, publicación y composición del SDK

En WritePlan, cada PlannedBlock con `patch=true` contiene en `block` la **base** con hash conocido y en `replacement_block_version_id` la identidad nueva reservada; `delta_offset`, `block_offset` y `delta_length` indican qué fragmento del write llega a ese DN. El resultado todavía no tiene hash: DN lo calcula y CN lo confirma mediante recibos. Para `patch=false`, `block` describe el bloque nuevo completo, cuyo hash/tamaño conoce el SDK por WritePart. AllocateBlocks/ResolveBlocks no usan los campos específicos de patch. El permiso opaco se vincula también a reemplazo y digest de la parte, enviados en AuthorizeBlock. El digest global del delta lo declara el SDK; los DN comprueban los digests de cada parte. CN valida cobertura, pero no puede reconstruir/verificar un SHA-256 global a partir de hashes parciales sin leer contenido y no afirma hacerlo.

Los Fence de handles incluyen handle_id; un upload completo o tarea interna sin handle lo deja vacío y se liga a operation_id/task_id en su registro. Expiry y wait_timeout_ms son políticas de espera renovables excluidas del digest; recursos, owner, generación y lease sí se incluyen. Para canonizar strings JSON se escapan comillas/backslash y controles (formas cortas `\b\t\n\f\r`, restantes `\u00xx` minúsculo), sin escapar `/` ni caracteres Unicode restantes. El orden de claves ASCII y estas reglas fijan una representación única; no se usa el orden wire Protobuf.

El SHA-256 de una página de manifiesto se calcula sobre la representación canónica de §2 del objeto `{"schema":"dfsha.manifest.page.v1","page_index":decimal,"blocks":[BlockRef…]}`; campos de BlockRef ordenados, índices crecientes y sin routing/recibos. La raíz usa `schema="dfsha.manifest.root.v1"`, file_id, content_epoch, total_bytes, block_count y lista ordenada de `{page_index,page_sha256}`. Los nombres son ASCII, números como strings decimales y hashes base64url. CN recalcula páginas/raíz y valida cobertura contigua; no acepta hashes que solo declara el cliente. Se puede calcular incrementalmente sin construir JSON/archivo completo en memoria. Páginas y sellado se fijan a operación hasta commit/abort/GC; los límites por Txn no crecen con el tamaño del archivo.

| Flujo | Valor esperado y quién verifica |
| --- | --- |
| PutBlock | SDK calcula longitud/SHA-256 del bloque; CN lo compromete en plan/manifiesto/capability. DN verifica bytes recibidos contra autorización y encabezado, cifra con AEAD, persiste objeto/recibo y recién confirma. CN contrasta recibo con emisor, época, hash y dominio. |
| PatchBlock | CN fija base/versión, rango y digest del delta; DN verifica delta y AEAD/hash de base contra metadatos autorizados; crea nueva versión, calcula SHA-256 del resultado y lo incluye en recibo. CN verifica recibos concordantes del mismo resultado. Ningún éxito de preparación modifica el archivo visible. |
| GetBlock completo | CN entrega SnapshotRef/BlockRef esperado por TLS tras ACL; DN verifica AEAD y SHA-256 **del bloque completo** antes del stream. SDK vuelve a calcular SHA-256 de todos los bytes y lo compara con BlockRef obtenido del CN, no con un hash arbitrario devuelto por DN. |
| GetBlock parcial | DN valida primero el bloque completo; después calcula range_sha256 sobre el rango. SDK comprueba versión, offset, longitud y hash de rango contra encabezado por TLS. Este hash de rango no es una prueba independiente del manifiesto: autoridad es DN autenticado que verificó AEAD/bloque. Para verificación independiente el SDK debe descargar el bloque completo. No prometer prueba Merkle de una fracción. |
| receive completo | SDK abre snapshot, obtiene todas sus páginas/bloques y verifica hashes de cada bloque, orden, tamaño y raíz de manifiesto. También calcula SHA-256 del archivo para evidencia local; compara con `SnapshotRef.file_sha256` **si está presente**. Tras write parcial ese hash opcional se elimina salvo que se recalcule leyendo todo el archivo; no conservar hash antiguo ni equiparar hash de raíz con hash de bytes. En pruebas se compara además con fixture original independiente. |
| ReplicaService | Origen autorizado entrega contenedor cifrado/longitud/ciphertext_sha256 vinculados a recibo/tarea. Destino comprueba SHA-256 del ciphertext, identidad/AAD, descifra/verifica AEAD y hash de plaintext esperado del manifiesto; confirma después de persistencia. Conocer un hash o recibir un chunk no acredita durabilidad. |

La durabilidad futura exige objeto temporal escrito, verificado y sincronizado, instalación inmutable y recibo persistido recuperable antes del ACK (fsync y garantías del FS a validar en Linux). Commit final verifica **W=2 copias en dominios distintos** por bloque y publica raíz, size, file_version/epoch, resultado e invalidaciones por una transacción de metadatos; R=3 es objetivo de reparación. W no es quórum etcd ni aporta consistencia por sí solo. H1 conserva almacenamiento local y política local explícita, sin fingir W=2.

`send/put` = BeginUpload + preparación de bloques/páginas + PutBlock a destinos + SealManifest + CommitUpload; `receive/get` = Open(R) + ResolveBlocks paginado + GetBlock + Close. `read(handle,offset,n)` resuelve rango del snapshot; `write(handle,offset,bytes≤16 MiB)` adquiere/valida locks, BeginWrite, PatchBlock/PutBlock a DN y CommitWrite. `cd` es estado del SDK tras Stat/validación del directorio, no RPC de sesión global. En monolito los puertos de control/datos pueden ser el mismo proceso; al distribuir, **los bytes van cliente–DN**, nunca mediante UploadService/FileAccessService.

Cada write confirmado actualiza el snapshot del handle escritor de forma serializada; handles ajenos conservan snapshot. Commits concurrentes en bloques distintos validan bases tocadas y componen delta sobre raíz vigente; solapados se serializan con lock y, si su base quedó obsoleta, fallan VERSION_CONFLICT. Crecimiento necesita lock de tamaño; offset>EOF no crea huecos. Commit compara epoch, ausencia de tombstone, condiciones de handle y **fence vigente en la misma transacción**. Cerrar libera; borrar no permite resurrección por solicitudes antiguas. Ninguna de estas reglas se considera implementada por el diagnóstico o por la prueba aislada de Lock de etcd.

## 5. Reproducción y evidencia

Generar/verificar con `python scripts/generate_proto.py` y `--check`; [entorno.md](entorno.md) identifica qué ejecutable usar en cada shell. El [catálogo generado](rpc-catalog.json) inventaría servicios, tipos y direcciones de stream; las tablas de este documento son la autoridad semántica. Pruebas y límites reales están en [evidencias de E2](evidencias/etapa2/README.md). El servidor escucha solo en loopback; TLS público/internal mTLS separados, sin servicios cloud ni publicación a Internet. No se eliminan validaciones de versión de código generado, verificación CA ni SAN.
# Actualización compatible de etapa 3

Aplican [D25–D29](etapa3-diseno.md). SnapshotRef añade block_size_bytes (8),
PlannedBlock añade reserva (9), Heartbeat añade métricas (7–9) y UploadService añade RenewUpload.
No se reutilizan números. Hay ahora 51 RPC propias. Los streams de bloques tienen plazos
30/120/240 s según perfil 4/64/128 MiB; el diagnóstico conserva sus límites anteriores.
La apertura R y su renovación/cierre son comandos porque persisten pins.
# Actualización E4: distribución con R=1/W=1

El contrato de E4 contenía 54 RPC. E5 añade BeginRead/EndRead (56 en total) para registrar la lectura activa como comando y serializar el handle en el control. El catálogo distingue H1, H2 y el perfil RF3; los resultados históricos conservan sus números originales. La implementación por sí sola no acredita una prueba.

## Contratos efectivos E5 (sustituyen propuestas RF3 anteriores)

| RPC | Solicitud/respuesta | Autorización | Transporte/deadline | Confirmación y errores |
| --- | --- | --- | --- | --- |
| FileAccessService.BeginRead | BeginReadRequest(context,handle_id,snapshot,offset,length) → ReadLease | Sesión dueña, modo lector y ACL vigente | Unary / 5 s; request_id idempotente | Registra ocupación del handle y snapshot en una transacción; HANDLE_BUSY, STALE_HANDLE, PERMISSION_DENIED, INVALID_ARGUMENT. |
| FileAccessService.EndRead | EndReadRequest(context,handle_id,read_id) → MutationResult | Misma sesión/handle | Unary / 5 s; idempotente | Libera solamente esa lectura; nunca confirma writes. |

La semántica vigente de Open, BeginWrite/CommitWrite/AbortWrite, locks, ResolveBlocks,
PatchBlock y lecturas está en [etapa5-rf3.md](etapa5-rf3.md). El delta admite hasta
16 MiB, incluso en bloques de 64/128 MiB; PatchBlock también crea la primera versión
de un bloque sin base. Deadlines de datos: 30/120/240 s por perfil. Los grants de
lectura ligan rango y read_id; PATCH_DATA es una acción distinta de READ_DATA.
El contexto mantiene la época estable de servicio y Fence usa la época de arranque
RF3. Los commits comprueban fences dentro de la transacción SQLite.

| RPC | Solicitud → respuesta | Acceso / efectos | Límite y confirmación |
|---|---|---|---|
| ClusterAdministrationService.ListNodes | ClusterQuery → NodeStatusPage | Consulta TLS, sesión admin; estado, métricas y contadores del control | Unary 5 s, ≤64 nodos/página; cero contenido de archivos |
| ClusterAdministrationService.CopyBlock | CopyBlockRequest → TaskStatus | Comando TLS, admin; persiste una tarea S/S autorizada y reserva | Unary 5 s; ACCEPTED confirma tarea, FINISHED confirma copia durable; request_id idempotente |
| ClusterAdministrationService.CopyStatus | GetTaskRequest → TaskStatus | Consulta TLS, admin; resultado persistido | Unary 5 s; reintento de lectura, sin comenzar otra copia |
