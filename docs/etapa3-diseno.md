# Decisiones operativas de etapa 3, anteriores a la implementación

La concreción durante implementación es [D30 y contrato H1](protocolos-hito1.md):
serialización de intención/manifiesto, permisos, estados y plazos exactos. Las
decisiones aquí descritas se verifican en tests/test_hito1.py y medición separada.

Fuente: solicitud actualizada del usuario, 2026-09-08; **no son requisitos nuevos del docente**. Este documento actualiza las propuestas técnicas de E1/E2 y de la guía original, que se conserva intacta. Se omite «modelo 2 de acceso»: no se implementa ni queda como pregunta. Q01–Q07 permanecen sin respuesta docente.

## D25 — H1 y CQRS local

Un proceso servidor, SQLite autoritativa (WAL, synchronous=FULL, claves foráneas), repositorio transaccional, consultas autorizadas y comandos con validaciones/publicación. Consultas List/Stat/GetAcl/GetOperation/ResolveBlocks no escriben; Open(R), Close, RenewHandle, login/logout, namespace y uploads sí modifican estado. Sin proyecciones/event sourcing/framework/colas ni etcd requerido. Perfiles de diagnóstico E2 permanecen utilizables para regresión; H1 es configuración explícita separada. ControlNode corresponde al control NameNode de HDFS y DataNode a almacenamiento de bloques, con lógica/contratos DFSha propios.

## D26 — Archivos CRUD, bloques inmutables y perfiles

Crear/descargar/reemplazar explícitamente/eliminar archivos lógicos, no WORM estricto. Objetos `blocks/<file_id>/<block_version_id>.blk`, IDs UUID validados, nunca nombres del usuario. Manifiesto ordenado y ubicaciones confirmadas en SQLite; el listado físico solo sirve para GC/recuperación, no para reconstruir ubicaciones.

block_size_bytes persiste por archivo **y snapshot**: 4194304 predeterminado, 67108864 grande, 134217728 experimental. Overwrite conserva tamaño anterior aunque cambie perfil del servidor. Vacío sin bloques. Fragmento 262144 y futuro write 16777216 independientes. Perfil write/lock E5 calcula índices con tamaño del archivo; parches grandes cuestan más y la concurrencia tiene menor granularidad.

## D27 — Cifrado y presupuesto

Contenedor versión 1: header JSON acotado autenticado como AAD (identidad, longitud/hash plaintext, key_id, DEK envuelta y prefijo nonce); registros AES-GCM de hasta 256 KiB con contador/longitud autenticados. DEK nueva aleatoria por intento de objeto, nonce prefijo aleatorio + contador único dentro de esa DEK. Staging siempre cifrado. Antes de entregar datos se verifica integridad completa incremental; cada registro se autentica de nuevo antes de emitirlo. No plaintext temporal servidor. AES/keywrap/Argon2 de bibliotecas fijadas.

Clave maestra creada solo por inicialización administrativa explícita, persistida con permisos fuera de Git. Fingerprint en SQLite; clave ausente/cambiada rechaza arranque, nunca se reemplaza silenciosamente. Resultados de idempotencia con capacidades se cifran en SQLite; sesiones guardan hash, contraseñas Argon2id. SQLite/WAL contienen metadatos sin cifrado integral de volumen: se informa y queda pendiente E8, igual backups/rotación/recuperación operativa de claves.

Presupuesto de admisión servidor 384 MiB: reserva 128 MiB de intérprete/metadata/auth más cuatro unidades conservadoras de 64 MiB de trabajo. Stream 4 MiB cobra 1 unidad; 64 MiB cobra 2; 128 MiB cobra 4, permitiendo 4/2/1 streams. Los buffers reales son por fragmento, no por bloque. Dos verificaciones Argon2 simultáneas como máximo. Cliente serializa bloques por defecto y usa lectura incremental. Medir RSS/peak real en validación; admisión no equivale a una cuota del SO.

Deadlines bloque 30/120/240 s por perfil, explícitos y máximos; capacidades de upload/handle sujetas a estado y vencimiento servidor. Lease de operación 300 s renovable cada 30 s y máximo total 1 h; handle 300 s renovable cada 30 s; sesión inicial 1 h. Un stream ya autorizado puede terminar hasta su deadline; revocación se aplica al siguiente stream y en commit, sin renovar una sesión revocada. Sellado, que comprueba hash completo local, hasta 300 s. No SQLite abierta mientras viajan bytes.

## D28 — Atomicidad, pins, idempotencia y recuperación

BeginUpload reserva nombre/file_id y capacidad de objeto cifrado; overwrite compara versión/identidad y conserva publicación anterior. Bloques verificados/fsync antes de recibo; páginas/sellado invisibles. Commit corta transacción que revalida sesión, ACL, padre vivo, identidad/versión, reserva/operación y recibos locales, publica snapshot y persiste resultado idempotente juntos. R=1/W=1 **solo H1**. request_id único por actor/época en todo servicio, intención canónica recalculada; igual ID/digest devuelve respuesta original, distinto falla. No cambiar identidad al reintentar.

Open(R) persiste pin/snapshot; descarga temporal cliente se publica solo tras hash/longitud y sin perder destino anterior en fallos. rm marca tombstone e invalida uploads de esa identidad; lectores vigentes conservan versión y permisos retenidos. Reinicio aborta uploads no confirmados, libera reservas y limpia objetos no referenciados; **no promete reanudar un upload parcial**, conserva archivos confirmados y resultados. Pins/sesiones no vencidos persisten. GC respeta snapshots actuales, handles vigentes, uploads activos y streams locales. Inyección de fallos solo mediante configuración local de pruebas, nunca RPC pública.

## D29 — Colocación preparada, solo adaptador local ahora

Selección futura por salud/capacidad/ocupación/reservas/transferencias/dominio y frescura. Excluir caídos/métricas vencidas/sin capacidad real cifrado+temporal. Preferir menor ocupación relativa y trabajo, round robin entre comparables, rotar primarios sucesivos. Reservar transaccionalmente, validar disco también al almacenar, liberar/reconciliar en commit/abort/expiry. Separar plan provisional de mapa confirmado; lecturas/reparaciones consultan autoridad, nunca hash % membresía nueva. Es política propia DFSha, no algoritmo atribuido a HDFS.

E3 LocalPlacement reserva en SQLite con un nodo/host. E4 registro/heartbeats y selección entre nodos reales. Objetivo final R3/W2 y tres CN/tres etcd; W de datos no es mayoría metadata. Con tres DN y R3 completo cada DN puede tener todos los bloques; distribuir debe demostrar bloques separados y tráfico útil de lectura/escritura en varios nodos. Q02 para pequeños/vacíos permanece. Pruebas E4 usarán 512 MiB/1 GiB o suficientes bloques según perfil, no asumir que 64 MiB siempre cruza bloques.

Cinco relaciones: cliente–CN metadata; cliente–DN bytes (colocalizados en H1, directos E4); CN–CN mediado etcd E7; CN–DN control/registro E4; DN–DN réplica E6. Ninguna relación distribuida se declara implementada en H1. RF3 avanzado/PatchBlock/locks públicos E5; réplica E6; control HA E7; seguridad integral E8; cloud E9.
