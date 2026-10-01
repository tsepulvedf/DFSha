# DFSha — Seguridad integral, etapa 8

Estado: E8 COMPLETA en el perfil protegido del laboratorio, 2026-10-01.
RNF6 se acredita dentro de las superficies y amenazas declaradas; no implica
cifrado integral del host ni despliegue académico. [Cierre y pruebas](evidencias/etapa8/cierre.md).
Las decisiones siguientes son del equipo, no aclaraciones del docente.
Q03 y las demás consultas permanecen pendientes.

## Decisiones de implementación

- **D59:** perfil protegido explícito, separado de los laboratorios anteriores.
  Cifrar páginas de metadatos etcd y cuerpos SQLite mediante AES-256-GCM de
  `cryptography`, con claves independientes del contenido. Autenticar identidad
  del registro y contexto. Direcciones de páginas e índices de nombres mediante
  HMAC con separación de propósito. No almacenar nombres ni contraseñas en índices.
  Persisten tamaños, tipos de registro, UUID, relaciones e información temporal;
  esto no equivale a ocultar patrones de acceso o toda la estructura del servicio.
- **D60:** conservar formatos de bloques inmutables y admitir varias claves de
  lectura; activar una clave nueva solo para objetos nuevos. La retirada exige
  inventario completo de referencias, snapshots y respaldos. No regenerar claves
  al arrancar ni reinterpretar un almacén existente como vacío.
- **D61:** revocar sesiones al deshabilitar cuentas o cambiar contraseñas, con
  autoridad compartida. Administración de políticas no concede lectura implícita
  del contenido en el perfil protegido. Argon2id conserva parámetros fijados hasta
  medir el coste; limitar admisión antes del trabajo costoso.
- **D62:** evidencia incremental con run_id, huella del código antes de ejecutar,
  estado por comando, código de salida observado y publicación atómica del resumen.
  Una ejecución interrumpida sigue sin resultado concluyente.

## Amenazas y límites

Se consideran clientes anónimos, usuarios ajenos, nodos no autorizados,
interceptación, alteración de objetos y copia de discos sin material de claves.
TLS/mTLS autentican transporte; permisos y tareas autorizan cada operación.
Los snapshots fijan contenido, no privilegios. Sin quórum no se autorizan nuevas
operaciones desde caché. R=3/W=2 no sustituye la mayoría de etcd.

No hay resistencia bizantina ni protección del plaintext en memoria frente al
administrador del host. La separación de directorios de claves no demuestra
independencia física. El laboratorio Windows acredita procesos en un equipo;
Linux tiene pruebas de E8 en un contenedor aislado; hosts independientes e
Internet permanecen pendientes. El contenedor también comparte el host físico.

## Fuentes verificadas

