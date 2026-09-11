# Contrato operativo H1 (etapa 3)

E5 añade dos contratos de soporte de lectura: catálogo total 56. H1 mantiene
sus 30 implementaciones y 26 métodos futuros; las nuevas reglas RF3 se activan
en el perfil distribuido `--rf3`, documentado en [E5](etapa5-rf3.md).

Este es el perfil monolítico preservado. Los 51 métodos mencionados abajo son
el catálogo histórico de E3. Con las extensiones aditivas de E4 hay 54: H1
mantiene 30 implementados (incluido diagnóstico) y 24 futuros. La administración
de clúster no se implementa en H1. Para comunicaciones distribuidas vigentes,
reglas E4 y evidencia usar [protocolos-hito2.md](protocolos-hito2.md).

Este documento y [D25–D30](etapa3-diseno.md) actualizan las propuestas E2 de
[protocolos.md](protocolos.md). No son nuevos requisitos del PDF. Wire `dfsha.v1`,
51 métodos: **27 de negocio H1, tres de diagnóstico y 21 futuros UNIMPLEMENTED**.
El perfil de diagnóstico conserva todos los métodos de negocio UNIMPLEMENTED.
Los números de campo anteriores se conservan; stubs regenerados, nunca editados.

## Comunicaciones y efectos

| Relación | Servicios / RPC | Implementación H1 | Seguridad y errores |
| --- | --- | --- | --- |
| COM-01 cliente–control | Authentication Login/Logout; Identity CreateUser/SetUser/CreateGroup/SetGroupMembers/GetAcl/SetAcl; Namespace List/Stat/Mkdir/Rmdir/Remove; Upload BeginUpload/AllocateBlocks/StageManifestPage/SealManifest/CommitUpload/AbortUpload/GetOperation/RenewUpload; FileAccess Open(R)/Close/RenewHandle/ResolveBlocks | 25 RPC con SQLite autoritativa, mismo proceso | TLS CA/SAN; sesión, permisos y revisión; errores estables de E2 |
| COM-02 cliente–bloques | BlockService PutBlock/GetBlock | Dos RPC, módulo de bloques del mismo servidor; endpoint devuelto en plan | TLS, sesión y capability ligada a actor/operación o handle/bloque/acción/época; permiso revalidado |
| COM-03 control–control | CN → etcd → otros CN, KV/Txn/Lease/Watch | Pendiente E7; probe E2 independiente preservado | mTLS/RBAC; quórum final no probado |
| COM-04 control–bloques | Registro/heartbeats, inventario, recibos, autorización interna y tareas | Pendiente E4; llamadas locales entre módulos en H1 | Listener interno mTLS, RPC futuras UNIMPLEMENTED; no rol distribuido ficticio |
| COM-05 bloques–bloques | ReplicaService StoreReplica/GetReplica | Pendiente E6 | mTLS y capacidades de tarea futuras |

RefreshSession, modos distintos de R, BeginWrite/CommitWrite/AbortWrite, locks,
PatchBlock y todos los métodos de nodos/réplicas conservan UNIMPLEMENTED. Open con
modo distinto de R produce INVALID_ARGUMENT/UNSUPPORTED_MODE. GetBlock H1 exige
bloque completo; los rangos parciales son E5. SDK send/receive componen RPC de
control y bloques; no crean una RPC que transporte archivos dentro del control
distribuido. cd/pwd pertenecen al cliente: cwd lógico e identidad, nunca `chdir`
del servidor. Stat de directorio exige x; List exige r+x; Stat de archivo exige r.

## Campos, límites, confirmaciones e idempotencia

Los tipos, campos y restantes motivos por RPC están en las tablas de
[protocolos.md](protocolos.md). Estas reglas sustituyen sus propuestas anteriores
incompatibles para H1:

- Bloque 4194304, 67108864 o 134217728 bytes según **archivo**, persistido también
  en SnapshotRef.block_size_bytes. Último bloque con longitud real, vacío sin
  bloques. Overwrite conserva perfil. Máximo de archivo configurado 16 GiB;
  fragmento 262144, mensaje gRPC máximo 1 MiB, futuro write 16777216 independiente.
