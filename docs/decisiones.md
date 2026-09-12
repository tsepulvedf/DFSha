# DFSha — Registro de decisiones y fuentes técnicas

Actualización 2026-09-12: **[D45–D50](etapa6-replicacion.md#decisiones-d45d50)**
adoptadas en E6: política persistida R3/W2, dominios administrativos explícitos,
commit por bloque, tareas con época y reconciliación, salud/cuarentena/GC y
promoción desde R1. Implementación: control/replication.py, autoridad existente,
SDK y DataNodes. 130 pruebas de regresión aprobadas; verificaciones complementarias
y medición en [evidencias E6](evidencias/etapa6/README.md). Stack fijado sin cambios.
Un solo control y un solo host son límites deliberados del laboratorio; Q01–Q07
sin aclaraciones docentes nuevas. Los apartados E1–E5 conservan su contexto histórico.

Actualizado 2026-09-11 · Etapas 1–5. [D36–D44](etapa5-rf3.md) implementadas y
verificadas en Windows local: RF3, fencing, parches y continuidad de heartbeats.
114 pruebas aprobadas; evidencia y límites en [estado](estado.md).
D25–D30 implementan RF1/RF2 H1 y sustituyen
propuestas anteriores incompatibles: [diseño](etapa3-diseno.md) y [contrato](protocolos-hito1.md).
E4 adopta [D31–D35](etapa4-diseno.md): adaptación de CQRS H1 sin contenido en
control; identidades/encarnaciones e inventarios; colocación por ocupación y
reservas; autorizaciones/recibos durables; copia y GC por tareas persistidas.
Son decisiones del equipo, no nuevas exigencias atribuidas al PDF. El algoritmo
de colocación no se atribuye a HDFS. Compatibilidad/estado en [entorno.md](entorno.md) y
[estado.md](estado.md). [Original E1](evidencias/etapa1/documentos-originales.zip) preservado.

<a id="base"></a>
## Base documental y decisiones previas

Al iniciar solo existían el [PDF](enunciado/SI3007-262-proyecto1-dfs.docx.pdf) y la [guía de prompts](propuesta/Prompts_Codex_DFSha_Opcion1_CS.md). No había código, configuración, registro de decisiones, estado ni repositorio Git inicializado. No se encontró una decisión técnica previa del equipo distinta de la elección explícita del usuario por la opción 1. No hay cambios anteriores de código que migrar en esta etapa.

| Material o afirmación | Clasificación correcta |
| --- | --- |
| RF1–RF3, RNF1–RNF7, opción 1, comunicaciones, entregables y cronograma | Requisitos del PDF; extraídos en [matriz-requisitos.md](matriz-requisitos.md). |
| RNF8 y aspectos de seis criterios de evaluación | Espacios con `…`; no hay contenido adicional que implementar. |
| NameNode central, CLI, «solo sus propios archivos», arquitectura tipo HDFS (p. 4) | Ejemplo ilustrativo. No elimina compartir mediante grupos/ACL ni obliga a un control único. |
| NFS, AFS, SMB; bloques frente a objetos (pp. 2–3) | Marco teórico. No obliga a usar esos sistemas ni POSIX. La denominación de WORM en p. 3 se conserva como texto del enunciado; no fundamenta la semántica de DFSha. |
| REST, gRPC, WebSockets y MOM (p. 5); Linux, Docker, FastAPI/Flask, Kafka/RabbitMQ, bases de datos (p. 7) | Alternativas y recursos sugeridos. No son una lista acumulativa de dependencias. |
| Python, 4 MiB, R=3/W=2, etcd, TLS/mTLS y once etapas de la guía | Propuestas técnicas/de planificación, varias también propuestas explícitamente por el usuario. Se adoptan o ajustan abajo. |
| Historial de conversaciones y temas estudiados mencionados por la guía | No accesible/verificado en esta sesión. No se trata como una decisión anterior. |

<a id="adr"></a>
## Decisiones adoptadas para el diseño

| ID | Decisión y razón | Alternativa evaluada / consecuencia | Trazabilidad |
| --- | --- | --- | --- |
| D01 | **Opción 1, organización única, C/S y composición S/S privada.** Es la elección USR y satisface la opción del PDF. | P2P federado queda fuera de alcance. La API de usuario es documentada; interfaces internas conservan control administrativo. | OP-01; [arquitectura §2](arquitectura.md#a2). |
| D02 | **Monolito modular antes de distribuir.** Conserva el hito 1 oficial y hace demostrable RF1/RF2 completos. | Separar procesos desde el primer hito omitiría su condición monolítica. Interfaces reemplazables permiten evolución. | H-08, H-10; [arquitectura §1](arquitectura.md#a1). |
| D03 | **Python 3.12.10, grpcio/grpcio-tools 1.83.1 y Protobuf 7.36.1, CLI/SDK propios.** Candidato 3.12 validado conjuntamente en E2; versiones transitivas con hashes. | REST/FastAPI también puede cumplir. No se afirma superioridad de rendimiento sin medir. Cliente implementado solo de diagnóstico; SDK funcional E3. | COM-01–05, F01–F06; [entorno y resultados reales](entorno.md). |
| D04 | **SQLite local en H1; etcd v3, familia 3.6, como destino de metadatos/coordinación.** SQLite simplifica el monolito; etcd aporta autoridad replicada y Txn/Lease. | SQLite compartido por red no se considera solución HA. Una base relacional con HA sería alternativa válida, pero requeriría su diseño/operación y otro adaptador. | RNF2/3; [arquitectura §3](arquitectura.md#a3); F07–F12, F20. |
| D05 | **API oficial etcd 3.6.14 y stubs de la misma toolchain.** E2 verifica imports, KV/Txn, Lease/Lock/Watch y TLS/mTLS/RBAC reales; wrapper aislado de compatibilidad. | Originales/URLs/hashes/licencias preservados; imports adaptados solo en copias de build, sin editar stubs. No fue necesario gateway ni un cliente Python antiguo. Reconexión/HA y adaptadores definitivos siguen E7. | F03, F08–F13; [procedencia](../third_party/README.md), [pruebas](evidencias/etapa2/README.md). |
| D06 | **Tres ControlNodes activos y tres miembros etcd.** Todo estado de control se comparte; mantenimiento tiene lease exclusivo. | No hay elección casera de CN por heartbeats ni SQLite local autoritativo. CN–CN se comunica indirectamente por etcd; aclaración Q05 registrada. | RNF2/3, COM-03; [arquitectura §4](arquitectura.md#a4). |
| D07 | **Bloques de 4 MiB, fragmentos de 256 KiB, concurrencia 4 con límite global.** Tamaño configurable y memoria proporcional a trabajo activo. | Cargar archivos completos en RAM incumpliría metas grandes. No usar bloques del tamaño del mensaje máximo gRPC. Estos números son DIS, no PDF. | RNF1/4/5; [arquitectura §5](arquitectura.md#a5). |
| D08 | **R=3 objetivo, W=2 durable en dominios distintos antes de publicar.** Permite confirmar con un DN caído y reparar luego. | W=3 daría tres copias iniciales pero bloquearía escrituras con un nodo caído; W=1 no tolera perder su único host. W no es mayoría etcd ni prueba de consistencia. | RNF2/3; [arquitectura §6](arquitectura.md#a6). |
| D09 | **Bloques y páginas de manifiesto inmutables; publicación de raíz por CAS.** Evita versiones parciales/mezcladas y actualizaciones perdidas; permite snapshots. | Reescritura in situ o manifiesto ilimitado en una clave complicaría recuperación y límites etcd. GC debe respetar referencias. | RF2/3, RNF3; [arquitectura §3](arquitectura.md#a3). |
| D10 | **Snapshot fijado al abrir; cada write confirmado publica; close solo libera.** Contrato uniforme y observable, sin buffer oculto pendiente de close. | Consistencia «solo al cerrar» cambiaría la visibilidad solicitada y no se adopta. Un send completo mantiene una transacción propia, no commits visibles por chunk. | RF2/3; [especificación §5–6](especificacion.md#s5). |
| D11 | **Locks por bloque y lock completo, con lease/fencing; delta sobre versión vigente.** Permite escritores en bloques distintos y rechaza bases solapadas obsoletas. | Un lock exclusivo permanente por archivo anularía esa concurrencia; solo leases sin comparación en Txn dejarían actuar a propietarios vencidos. Lock de tamaño protege crecimiento. | RF3, RNF3/5; [arquitectura §7](arquitectura.md#a7). |
| D12 | **write máximo 16 MiB; sin huecos ni append atómico; modos r/r+/w/w+/x/x+.** Acota transacciones y concreta RF3. | Lecturas pueden ser grandes por streaming; transferencias completas usan send/receive. PatchBlock en DN conserva la base sin revelarla a usuarios con permiso solo de escritura. | RF3; [especificación §6](especificacion.md#s6). |
| D13 | **rm con tombstone, file_id irreutilizable y lectores abiertos retenidos.** El nombre desaparece y publicaciones antiguas fallan. | Borrar físicamente de inmediato rompería snapshots; reutilizar IDs permitiría resurrección. GC coordinada y retiro irreversible priorizan seguridad. | RNF3, USR-DEL; [arquitectura §8](arquitectura.md#a8). |
| D14 | **Idempotencia persistida junto al resultado del commit.** Resuelve retries después de respuesta perdida con el mismo request_id/digest. | No se promete ejecución exactamente una vez de todos los efectos físicos: pueden quedar staging/réplicas repetidas, pero una única publicación lógica. | RF2/3, RNF3; [arquitectura §6](arquitectura.md#a6). |
| D15 | **Sin nuevas lecturas autorizadas ni mutaciones cuando no hay quórum.** Mantiene una autoridad consistente y revocación definida. | Lectura offline de snapshots con tokens firmados podría ampliar disponibilidad, pero añade política de revocación/caché que no se adopta. Un stream ya autorizado puede terminar dentro de 15 s. | RNF2/3/6; [especificación §7](especificacion.md#s7). |
| D16 | **Usuario/contraseña Argon2id, grupos/ACL y permisos opacos por bloque.** Denegación por defecto y validación del DataNode mediante cualquier CN. | 2FA/API keys adicionales quedan sujetos a Q03. Tokens firmados son alternativa futura, no necesaria para esta escala; la introspección añade carga a medir. | RNF6; [arquitectura §9](arquitectura.md#a9). |
| D17 | **TLS C/S, mTLS S/S, AES-GCM y envoltura de claves mediante bibliotecas.** Cifrar datos, metadatos persistidos y backups; gestionar claves y rotación fuera de Git. | No implementar criptografía propia. El ciphertext por sí solo no da HA: todas las réplicas autorizadas deben recuperar las claves. KMS cloud solo tras verificar acceso académico. | RNF6/2; F14–F19, F23–F24. |
| D18 | **Tres VMs independientes y acceso C/S directo redundante; S/S en VPC.** Un fallo de host deja control, mayoría etcd y datos. | Tres contenedores en un host solo prueban fallos de proceso. VPN/proxy únicos añadirían dependencia; se evitan en el diseño base. Cuarto DN permite reparar a R=3 durante caída. | INF-01, RNF2/7; [arquitectura §10](arquitectura.md#a10). |
| D19 | **Destino Linux con Docker por host o ejecución nativa reproducible.** En E2 se adopta Windows nativo temporal para validar API con herramientas existentes, sin Docker/WSL disponibles. | No se instalan varias rutas. Windows etcd tier 3 no prueba el destino final; scripts Linux preparados, validación Linux pendiente. Kubernetes/MOM/FUSE/GUI fuera del alcance. | INF-02/03; D21, F21–F24; [entorno](entorno.md). |
| D20 | **Metas propuestas y evidencia por etapa, sin provisión en E1/E2.** Objetivos 1 GiB, 10 clientes y 100/1.000/10.000 archivos, con ajustes justificados. | Streaming sintético E2 no constituye benchmark ni acredita esas metas. No hay despliegue cloud. | RNF1/5, USR-EVID; [especificación §9](especificacion.md#s9). |
| D21 | **Una ruta E2: Python Windows ya existente y etcd oficial aislado.** Venv con lock/hashes y wheel importado en entorno limpio. | Preferencia Linux se mantiene; ausencia de WSL/Docker justifica compatibilidad local ahora. WAL Linux futuro en FS nativo, mismo árbol canónico /mnt/f/DFSha en WSL. | USR-E2-ENV; [entorno](entorno.md). |
| D22 | **Contratos v1 separados de diagnóstico, 47 RPC futuras UNIMPLEMENTED.** Dos listeners loopback TLS/mTLS y streams sintéticos con memoria acotada. | Health/ACK diagnóstico no representan RF1/RF2/almacenamiento. Monolito no depende del probe etcd, prepara SQLite/local. | RF1/2/3, COM-01–05; [protocolos](protocolos.md). |
| D23 | **Intención canónica y autorización de plan por parte de write.** IDs por actor/época en todo servicio, checksums por parte, fence/reemplazo vinculados a autorización. | Hash final de un bloque parcheado lo determina DN; hash completo de archivo opcional después de patch, nunca se conserva uno obsoleto. Digest de CreateUser requiere además verificador secreto Argon2id, sin hash rápido de contraseña. | RNF3/6, D11/D14; [protocolos §§2–4](protocolos.md). |
| D24 | **GitHub existente como único remoto.** Se consultó vacío antes de inicializar main, nombre confirmado por API. Origin enlazado, sin autor inventado. | No hay commits/push ni código sincronizado; lectura verificada no demuestra permiso de escritura. Volver a consultar historia antes de primer commit. | ENT-02; [evidencia Git](evidencias/etapa2/entorno-git.json). |

<a id="compatibilidad"></a>
## Compatibilidad: antecedente E1 y resultado E2

La tabla siguiente conserva la revisión documental del 2026-09-07 y las comprobaciones que estaban pendientes **al cerrar E1**. E2 ya instala versiones exactas compatibles, genera/importa stubs, comunica procesos TLS/mTLS y ejecuta acceso etcd real; resultados en [evidencias E2](evidencias/etapa2/README.md). Persistencia DFS, rotación/recuperación de claves, Linux y HA siguen pendientes. **Compatibilidad documental no equivale a ejecución conjunta**, y ejecución de diagnóstico tampoco equivale al DFS.

| Parte | Verificado en fuentes | Qué falta comprobar y fijar en etapa 2 |
| --- | --- | --- |
| Python/gRPC | Las fichas actuales de `grpcio` y `grpcio-tools` exigen Python ≥3.10; Python 3.12 es candidato compatible con ese mínimo. El quickstart conserva un mínimo histórico menos restrictivo; se prioriza la ficha del paquete a instalar. | Patch Python, versiones exactas coincidentes de grpcio/grpcio-tools, wheels Linux/Windows pertinentes; crear entorno y RPC TLS real. |
| Protobuf | No se permite código generado más nuevo con un runtime anterior. Hay que considerar también las exigencias del plugin gRPC. | Resolver conjuntamente compilador/plugin/runtime; generar desde cero e importar stubs; fijar lock y licencias. |
| etcd | La API v3 ofrece KV/Txn, leases, locks y Watch; el cliente oficial destacado por etcd es Go. Los contratos pueden usarse vía gRPC. | Imagen 3.6.x concreta por digest, importación de protos oficiales con sus dependencias/licencias; prueba Python↔etcd real, TLS/RBAC, failover, límites y lease expirado. No se afirma cliente Python oficial instalado. |
| Contingencia gateway | El gateway JSON existe, pero no soporta autenticación basada en Common Name del certificado TLS. | Si se usa, diseñar auth explícita y verificar APIs de coordinación disponibles; actualizar D05. No degradar seguridad para evitar un problema de stubs. |
| Cifrado | `cryptography` declara Python ≥3.9, excluyendo 3.9.0/3.9.1; ofrece AESGCM y AES Key Wrap. | Versión mantenida compatible, wheel/OpenSSL, roundtrip, rechazo de alteración, formato persistente y recuperación de claves. |
| Contraseñas | `argon2-cffi` declara Python ≥3.8; su API mantenida ofrece PasswordHasher/Argon2id. | Versión/bindings exactos; hash/verify/rehash y coste con límites de RAM e intentos. |
| Persistencia y contenedores | SQLite documenta commit atómico; Docker documenta persistencia de volúmenes. | Configurar durabilidad real de SQLite/filesystem, cifrado del volumen, permisos, reinicio y versión de imágenes. |

El conjunto se resolvió y comprobó antes de implementar RF1/RF2. Los fallos iniciales de expectativas de error por transporte quedaron conservados y corregidos: IP/SAN en negativos TLS y error acotado UNAVAILABLE/DEADLINE_EXCEEDED para indisponibilidad. No se relajó validación de CA/SAN ni de versiones.

<a id="fuentes"></a>
## Fuentes técnicas consultadas

Estas fuentes sustentan capacidades, no requisitos docentes. Páginas stable/latest son móviles; versiones realmente usadas ya fijadas en [entorno](entorno.md) y requirements.lock. No se consultaron conversaciones ni archivos de otros proyectos. Fuentes adicionales E2: [etcd plataformas](https://etcd.io/docs/v3.6/op-guide/supported-platform/), [RBAC y CN de certificado](https://etcd.io/docs/v3.6/op-guide/authentication/rbac/), [release v3.6.14](https://github.com/etcd-io/etcd/releases/tag/v3.6.14), metadatos PyPI de las versiones enlazadas en entorno.md.

| ID | Fuente primaria consultada | Uso en el diseño |
| --- | --- | --- |
| F01 | [gRPC Python: básicos](https://grpc.io/docs/languages/python/basics/) y [quickstart](https://grpc.io/docs/languages/python/quickstart/) | Contratos, stubs y streams; mínimos del tutorial contrastados con paquetes. |
| F02 | [grpcio](https://pypi.org/project/grpcio/) y [grpcio-tools](https://pypi.org/project/grpcio-tools/) | Requisitos Python publicados por mantenedores. |
| F03 | [Garantías de compatibilidad Protobuf](https://protobuf.dev/support/cross-version-runtime-guarantee/) | Generador y runtime deben ser compatibles. |
| F04 | [Autenticación gRPC](https://grpc.io/docs/guides/auth/) | TLS, mTLS y credenciales de llamada. |
| F05 | [Deadlines gRPC](https://grpc.io/docs/guides/deadlines/) y [reintentos](https://grpc.io/docs/guides/retry/) | Plazos explícitos y reintentos con semántica propia de operación. |
| F06 | [RFC 9110 — HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html) | Comparación del transporte HTTP para alternativa REST. |
| F07 | [etcd 3.6: garantías](https://etcd.io/docs/v3.6/learning/api_guarantees/) | Orden/atomicidad de KV y límites de usar Watch para decisiones. |
| F08 | [etcd 3.6: límites](https://etcd.io/docs/v3.6/dev-guide/limit/) y [configuración](https://etcd.io/docs/v3.6/op-guide/configuration/) | Solicitudes pequeñas, cuotas y límite de operaciones. |
| F09 | [etcd 3.6: API de concurrencia](https://etcd.io/docs/v3.6/dev-guide/api_concurrency_reference_v3/) | Claves de lock ligadas a lease y comparación en transacciones. |
| F10 | [etcd 3.6: fallos](https://etcd.io/docs/v3.6/op-guide/failures/) | Mayoría, elección e indisponibilidad bajo partición. |
| F11 | [etcd 3.6: transporte seguro](https://etcd.io/docs/v3.6/op-guide/security/) | Certificados de clientes/peers; activar seguridad, cifrado en reposo separado. |
| F12 | [etcd 3.6: recuperación](https://etcd.io/docs/v3.6/op-guide/recovery/) | Snapshot/restore y diferencia de revisiones al restaurar. |
| F13 | [etcd 3.6: gateway](https://etcd.io/docs/v3.6/dev-guide/api_grpc_gateway/) | Alternativa JSON y limitación de autenticación por Common Name. |
| F14 | [cryptography: AEAD](https://cryptography.io/en/stable/hazmat/primitives/aead/) | AESGCM, datos asociados y no reutilizar nonce con una clave. |
| F15 | [cryptography: key wrapping](https://cryptography.io/en/stable/hazmat/primitives/keywrap/) | Envoltura de DEK mediante biblioteca. |
| F16 | [cryptography en PyPI](https://pypi.org/project/cryptography/) | Compatibilidad declarada de Python. |
| F17 | [argon2-cffi: qué es Argon2](https://argon2-cffi.readthedocs.io/en/stable/argon2.html) | PasswordHasher y variante Argon2id. |
| F18 | [argon2-cffi en PyPI](https://pypi.org/project/argon2-cffi/) | Compatibilidad y bindings mantenidos. |
| F19 | [HDFS Architecture](https://hadoop.apache.org/docs/stable/hadoop-project-dist/hadoop-hdfs/HdfsDesign.html) | Referencia de separación metadatos/datos, no implementación sustituta ni semántica de acceso parcial. |
| F20 | [Atomic Commit in SQLite](https://sqlite.org/atomiccommit.html) | Atomicidad local del monolito y dependencia del filesystem. |
| F21 | [Volúmenes Docker](https://docs.docker.com/engine/storage/volumes/) | Persistencia separada del ciclo de vida del contenedor. |
| F22 | [Amazon VPC](https://docs.aws.amazon.com/vpc/latest/userguide/what-is-amazon-vpc.html) y [Google Cloud VPC](https://docs.cloud.google.com/vpc/docs/vpc) | Red virtual de servicio y separación de flujos; no acreditan permisos de la cuenta académica. |
| F23 | [Cifrado Amazon EBS](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-encryption.html) | Protección de volúmenes/snapshots y dependencia de claves del proveedor. |
| F24 | [Compute Engine: cifrado de discos](https://docs.cloud.google.com/compute/docs/disks/disk-encryption) | Alternativa de cifrado persistente en GCP. |

<a id="aclaraciones"></a>
## RNF8 y registro de cambios

| Fecha | Origen | Cambio | Efecto |
| --- | --- | --- | --- |
| 2026-09-07 | PDF local, p. 2 | RNF8 revisado: tres entradas `…`, sin contenido adicional. | No se crean nuevos requisitos docentes. |
| 2026-09-07 | Usuario, solicitud de etapa 1 | Opción 1 exclusiva; cinco documentos, reglas de corrección y trabajo solo de especificación/diseño. | Matriz con requisitos USR y decisiones D01–D20. |
| 2026-09-07 | Diseño del equipo | Semántica RF3, R/W, mediación etcd, exposición C/S y permisos opacos definidos. | Especificación/arquitectura 1.0; Q01–Q07 permanecen pendientes. |
| 2026-09-08 | Usuario, solicitud E2 y verificación técnica | Remoto existente definido; D03/D05/D19 concretadas, D21–D24 y contratos v1. | Base ejecutable local y pruebas de compatibilidad; no RF completos, HA ni cloud. Q01–Q07 sin respuesta docente. |

No hay respuestas docentes registradas ni aprobación docente supuesta. Las consultas Q01–Q07 están en [especificación §10](especificacion.md#s10). Cuando llegue una aclaración, se añadirá una fila con fuente accesible y se actualizará primero la matriz, luego diseño, implementación y pruebas afectadas.
# Decisiones de etapa 3

**Actualización E5:** [D36–D44](etapa5-rf3.md) concretan el acceso parcial y
reemplazan las propuestas incompatibles de etapas anteriores. Se conserva Python
3.12.10 y la toolchain fijada; no se cambiaron dependencias. BeginRead/EndRead son
contratos aditivos necesarios para serializar lecturas activas en el control.
Los originales PDF/guía se preservan; la guía no prevalece sobre el prompt E5.

[D25–D29](etapa3-diseno.md) actualizan el diseño por instrucción del usuario:
CQRS local, CRUD y perfiles, contenedor cifrado con memoria acotada, publicación/recuperación
y colocación preparada para etapa 4. Se conservan dependencias y Q01–Q07 sin información nueva.
# D30 — Concreción del contrato H1

[D30](protocolos-hito1.md#d30-representación-efectivamente-implementada) define
digest/manifiesto JSON protobuf, sesiones base64 estándar y reintentos. Sustituye
propuestas E2 sin implementación; método/actor/época ligados al ledger. Stack
conservado. Margen de redondeo del deadline recibido 2 s, sin ampliar el plazo
solicitado por SDK ni aceptar llamadas ilimitadas.