- [Parámetros de argon2-cffi](https://argon2-cffi.readthedocs.io/en/stable/parameters.html):
  medir memoria, paralelismo y tiempo con el equipo real.
- [AEAD de cryptography](https://cryptography.io/en/stable/hazmat/primitives/aead/):
  nunca reutilizar nonce con una misma clave para otro cifrado; autenticar AAD.
- [Seguridad de transporte etcd](https://etcd.io/docs/v3.6/op-guide/security/) y
  [RBAC](https://etcd.io/docs/v3.6/op-guide/authentication/rbac/): TLS no constituye
  cifrado del almacenamiento; las superficies auxiliares requieren revisión propia.

## Cobertura y verificación

### Revisión de dependencias (2026-09-15; consulta repetida 2026-10-01)

Se conserva grpcio 1.83.1: el aviso del mantenedor
[GHSA-hf3w-6hpw-qp67](https://github.com/grpc/grpc/security/advisories/GHSA-hf3w-6hpw-qp67)
identifica esa versión como corregida para los agotamientos de memoria descritos.
No se desactivan los experimentos de transporte que habilitan esas correcciones.
etcd 3.6.14 incorpora los arreglos de límites de Watch/RBAC y handshake indicados
en [su publicación oficial](https://etcd.io/blog/2026/july-23-patch-release/).
La revisión del [historial de cryptography](https://cryptography.io/en/stable/changelog/)
y sus [avisos](https://github.com/pyca/cryptography/security/advisories) se realiza
sobre la versión fijada 50.0.1. Esta consulta no equivale a certificar ausencia
de vulnerabilidades ni sustituye revisar nuevos avisos antes de desplegar.

### Superficies persistentes

| Ubicación | Mecanismo del perfil protegido | Límite o verificación pendiente |
| --- | --- | --- |
| Páginas etcd, incluidas copias en WAL | AES-GCM por página; HMAC de contenido para dirección | Raíz/leases exponen UUID, tipos y tiempos; RBAC/certificados de etcd no quedan cifrados por este codec |
| SQLite control y respaldo de migración | Cuerpos AEAD, índice de nombre HMAC | UUID, parent, clase y flag live visibles; origen protegido desde bootstrap, sin conversión de datos anteriores |
| Inventario SQLite de cada DN | Cuerpos AEAD con clave propia del nodo | Claves de inventario distintas de la clave de metadatos del control |
| Bloques y staging | DFSHAB01, DEK aleatoria por objeto, AES-GCM por fragmento | Cabecera de bloque autenticada pero visible; no se entrega plaintext antes de autenticar todo el objeto |
| Respaldos E7 | Copia completa bajo ACL local | Perfil histórico no protegido; no convertirlo silenciosamente |
| Respaldos E8 | Archivo cifrado por objetos y manifiesto AEAD, clave externa | Restauración HA y rechazo de clave incorrecta comprobados; ventana offline detiene CN/DN y GC |
| Logs de aplicación protegidos | Campos permitidos, auditoría y rotación 4 × 5 MiB por proceso | Identificadores/resultados visibles bajo ACL; no contienen contenido ni secretos |
| Salida nativa y etcd | Drenaje acotado 3 × 2 MiB; etcd rota su salida estructurada 3 × 10 MiB, edad 7 días | Retención local, no auditoría inmutable ni protección ante administrador comprometido |
| Sesión CLI protegida | Archivo AEAD y temporal cifrado; clave externa al directorio del cache | La clave perdida impide abrir el cache; volver a iniciar sesión exige derechos vigentes |
| Descarga elegida por usuario | Archivo ordinario en claro y temporal local | No se cambia silenciosamente el formato solicitado; proteger el equipo cliente |
| Volcados, paginación e hibernación del SO | No forman parte del archivo de backup ni son temporales creados por DFSha | No se comprobó cifrado de estas superficies del host; no exportar volcados como si fueran respaldos protegidos |

Las claves de metadatos, inventario y contenido residen fuera de los directorios
de bases/bloques, bajo ACL del laboratorio. No se incluyen en Git. Siguen en el
mismo host: esto no acredita custodia independiente ante pérdida del medio.
La cobertura comprobada es el cifrado aplicativo de las rutas declaradas. No se
habilitó BitLocker ni se reformateó una unidad; proteger sectores, memoria virtual
y volcados del sistema requiere controles del host que este laboratorio no acredita.

Las pruebas reales del perfil protegido 3CN/3etcd/3DN cubren administración,
revocación, roles, rotación/recuperación, temporales, respaldos y retención.
Linux aprobó 36 casos E7/E8 en 439,88 s en `20261001T034403Z-581a2df8`, con imagen
reconstruida y exit 0 observado. Windows repitió los mismos 36 en 2299,16 s y
completó la medición protegida de 512 MiB en `20261001T034229Z-9d313040`.
La cobertura Windows consolidada reúne 177 casos distintos por ejecuciones
identificadas. [Criterios y pruebas](evidencias/etapa8/aceptacion.md).
La base E8 aprobó siete casos iniciales en
`evidencias/etapa8/baseline.xml`; no se recuperó el código de salida del supervisor.

## Custodia y recuperación comprobadas

| Material | Ubicación/configuración del laboratorio | Custodia y recuperación |
| --- | --- | --- |
| Clave de contenido y claves de lectura | `secrets/` de cada nodo, `key_path`, `content_read_key_paths`, `content_active_key_path` | 32 bytes aleatorios; SHA-256 como identificador; provisionar por administración, nunca por API del cliente |
| DEK por objeto | Envuelta en la cabecera DFSHAB01 | Solo se recupera con la clave autorizada; copia S/S conserva ciphertext y cabecera |
| Clave de metadatos de control | `secrets/metadata-at-rest.key`, `metadata_key_path` | Misma autoridad criptográfica para los tres controles; pérdida impide descifrar las páginas |
| Clave de inventario DN | `metadata_key_path` propio del nodo | Independiente de los otros inventarios y del contenido |
| Clave del archivo de backup | Archivo externo indicado por `--archive-key-file` | No se incorpora al archivo que protege; el backup sí contiene cifrado el material operativo necesario para restaurar |
| Clave de cache CLI | `--session-key-file` fuera del directorio de sesión | No se entrega a servidores; no regenerar para intentar abrir un cache existente |
| CA de laboratorio | `certificates/ca.key`, bajo permisos del propietario/administración | Solo emisión; no se copia a directorios de identidad de cada proceso ni al cliente |
| Hojas TLS | `identities/<identidad>/`, claves privadas distintas | Rotación por etapas con la CA existente; cliente recibe únicamente confianza pública |

El backup rechaza rutas de claves/certificados fuera de la raíz inventariada
(`BACKUP_EXTERNAL_KEY_MATERIAL`) antes de detener el servicio: debe incorporarse
ese material a un plan recuperable, no producir silenciosamente una copia incompleta.
La restauración no necesita el servidor original; sí la clave externa del archivo.
Rotar la clave activa de contenido no modifica objetos existentes. La rotación
de la clave maestra de metadatos requeriría una migración explícita y no se
presenta como recifrado automático implementado.

Emisión de una hoja nueva, sin sobrescribir la identidad actual:

```powershell
.\.venv-win\Scripts\python.exe scripts/issue_certificate.py --ca-dir .runtime/demo-e8/certificates --output .runtime/demo-e8/identities/renewed-node --identity <node_id> --days 7
```

Actualizar los caminos de la identidad correspondiente y reiniciar solo ese
proceso; comprobar SAN/serial, registro y lectura antes de pasar al siguiente.
En etcd reiniciar un miembro por vez y verificar mayoría/membresía. Las pruebas
`test_stage8_certificates.py` y `test_stage8_lifecycle.py` ejecutan esa secuencia.
Las hojas usan vigencia de 1–30 días limitada por la CA; no se regenera la CA al
reiniciar. Retirar un DN mediante `node-authorize --no-enabled` revoca su autoridad
online aunque siga teniendo una hoja válida; no borra las claves que ya conoció.
No hay afirmación de CRL ni de resistencia a un nodo legítimo totalmente comprometido.

El cliente usa listener TLS público. Registro, recibos y mantenimiento usan mTLS
con comprobación de roles; los peers etcd aceptan solo CN administrativos de
miembros. El rol de cada control limita KV al prefijo DFSha. `/metrics` y `/health`
no están cubiertos por RBAC KV: el laboratorio los limita a loopback y mTLS.
Una identidad de CA confiable puede consultar métricas, incluso sin permiso KV;
esto se prueba y no se anuncia aislamiento por rol para esas rutas auxiliares.

El run `20260915T102901Z-14ee6862` terminó con código 0 observado y cuatro casos
aprobados, sin cambios de fuentes durante la ejecución. `ha_recovery.py` recuperó
un respaldo protegido en otro directorio y comprobó los datos y permisos mediante
los procesos HA. Se mantiene la invalidación administrativa de la época al restaurar.
No es recuperación de escrituras posteriores al backup.

`key_lifecycle.py` provisiona una clave nueva y exige que los procesos autorizados
la anuncien por mTLS antes de activarla. El ensayo reinició los tres DN por turnos,
conservó la lectura de un snapshot antiguo y verificó nuevas escrituras con la
clave activa nueva. Las copias S/S conservan el objeto cifrado y su key_id original.
El guard de retirada es conservador: no elimina claves; rechaza cualquier backup
retenido sin inventario de dependencias comprobado y exige mantenimiento offline.
La automatización de retirada efectiva no se declara terminada.

`issue_certificate.py` emite una hoja con nueva clave privada usando la CA existente.
El ensayo renovó un ControlNode sin invalidar el handle compartido. La revocación
administrativa de un DN se comprueba aun cuando su canal mTLS ya está establecido:
el certificado por sí solo no conserva autorización de registro ni elegibilidad.
Esto no acredita revocación individual por CRL de una hoja antigua; las pruebas de
rotación de los demás roles se probó posteriormente en
`20260915T185856Z-525dabf5`: tres miembros etcd por turnos, serial nuevo comprobado
mediante TLS y lectura del snapshot entre reinicios; después una hoja de DataNode.
El certificado de servidor vencido fue rechazado antes de ejecutar el handler.
La pérdida de dos miembros etcd impidió Stat/Mkdir; tras recuperar mayoría el
nombre prohibido seguía ausente y el snapshot era legible. Los nueve casos de
esa selección terminaron con exit 0; su medición también terminó con exit 0.
El informe completo y las magnitudes están en
[medición protegida](evidencias/etapa8/medicion-protegida.md).

## Reproducción del perfil protegido

PowerShell, desde `F:\DFSha`, con una raíz nueva y herramientas ya preparadas:

El arranque manual protegido pide sin eco la contraseña administrativa. En una
raíz nueva la usa para el bootstrap; al reanudar o restaurar exige la vigente,
sin restablecerla. Para automatización se admite `--admin-password-stdin`, nunca
un argumento con el valor secreto. Las clases de laboratorio conservan una
contraseña de fixture para pruebas aisladas; no es la credencial del arranque
manual protegido. El supervisor guarda la contraseña solo en memoria.

```powershell
.\.venv-win\Scripts\python.exe scripts/run_ha_lab.py --directory .runtime/demo-e8 --protected
# En otra consola, para detener solamente ese laboratorio:
New-Item -ItemType File .runtime/demo-e8/stop-ha
# Reanudar sus claves, certificados y datos existentes:
.\.venv-win\Scripts\python.exe scripts/run_ha_lab.py --directory .runtime/demo-e8 --resume
.\.venv-win\Scripts\python.exe scripts/verify_stage8.py --measure
```

Para respaldo al detener, añadir `--backup-on-stop <directorio-nuevo>` y
`--archive-key-file <archivo-externo-de-32-bytes>`. Para restaurar, usar otra raíz
con `--restore-from <backup>` y esa misma clave externa. No se imprime ni se pasa
el valor de la clave como argumento. El archivo de clave debe custodiarse bajo ACL
fuera del respaldo; perderlo impide recuperar el archivo protegido. Los comandos
manuales son procedimientos; las ejecuciones acreditadas están en las evidencias.

## Permisos, administración y revocación

| Actor / acción | Regla aplicada |
| --- | --- |
| Anónimo | Sin acceso a namespace, datos ni administración; diagnóstico no acredita derechos DFS |
| Usuario / listar directorio | Lectura del directorio y recorrido de ancestros; no confundir listar con atravesar |
| Usuario / crear o eliminar entrada | Escritura y recorrido en el padre; comprobación transaccional |
| Usuario / leer archivo o snapshot | Permisos actuales del archivo retenido; snapshot no congela privilegios |
| Usuario / escribir | Modo válido, permisos actuales, operación activa y fencing comprobados al publicar |
| Propietario / ACL | Puede modificar la política del objeto; no delega por conocer su UUID |
| Administrador / identidades y política | Gestiona usuarios, grupos, ACL y nodos; el perfil protegido no concede lectura implícita de archivos ajenos |
| DataNode / bloques | Permiso limitado a sujeto, operación, versión, acción, destino y vigencia; consulta al control |
| DataNode / copia o borrado S/S | Tarea interna vigente, roles, propietario y generación; mTLS por sí solo no basta |
| ControlNode / etcd | Identidad con rol limitado al prefijo de ese servicio; credencial root separada |

Las sesiones son opacas. El estado autoritativo almacena su hash; los resultados
idempotentes que necesitan devolver una sesión se cifran. Logout, cambio de
contraseña y deshabilitación afectan a todos los controles. Habilitar de nuevo
una cuenta no revive sus sesiones revocadas. Los streams ya autorizados conservan
solo la ventana finita vigente; nuevas aperturas, streams y commits revalidan.

Ejemplos CLI (PowerShell; sustituir los UUID y revisiones por resultados reales):

```powershell
$dfshaCli = @('-m', 'dfsha.client.cli', '--config', '.runtime/demo-e8/client.toml', '--session-file', '.runtime/client-e8/admin/session.enc', '--session-key-file', '.runtime/client-keys/admin.key')
.\.venv-win\Scripts\python.exe @dfshaCli init-session-key
.\.venv-win\Scripts\python.exe @dfshaCli login admin
.\.venv-win\Scripts\python.exe @dfshaCli useradd alumno
.\.venv-win\Scripts\python.exe @dfshaCli groupadd equipo
.\.venv-win\Scripts\python.exe @dfshaCli group-members <group_id> <revision> <user_id>
.\.venv-win\Scripts\python.exe @dfshaCli user-set <user_id> <revision> --disabled
.\.venv-win\Scripts\python.exe @dfshaCli passwd <user_id> <revision>
.\.venv-win\Scripts\python.exe @dfshaCli node-authorize <node_id> <revision> --no-enabled
```

Las contraseñas se solicitan sin eco; no escribirlas en el comando. Usar distintos
`--session-file` bajo ACL para administrador y usuario ordinario. `getacl` devuelve
la revisión vigente; `setacl` recibe un JSON compatible con Acl. Conservar la
revisión para detectar cambios concurrentes. No publicar archivos de sesión.
El perfil protegido exige `--session-key-file`; `init-session-key` crea una clave
solo de forma explícita y rechaza regenerarla si ya hay un cache que la necesita.
La separación de directorios no acredita independencia física del medio.

## Límites y retención

Argon2id usa `m=19456 KiB, t=2, p=1`, hasta dos trabajos simultáneos por ControlNode;
el límite global teórico de tres procesos es seis trabajos. Antes del hash, la
autoridad compartida admite como máximo 60 intentos/minuto globales y 10/minuto
por bucket de identidad (64 buckets fijos, incluidas identidades inexistentes).
Esta política acota metadatos y trabajo, pero un atacante puede agotar la ventana
de admisión: no se promete disponibilidad frente a DoS sin controles de red.

En `20260915T103652Z-bbd837f8`, dos hashes concurrentes tardaron 0,01610 s en
conjunto. El máximo residente del proceso pytest fue 111013888 bytes; incluye
trabajo anterior de ese proceso y no es una medición aislada de memoria de Argon2.
La configuración reserva 19456 KiB por hash. Una barrera mantuvo ocupados los dos
slots y comprobó LIMIT_EXCEEDED para el tercero, además de verificar contraseña
correcta e incorrecta. Son observaciones de ese equipo, no un SLA ni una garantía
de resistencia para contraseñas débiles.

El perfil limita sesiones activas a 128 globales/8 por usuario, handles a
512 globales/32 por usuario y uploads a 64 globales/16 por usuario. Los límites
de contenido, fragmentos y write se conservan: perfiles 4/64/128 MiB, fragmentos
256 KiB, write máximo 16 MiB. Login HA tiene deadline de 30 s; no cambia TTL de
locks/handles ni permite publicación después de vencerlos.

Los resultados de idempotencia y tombstones no se borran por edad: eliminar el
registro no autoriza volver a ejecutar una identidad antigua. Los backups y pins
administrativos necesitan liberación explícita con referencias verificadas. La
cuota etcd limita el crecimiento, pero no sustituye el mantenimiento de páginas
inmutables huérfanas y el inventario de retención.

`metadata_retention.py` implementa una ventana offline: el supervisor debe haber
detenido sus tres CN y los DN; no basta la ausencia de un archivo PID. El comando
`run_ha_lab.py --collect-pages-on-stop` exige `--backup-on-stop` cifrado y clave
externa. Marca las páginas alcanzables de las raíces activa/importada, incluyendo
todos los registros de snapshots, resultados y tombstones. Cada lote de hasta
32 eliminaciones compara raíz y propiedad de la barrera etcd; renueva esa propiedad
durante el recorrido y se detiene ante pérdida de autoridad. Tiene un máximo de
100000 páginas por ejecución. No es GC online ni elimina objetos de datos.
La prueba de retención pasó en `20260915T185856Z-525dabf5`: rechazó trabajo con
procesos activos y un digest incorrecto; eliminó páginas huérfanas, conservó
snapshot/resultados y verificó descarga tras reiniciar.

`--release-pin-on-stop <snapshot_id> --expected-pin-digest <sha256>` libera un pin
administrativo de migración después del backup, comparando la identidad y el hash
del registro completo. Conserva un resultado idempotente y deja la recolección de
bloques al mecanismo de referencias cuando se reanude el servicio. El snapshot
vigente u otros handles continúan fijando sus objetos. No hay borrado por edad de
ledgers o claves. La compactación MVCC/defrag requiere administración etcd separada
y no se presenta como ejecutada por este recolector. La prueba real de estas
operaciones pasó en el run `20260915T185856Z-525dabf5`.

El bootstrap cifrado se puede repetir con la misma cuenta administrativa válida
y contraseña sin cambiar identidad, clave, revisión o privilegios. Una cuenta
deshabilitada, eliminada, sin rol administrativo o con otra contraseña produce
ALREADY_EXISTS; la repetición no la recrea. Una autoridad SQLite ya migrada tampoco
se reactiva. Los perfiles históricos conservan su inicialización explícita original.

## Matriz RNF6 de seguimiento

| Aspecto | Implementación | Prueba/evidencia prevista o disponible | Límite de cierre |
| --- | --- | --- | --- |
| Autenticación y grupos | Argon2id, IdentityService, sesiones etcd | test_stage8_authorization.py, CLI cifrada; Linux final aprobado | Q03 pendiente; sin 2FA/API keys adicionales |
| Revocación | Sesiones/ACL compartidas; validación en commit | Revocación tras open y preparación W=2; canal DN existente rechazado | Streams ya autorizados solo dentro de su plazo finito |
| Transporte | TLS cliente, mTLS internos y peers con CN permitido | TLS, test_stage8_etcd_security.py y test_stage8_certificates.py | No CRL declarada; métricas mTLS sin RBAC KV |
| Bloques | AES-GCM y key_id por objeto inmutable | test_stage8_keys.py; corrupción/junction en regresión Windows | Administrador del host fuera del modelo de confidencialidad |
| Metadatos/WAL | Páginas/cuerpos AEAD e índices HMAC | storage.xml y test_stage8_storage.py | Estructura opaca visible; no cifrado integral de sectores |
| Backups | Archivo cifrado y restauración aislada | test_stage8_recovery.py, restauración después de rotar claves/certificado | Clave externa indispensable; prueba local |
| Custodia/rotación | Inventario por mTLS, nueva clave y lectura antigua | test_stage8_lifecycle.py, Linux final aprobado | Guard de retirada conservador, no borrado automático |
| Auditoría/límites | Campos permitidos, logs rotativos, admisión y mantenimiento acotados | test_stage8_limits.py, test_stage8_process_log.py, test_stage8_retention.py | Ledger/tombstones retenidos; compactación MVCC administrativa separada |
| Perfil HA protegido | Tres CN/tres etcd/tres DN, R=3/W=2 | Medición 512 MiB y regresión afectada aprobadas; cierre con huellas de fuentes | Hosts/Internet pendientes E9; Linux local no acredita independencia física |