- PutBlock: header primero; fragmentos exactamente 256 KiB salvo último, offsets
  contiguos y hash/longitud del plan. Evita que fragmentos diminutos excedan la
  reserva por sobrecarga criptográfica. ACK después de fsync y recibo/ledger SQLite.
- Upload Begin reserva destino y capacidad cifrada. Allocate ≤64 bloques, Stage
  páginas consecutivas de 64 salvo última, ≤64 KiB. Seal comprueba cobertura,
  hash del manifiesto y **hash de todo el archivo leyendo bloques locales** fuera
  de la transacción; esto es específico del monolito. El control distribuido E4
  no podrá verificar ese hash leyendo contenido a través de su API de control.
- Commit revalida sesión, permisos, identidad/versión base, padre vivo, operación
  no vencida, sello y recibos locales; publica snapshot/namespace y ledger en la
  misma transacción. R=1/W=1 local. No hay transacción durante la transferencia.
- Unary tiene deadline solicitado obligatorio ≤5 s; Seal ≤300 s. Validación del
  deadline recibido admite 2 s de margen de representación/conversión de reloj:
  se observó 300,999... s para una llamada de 300 s y rechazo intermitente justo
  alrededor de 301 s. No cambia los plazos del SDK ni permite llamadas ilimitadas.
  Put/Get solicitan máximo 30/120/240 s por perfil, con el mismo margen. SDK reintenta UNAVAILABLE hasta
  tres intentos, espera 100/200 ms; cada intento usa su deadline acotado y la misma
  solicitud. Un timeout puede tener resultado desconocido: consultar GetOperation
  y reintentar Commit con **su mismo request_id**. No se reintenta automáticamente
  una descarga interrumpida: el temporal se descarta, puede iniciarse otra descarga.
- Operación TTL 300 s, renovación cada 30 s, vida máxima una hora; handle TTL 300 s
  renovable cada 30 s; sesión una hora. RefreshSession pendiente: volver a login.
  Stream autorizado puede terminar hasta su deadline; operaciones siguientes y
  commit revalidan. Renew no resucita una operación abortada/vencida.
- Sesión `authorization: Bearer <base64 estándar con padding>` de token aleatorio
  32 bytes; únicamente SHA-256 en tabla de sesiones. Login no idempotente; Logout
  sí permite recuperar el resultado original con la misma solicitud revocada.
  SDK verifica el canal con DiagnosticService.Health, presupuesto separado de 10 s
  antes de Login; autenticación conserva 5 s y no se reintenta automáticamente.
  Health no acredita RF1/RF2; evita un hilo de suscripción de conectividad cuyo
  cierre concurrente produjo una advertencia en gRPC Windows durante las pruebas.
  Evita consumir el plazo de autenticación al establecer una conexión fría.
- Usuario/grupo ASCII `[A-Za-z0-9_-]{1,64}` en este hito; rutas admiten Unicode NFC.
  Contraseña UTF-8 12..1024 bytes, Argon2id t=2, m=19456 KiB, p=1, hasta dos
  verificaciones simultáneas. Administrador inicial por bootstrap explícito.
  Cada usuario obtiene grupo propio y `/home/usuario` 700; archivos nuevos 600.
  Administrador puede gestionar grupos/usuarios; propietario o administrador ACL.
- List limita 100 entradas y cursor ≤512 bytes ligado a usuario/directorio/revisión
  e identidad del último hijo. Resolve limita 64; cursor índice dentro del snapshot
  autenticado de la solicitud, sin tabla de ubicaciones en cliente.
- Estados PREPARING/COMMITTED/ABORTED/EXPIRED son reales; GetOperation consulta por
  operation_id o request_id original de Begin. Resultado de cada mutación está en
  ledger persistente, cifrado con AES-GCM. Conservación del ledger/tombstones durante
  el proyecto; no equivale a retener los bloques para siempre.

### D30: representación efectivamente implementada

La clave global de ledger es `(service_epoch, usuario autenticado, request_id)`;
el método se compara además en el registro. El digest H1 es SHA-256 del JSON UTF-8
de `MessageToDict(..., preserving_proto_field_name=True)`, limpiado recursivamente
de campos `context`, `password`, `capability`, `expires_at_unix_ms`. Claves ordenadas,
separadores `,` y `:`, Unicode NFC sin escape ASCII. Se omiten defaults proto3 sin
presencia; opcionales presentes, incluido cero, se conservan. uint64 son strings
decimales, uint32 números, enums nombres y bytes base64 estándar. Esta regla se
prueba con la toolchain fijada; sustituye la propuesta de envoltura JSON E2 que
nunca tuvo clientes funcionales. E4 deberá mantenerla o versionar explícitamente.

