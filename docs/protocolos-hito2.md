# Protocolos ejecutables de H2 / etapa 4

La corrección [D44 de E5](etapa5-rf3.md) conserva registro ante pérdida de respuesta
de heartbeat. Nuevas colocaciones siguen exigiendo READY; ubicaciones ya reservadas
o confirmadas pueden atender transferencias en SUSPECT con autorización online y
generación válida. STARTING/UNAVAILABLE permanecen excluidos. La reinscripción se
reserva para rechazo explícito de registro/generación o arranque del proceso.

Estado: implementación E4 comprobada en Windows mediante [100 pruebas y medición real](evidencias/etapa4/README.md). Complementa [el contrato general](protocolos.md), [H1](protocolos-hito1.md) y las [decisiones E4](etapa4-diseno.md). Los requisitos provienen del PDF; el algoritmo de colocación y estas extensiones son decisiones del equipo solicitadas por el usuario. El catálogo marca implementación, no aprobación individual automática de cada RPC. Las cuatro relaciones C–CN, C–DN, CN–DN y DN–DN se ejercitaron con conexiones; CN–CN sigue pendiente.

## Relaciones y servicios

| Relación | Servicios / RPC | Seguridad | Estado E4 |
|---|---|---|---|
| Cliente–ControlNode | Authentication, Identity, Namespace, Upload, FileAccess R/Close/Renew/Resolve; ClusterAdministration ListNodes/CopyBlock/CopyStatus | TLS CA/SAN + Bearer; ACL H1; administración requiere admin | Implementación E4; RF3 restante UNIMPLEMENTED |
| Cliente–DataNode | BlockService.PutBlock/GetBlock | TLS CA/SAN; Bearer y capability; DN consulta AuthorizeBlock por mTLS antes de cada stream | Implementación de streaming directo; PatchBlock pendiente E5 |
| ControlNode–ControlNode | Contratos de coordinación, mediación futura etcd | mTLS previsto | PENDIENTE E7; una SQLite, un control, sin etcd requerido |
| ControlNode–DataNode | RegisterNode, Heartbeat, BlockReport, ReportDurable, ReportTask, AuthorizeBlock, AuthorizeInternal, VerifyReceipt, ReplicateBlock, GetTask, DeleteRetiredBlock | mTLS, identidad CN del certificado contra lista administrativa; roles por API | Implementación E4; copia ordenada, sin reparación automática |
| DataNode–DataNode | ReplicaService.GetReplica, destino inicia pull del contenedor cifrado | mTLS destino autorizado en tarea; origen vuelve a consultar al control | Implementación E4; StoreReplica queda UNIMPLEMENTED; no hay ACK de réplica por simple cierre del stream |

## Campos, validación y tiempos

Los tipos protobuf están en `proto/dfsha/v1/`. No se reutilizaron números. `BlockLocation.client_endpoint` es la dirección C/S; `private_endpoint` sirve S/S; los binds solo describen dónde escucha el proceso. El laboratorio anuncia localhost porque todos sus participantes están en el mismo host; esto no sirve para clientes externos. Los certificados verifican localhost/127.0.0.1 mediante SAN; no se reemplaza el nombre esperado.

`RegisterNode`: UUID node_id e inventory_id, generación >0, endpoints, dominio y capacidad exactamente preautorizados. El CN del certificado debe corresponder al node_id; no se usa la dirección TCP como identidad. Una encarnación antigua devuelve ABORTED/VERSION_CONFLICT. La misma encarnación solo puede repetir su registro exacto. STARTING no puede aceptar planes: requiere todas las páginas del inventario. `BlockReport`: ≤64 recibos y ≤64 KiB, report_id estable por arranque y páginas secuenciales. Un reporte desconocido no publica archivos ni crea ubicaciones por inferencia.

`Heartbeat`: generación vigente, secuencia creciente, usado/libre/reservado, streams activos y cuatro contadores de bytes. El control usa su reloj al recibirlo. Intervalo de laboratorio 0,5 s, SUSPECT después de 2,5 s y UNAVAILABLE después de 6 s sin renovación; parámetros configurables en el control. El reinicio de control exige reconciliación otra vez. El reinicio de DN incrementa generación durable y aborta uploads de su generación anterior. Los datos publicados y recibos conservan su identidad; inventariarlos permite recuperar ubicaciones válidas.

`AllocateBlocks`: continúa siendo comando CQRS de H1, ≤64 bloques; cada destino se reserva en la misma transacción corta. `PutBlock` recibe header seguido por fragmentos ≤262144 B (salvo el último, exactamente ese tamaño); cada offset es el desplazamiento de transporte. Bloques por archivo de 4194304/67108864/134217728 B; límite futuro write 16777216 B permanece independiente. Los streams tienen deadline máximo de perfil 30/120/240 s más tolerancia de codificación gRPC, autorización viva y backpressure. Renovación de upload/handle cada 30 s mantiene sus leases de 5 min, máximo 1 h de upload.

`AuthorizeBlock` transporta el RequestContext del usuario y el token de sesión; la identidad del DN proviene de mTLS, no de ese contexto. WRITE valida operación, allocation, destino/generación, fence, usuario/sesión, ACL e intención; READ valida handle/snapshot fijado, pertenencia exacta del bloque y ubicación confirmada. La capability HMAC vincula usuario, sesión, operación/handle, block_version_id, acción y encarnación de destino. Conocer bloque/endpoints no autoriza. El control verifica expiración/revocación en cada autorización. Un stream autorizado termina como máximo en su deadline y vencimiento concedido; no hay renovación offline. Control inaccesible: nuevas autorizaciones fallan de forma controlada.

