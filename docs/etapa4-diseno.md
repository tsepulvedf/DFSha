# D31–D35: etapa 4, decisiones previas a la implementación

Fuente: solicitud del usuario; no requisitos añadidos al PDF. Se conserva H1 y
sus datos. Raíces nuevas: control SQLite, tres o cuatro inventarios/volúmenes DN
independientes. Un proceso por nodo, TLS C/S y mTLS S/S; etcd no participa.

**D31 — Reutilización:** mismos Queries/Commands/SDK RF1/RF2, con puertos para
reservar/planificar, verificar recibos y retirar objetos. Control distribuido no
registra Put/Get ni dispone de la clave de contenido. Su sellado verifica
manifiesto y recibos autenticados; SHA-256 global declarado por SDK se verifica
al descargar, no se reconstruye combinando hashes parciales. Metadata y mapas
de ubicaciones separados: copiar un objeto no crea otro snapshot.

**D32 — Membresía:** identidades mTLS preautorizadas, endpoints exactos de inventario
administrativo, node_id estable y generación durable creciente. STARTING hasta
reconciliar todas las páginas del inventario; READY con heartbeat vigente,
SUSPECT y UNAVAILABLE por umbrales configurables del reloj del control. Reinicio
de control invalida frescura sin olvidar ubicaciones. Reinicio de DN conserva
objetos, verifica inventario y aborta uploads afectados de la encarnación anterior.

**D33 — Colocación:** reservar por bloque en transacción SQLite; espacio necesario
= plaintext + 4096 de cabecera + 20 por fragmento. Usado efectivo = máximo de
medición reciente y copias confirmadas contabilizadas; reservas solo preparaciones
sin recibo. Excluir no READY/frescura/capacidad/free. Comparar ocupación relativa
por bandas de 5 puntos porcentuales y streams activos; round robin persistido
entre candidatos comparables, evitando primario anterior cuando sea posible.
Cuotas por DN son de laboratorio, no discos físicos independientes en un host.
Caída durante upload: aborto de operación completo, no replanificación implícita.

**D34 — Autoridad y cifrado:** DN consulta AuthorizeBlock al control por cada stream,
con identidad mTLS y sesión/capability del cliente; permiso liga destino/generación
y snapshot u operación. Control inaccesible deniega autorización nueva. Stream ya
autorizado puede terminar hasta su deadline. Recibo persiste en inventario antes
del ACK y ReportDurable autenticado; reinicio permite recuperar recibos. KEK de
contenido compartida solo entre DN autorizados, copias privadas provisionadas
fuera de Git y fuera de directorios de bloques; clave de control distinta. No
transferir claves al cliente. Cifrado DFSHAB01 de H1 permanece intacto.

**D35 — Copia/GC:** administrador crea tarea persistente limitada a bloque/origen/
destino/digest/longitud/expiry. Destino pide ciphertext al origen por mTLS streaming,
verifica contenedor y plaintext incrementalmente con su KEK y confirma recibo antes
de añadir ubicación. Original permanece. Tareas idempotentes, máximo dos trabajos
simultáneos por DN. GC únicamente por orden persistida del control tras comprobar
ausencia de referencias/pins; perder heartbeat no autoriza borrar datos.

R1/W1 temporal; copia manual no es política R3/W2 ni reparación automática.
RF3 E5, réplica/repair E6, HA control E7, seguridad integral E8, cloud E9.
Q01–Q07 pendientes; modelo 2 de acceso omitido. Linux/Internet/host-failure no se
acreditan con procesos locales. Validar perfiles 4/64/128, varios clientes, 512 MiB
o 1 GiB, contadores por DN y cero contenido en CN, no cero tráfico de metadatos.