Incluye rutas/cwd, ID de operación/file/handle/bloque, revisiones, época de contenido,
offsets, longitudes, hashes, flags overwrite, snapshot, páginas/sello, ACL y fence
(salvo vencimiento). Actor/época se autentican y ligan al ledger aunque no se
repitan dentro del digest; método distinto también falla IDEMPOTENCY_MISMATCH.
CreateUser compara adicionalmente el verificador Argon2id original, para que cambiar
la contraseña no se convierta en un reintento válido. Cada sub-RPC tiene su ID;
OperationRef conserva la identidad de Begin. Los chunks quedan comprometidos por
SHA-256 y longitud del header; no se incluyen bytes del archivo en JSON.

Página y raíz del manifiesto usan SHA-256 del JSON canónico de la lista ordenada
de BlockRef (misma conversión protobuf); raíz = lista completa, página = su tramo.
BlockRef contiene file_id, block_version_id, índice, longitud y hash plaintext.
Snapshot liga además tamaño de bloque/archivo, epoch y versión. H1 mantiene esa
metadata en memoria O(número de bloques), acotada por máximo 16 GiB; nunca contenido
O(tamaño del archivo). No aplicar la fórmula de raíz E2 a objetos creados por H1.

## Integridad, publicación local y almacenamiento

Control fija hash esperado de cada bloque y hash del archivo en snapshot. DN local
verifica identidad, longitud y SHA-256 contra metadata autoritativa; autentica el
contenedor completo incrementalmente **antes del primer plaintext** y autentica
cada registro de nuevo al emitirlo. SDK verifica header, offset/longitud, hash de
cada bloque, raíz de manifiesto y hash total antes de publicar el temporal local.
Get parcial futuro deberá verificar primero el bloque entero y usar el hash de
rango del servidor autenticado; ese hash solo no sustituye el SHA-256 del bloque.

DFSHAB01: magic 8 bytes, longitud header uint32 big endian, JSON ≤4096 bytes con
version, file_id, block_id, size, sha256, key_id, wrapped_dek y nonce_prefix. Cada
registro tiene uint32 longitud ciphertext y AES-GCM(plaintext≤262144, tag16), AAD
header exacto + índice uint32 + longitud plaintext uint32. Nonce = prefijo aleatorio
8 bytes + contador4, DEK aleatoria32 por intento, envuelta con AES key wrap y KEK32
persistente. No se reutiliza DEK entre objetos/intentos. Staging y bloques cifrados.

SQLite WAL/FULL persiste árboles, permisos, sesiones hashed, snapshots, asignaciones,
reservas, recibos y ledger cifrado. Índice único de nombre vivo y transacciones
BEGIN IMMEDIATE evitan carreras; consultas usan lectura transaccional consistente.
SQLite/WAL contienen metadatos legibles y hashes; **no hay cifrado integral del
volumen demostrado**. Directorios/claves tienen ACL del usuario actual, SYSTEM y
Administradores en Windows; 700/600 en POSIX preparado. Backup/rotación/custodia
externa/volúmenes cifrados y seguridad integral siguen pendientes E8.

Descarga publica por os.replace con overwrite, o enlace duro atómico sin reemplazo
en NTFS/POSIX; requiere soporte de hardlinks en el destino. Un fallo conserva el
destino anterior y borra el temporal propio. Reinicio aborta uploads sin commit,
libera reservas y recoge objetos sin referencias. Preserva usuarios/sesiones,
manifiestos, clave y pins vigentes. GC cada 10 s respeta snapshots actuales, pins,
operaciones activas y streams abiertos. No reanuda uploads interrumpidos.

fsync se ejecuta antes del recibo; POSIX incluye fsync del directorio. Windows
verifica recuperación ante caída de proceso; durabilidad ante pérdida eléctrica
del hardware/NTFS no está medida. Un bloqueo exclusivo de raíz evita dos monolitos
usando simultáneamente la misma SQLite. R=1 es punto único de fallo declarado.