`ReportDurable` lleva contexto interno y contexto original del PutBlock, operación y fence. El DN persiste contenedor cifrado y recibo/inventario SQLite FULL antes de reportar. Control valida identidad mTLS del emisor, generación, operación activa, intención original, bloque asignado, tamaño/digest y reserva. Guarda bloque, ubicación y ledger PutBlock en una transacción; no acepta conteos del cliente como prueba. `VerifyReceipt` es consulta privada solo del control y permite recuperar el recibo tras reinicio. La publicación final de snapshot/resultados/namespace sigue siendo atómica y única, usando las transacciones de H1.

## Integridad e idempotencia

SHA-256 del plaintext de cada bloque proviene de la fuente estable del SDK y queda en BlockRef/manifiesto. El DN lo comprueba al escribir y al descifrar el contenedor completo antes de servir plaintext. El SDK compara cabecera, longitud y hash contra el manifiesto del snapshot. SHA del archivo completo se verifica en el SDK al descargar; el control verifica orden, tamaños, manifiesto y recibos durables, **no recomputa SHA del archivo leyendo bytes**. El hash del contenedor cifrado del recibo se usa para copia S/S, distinto del hash lógico.

Al copiar, el destino descarga el contenedor completo por GetReplica en fragmentos, verifica SHA de ciphertext esperado en la tarea/recibo de origen, desenvuelve la DEK con su propia copia autorizada de KEK y verifica todos los tags AES-GCM, identidad, longitud y SHA plaintext. Solo entonces confirma inventario y ReportTask. Añadir ubicación no cambia snapshot ni versión lógica.

El alcance de request_id sigue siendo `(service_epoch, user_id, request_id)`, global entre comandos y PutBlock. El digest canónico excluye contexto, credenciales, capabilities y vencimientos emitidos por servidor; incluye operación, identidad del bloque, tamaño, SHA y fencing. Reutilizar la identidad con otra intención devuelve ALREADY_EXISTS/IDEMPOTENCY_MISMATCH. La respuesta perdida después de CommitUpload se recupera por ledger, sin segundo snapshot. Copia/borrado se identifican por task_id persistido; reintentar la entrega no crea otra tarea. ACCEPTED nunca significa copia confirmada.

Errores: UNAUTHENTICATED para sesión inválida; PERMISSION_DENIED para rol/capability/destino ajeno; ABORTED/VERSION_CONFLICT para encarnación/intención incompatible; RESOURCE_EXHAUSTED/NO_SPACE para cuota/espacio; DATA_LOSS/CHECKSUM_MISMATCH para integridad; UNAVAILABLE/DATA_UNAVAILABLE o SERVICE_UNAVAILABLE para copia/servicio inaccesible; FAILED_PRECONDITION/OPERATION_EXPIRED para upload vencido; futuros UNIMPLEMENTED/NOT_IMPLEMENTED_STAGE2. APIs internas unary usan plazos ≤5 s en clientes del sistema; el dispatcher usa 2 s y reintento en el siguiente ciclo. Streams S/S ≤240 s y tarea ≤5 min.

## Fallos y limpieza

No se replanifica en E4: un fallo de subida lleva a AbortUpload, libera las reservas activas y deja visible la versión anterior. Reiniciar control aborta PREPARING, conservando resultados COMMITTED y pins vigentes. Reiniciar DN invalida destinos de su encarnación previa. Un mensaje tardío no revive operaciones abortadas ni tombstones. La descarga vuelve a consultar ubicaciones del mismo bloque/snapshot y descarta solamente sus bytes temporales incompletos; si no queda una copia accesible devuelve indisponibilidad. No reconstruye ubicaciones con hashes.

El control persiste tareas de borrado cuando ya no hay snapshots/pins/operaciones que retengan el objeto. El DN exige la tarea autorizada y pin exclusivo para borrar. Un DN desconectado no borra por falta de heartbeats. Al reiniciar elimina solamente staging interrumpido de su propio volumen y reporta objetos cifrados persistidos sin índice para decisión del control. Objetos corruptos se conservan para diagnóstico, no se reportan como disponibles. Reparación automática, retención administrativa y política de claves completa siguen pendientes.

## Custodia y evidencia

La lista autorizada y endpoints son configuración del control, nunca catálogo de bloques del cliente. Clave de metadatos del control diferente de la KEK de contenido; cada DN obtiene una copia privada autorizada de esta última, fuera de volúmenes de bloques y Git. CA privada solo en aprovisionamiento del laboratorio; cada proceso recibe únicamente su certificado/clave y CA pública. El cliente recibe solo CA pública. Todos corren bajo el mismo usuario del laboratorio: las ACL no aíslan procesos frente a un administrador del host. SQLite/inventarios/WAL no están cifrados por la aplicación; requieren protección de volumen/backups E8. TLS y bloques cifrados no completan RNF6.

La autoridad de identidad procede de [gRPC AuthContext](https://grpc.github.io/grpc/core/md_doc_server_side_auth.html) y [la API Python de gRPC](https://grpc.github.io/grpc/python/grpc.html). No se modificaron dependencias ni algoritmos criptográficos de H1.
