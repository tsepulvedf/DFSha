# E7 — alta disponibilidad del control

Estado: COMPLETA en el laboratorio Windows de fallos de procesos, 2026-09-14.
[Criterios y evidencia](evidencias/etapa7/aceptacion.md),
[inventario final](evidencias/etapa7/verificacion-final.json): 152 casos distintos
aprobados mediante una suite de 144 aprobadas/4 fallidas y una repetición de ocho
aprobadas (cuatro corregidas y cuatro nuevas). No es una única suite de 152.
Wheel instalado comprobado con procesos HA reales; fallos históricos preservados.
E6 de partida: commit 0100928, remoto idéntico y checkout limpio. Regresión de esta
sesión: 131 pruebas aprobadas en 1108,689 s, sin omisiones; evidencia en
evidencias/etapa6/20260912T233248Z/result.json. PDF releído íntegro: siete páginas.

## Decisiones de implementación D51–D56

- D51: tres controles activos comparten un solo clúster etcd de tres miembros.
  R3 son copias objetivo, W2 son ACK de datos por bloque, y 2/3 es mayoría de
  metadatos. Sin mayoría no hay fallback SQLite ni autorización desde caché.
- D52: espacio versionado /dfsha/ha/<uuid>/v1, raíz autoritativa y páginas
  inmutables identificadas por SHA-256. Índice por tipo y partición de identidad;
  valores grandes se subdividen en páginas de hasta 128 KiB. Las páginas se
  persisten antes de un único CAS de raíz; el commit no publica manifiestos a medias.
  La unidad de trabajo conserva las interfaces CQRS existentes. Una barrera etcd
  de corta duración serializa exclusivamente decisiones de metadatos, jamás
  transferencias. Su propiedad y los leases requeridos se comparan al publicar.
- D53: época global persistente; arranque individual no la cambia. Locks y handles
  tienen propiedad temporal respaldada por leases etcd, distinta de registros y
  resultados durables. Un lease vencido no se restaura mediante KeepAlive.
- D54: SDK y DataNodes usan varios endpoints con reintentos acotados, conservando
  solicitud e intención. Las cachés solo contienen páginas inmutables verificadas;
  cada decisión empieza con una lectura autoritativa. Watch emite notificaciones
  y reconstruye tras compactación, sin decidir permisos; el mantenimiento actual
  conserva su ciclo periódico acotado.
- D55: mantenimiento elegido con lease y generación compartidos. Referencias,
  reservas, publicación y retirada comparten la barrera transaccional; los
  ejecutores antiguos pierden autoridad. RETIRED continúa irreversible.
- D56: migración con ventana de mantenimiento y backup SQLite coherente con WAL;
  importación versionada y validación antes de activar. Handles locales no se
  convierten en leases vigentes. Restauración usa otro clúster/directorios y
  cambio explícito de época, preservando resultados y datos del punto respaldado.

Son decisiones del equipo a partir del prompt E7, no aclaraciones del docente.
Q01–Q07, incluida Q05 sobre mediación CN→etcd→CN, siguen pendientes.

### D57 — contención física y verificador de aceptación

Se comparan las representaciones DOS/UNC equivalentes de rutas Windows después
de resolverlas. Esto evita el falso rechazo al aparecer el directorio durante
`realpath` de Python 3.12, sin permitir que una junction salga del almacén.
No se cambiaron ACL, TLS, TTL ni versiones de dependencias. La segunda descarga
del escenario de aceptación declara `overwrite=True`, preservando la protección
del SDK frente a reemplazos locales implícitos. [Causa, regresión y límites de
la evidencia original](evidencias/etapa7/diagnostico-putblock.md).

La [primera medición corregida](evidencias/etapa7/medicion-fixed.md) terminó con código 0:
512 MiB, W2/R3, parche de 4096 bytes y lectura del mismo handle tras la caída
del control. La regresión final se registra separadamente; esta medición no
sustituye las pruebas de quórum, concurrencia, migración o restauración.

## Fuentes oficiales y límites

D58 concreta los fallos de la regresión conjunta del 14 de septiembre: `Lock`
usa 15 s en HA (antes retenía 6 s, menos que los 8 s máximos de espera por la
barrera de metadatos); el perfil de endpoint único conserva 6 s. No se modifica
la duración del lease, el fencing ni el conflicto esperado. `FailoverChannel`
permite reintentar exclusivamente `GetProtection` ante CANCELLED de transporte
sin detalle DFS, dentro del presupuesto restante y entre endpoints existentes.
La consulta no modifica el estado. No se aplica a mutaciones, PERMISSION_DENIED,
cancelaciones de aplicación ni al cierre solicitado del canal.

El SDK conserva OUTCOME_UNKNOWN cuando no puede consultar un commit incierto.
Los tests H1/H2 actualizan esa expectativa, conservando su recuperación completa.
Los resultados antes/después se identifican en las evidencias, sin ocultar la
regresión conjunta fallida ni sumar repetidos como pruebas distintas.

[Límites etcd](https://etcd.io/docs/v3.6/dev-guide/limit/),
[garantías API](https://etcd.io/docs/v3.6/learning/api_guarantees/),
[concurrencia](https://etcd.io/docs/v3.6/dev-guide/api_concurrency_reference_v3/) y
[recuperación](https://etcd.io/docs/v3.6/op-guide/recovery/).
Se conserva etcd 3.6.14 y los stubs oficiales fijados. Las solicitudes y
comparaciones deben permanecer por debajo de los límites del servidor real.
Los snapshots DFS no dependen de conservar el historial MVCC.

Laboratorio Windows: fallos de procesos en un único host. Linux, hosts físicos
independientes, cloud y seguridad integral no se presuponen comprobados. E8 no se ejecuta.

## Resultado de aceptación y límites

Adaptador, tres miembros y controles, leases compartidos, failover,
quórum/partición TCP, mantenimiento/GC, migración, backup/restauración y regresiones
comprobados. [Medición final](evidencias/etapa7/medicion.md): 512 MiB, 157,500 s
hasta commit, parche de 4096 bytes en 27,703 s y lectura tras parada del control
en 21,157 s; hashes correctos y cero contenido por controles. El informe terminal
está completo y el laboratorio cerrado; el código de salida de la sesión final
no fue recuperable tras interrupción, a diferencia del 0 observado en la anterior.
Los límites de infraestructura y las mejoras de retención descritas abajo siguen
pendientes. E8 no se ejecutó.

## Autoridad, esquema y límites efectivos

El adaptador `control/etcd_metadata.py` implementa la misma unidad de trabajo de
metadatos que usa el dominio E6. `MetadataStore` y `LeaseAuthority` son los puertos
ejercidos; los protocolos conceptuales `Distributed*` de E2 no son otra base de datos.
SQLite en el perfil HA solo conserva inventarios de cada DataNode. La ruta local
de control sirve para su exclusión de instancia y para conservar el origen
migrado; no decide permisos, namespace, reservas ni versiones.

| Clave relativa a `/dfsha/ha/<UUID>/v1/` | Contenido y vigencia |
| --- | --- |
| `root` | Hash de la raíz visible. Una lectura Range linealizable obtiene su revisión. |
| `pages/<sha256>` | Páginas inmutables: hojas `L` o índices `I`, hash verificado al leer; máximo 131.073 bytes incluyendo tipo. |
| `gate` | Propietario opaco ligado a lease; serializa decisiones de metadatos entre procesos. |
| `leases/<tipo>/<id>` | Propiedad temporal de sesión, handle, lock o estado de nodo. Los registros y resultados durables están en páginas independientes. |
| `maintenance-owner` | Coordinador temporal; registro compartido de generación en `settings/maintenance`. |
| `commits/<id>` | Marcador temporal de publicación, para distinguir respuesta perdida de CAS rechazado; asociado a lease y limpiado al reutilizar el worker. |
| `import-root` | Raíz preparada para migración; no es autoridad hasta su activación explícita. |

El índice agrupa registros por tipo y prefijo SHA-256 de identidad (256 particiones).
Manifiestos/snapshots, nodos lógicos, ACL, sesiones, operaciones, reservas, ubicaciones,
historial, tareas y retiradas se guardan en este árbol. El hash de partición organiza
metadatos; **no selecciona la ubicación física de bloques**.

Los objetos grandes se subdividen en páginas de 128 KiB con índices de hasta 64
referencias. La transacción final publica una raíz pequeña: no contiene el
manifiesto entero. Los lotes previos tienen hasta 32 puts y 512 KiB de valores;
la transacción final se limita a 256 KiB, con hasta 48 guardas de leases y 48
efectos de leases, además de raíz, barrera y marcadores. Etcd arranca con
`--max-request-bytes=1572864`, `--max-txn-ops=128` y cuota de 1 GiB.
La caché de páginas tiene 16 MiB; las páginas nuevas de una UoW también se acotan
a 16 MiB. Una operación que exceda los límites devuelve `LIMIT_EXCEEDED`.

El dominio todavía reconstruye representaciones de manifiestos para validar
operaciones. La transacción Raft final es acotada, pero el coste de CPU/lectura de
metadatos depende del manifiesto; no se afirma rendimiento constante para millones
de entradas. La compactación MVCC no elimina snapshots DFS: estos son registros
propios. Las páginas inmutables huérfanas de preparación quedan sujetas a cuota;
su recolección física independiente requiere una barrera y no se hace por Watch.

## Publicación y continuidad

```mermaid
sequenceDiagram
    participant SDK
    participant C1 as Control 1
    participant E as etcd 3 miembros
    participant D as DataNodes
    participant C2 as Control 2
    SDK->>C1: BeginWrite (identidad, intención, rango)
    C1->>E: Leer raíz, adquirir propiedad y publicar preparación
    C1-->>SDK: Plan y permisos
    SDK->>D: PatchBlock (solo delta)
    D->>D: Replicar versión cifrada
    D->>C2: Recibos autenticados
    C2->>E: Confirmar ubicaciones y estado compartido
    SDK->>C2: CommitWrite (misma operación)
    C2->>E: Leer raíz vigente; revalidar bases, ACL, W2 y fencing
    C2->>E: Persistir páginas nuevas
    C2->>E: Txn compara raíz y propietarios de leases; publica raíz y resultado
    C2-->>SDK: Resultado durable o conflicto controlado
```

Preparaciones de bloques distintos progresan en paralelo; las decisiones finales
tienen un orden total. La barrera global se libera antes de transferir contenido.
Un propietario vencido no publica aunque tenga ACK de datos. Raíz e intención
se conservan para combinar cambios compatibles y recuperar resultados desde otro
control. El identificador de arranque del proceso no altera `control-epoch` compartido.

El SDK compartido devuelve `Fault('OUTCOME_UNKNOWN')` si CommitUpload pierde la
respuesta y no consigue recuperar un resultado confirmado. Esto también aplica
al usar H1/H2: no afirma aborto ni repite una publicación con otra identidad.
Las pruebas históricas de caída justo antes de publicar exigen ahora ese motivo
preciso, conservando el reinicio, la recuperación, la limpieza y la comprobación
de que continúa visible la versión anterior. Una caída durante PutBlock sigue
siendo un error de transporte, antes de intentar el commit.

En este laboratorio las RPC normales HA tienen presupuesto de 15 s por intento,
hasta tres intentos del SDK cuando procede. La elección de endpoint distribuye
ese presupuesto entre alternativas, conservando el request. El lease de barrera
de metadatos es 30 s, con espera por adquisición acotada a 8 s: la caída de un
proceso que lo retenga puede exigir esperar su expiración. Los handles conservan
120 s y máximo de 24 h; locks parciales 30 s, renovación cada 10 s. Los campos de
tiempo publicados son UTC; el reloj monotónico de un proceso no se comparte.
La expiración exige tanto plazo vigente como propiedad etcd; al reiniciar todo
el clúster no se reviven handles cuyo plazo absoluto ya terminó. VMs futuras
requieren relojes sincronizados, además de la autoridad de leases de etcd.

Los heartbeats HA se envían cada 3 s, con sospecha a 12 s e indisponibilidad a
30 s. Los valores históricos SQLite permanecen. El mantenimiento tiene lease de
15 s renovado por un hilo independiente cada 3 s; todas sus transacciones comparan
la propiedad compartida. Un KeepAlive previo no sustituye esa comparación.

## Migración y respaldo

`HACluster.seed_e6(callback)` construye datos reales usando E6 antes de activar HA.
La migración requiere detener el control SQLite y bloquear su archivo `.owner`.
Usa `sqlite3.Connection.backup`, compatible con WAL, y desactiva explícitamente
el origen mediante `authority_migrated`. Importa por lotes a otra raíz, compara
todos los registros importados y activa una sola raíz etcd. Las sesiones locales
se revocan; handles/locks antiguos exigen reapertura. Los snapshots retenidos se
conservan mediante pins administrativos de migración; no se convierten en leases
supuestamente vigentes. Su liberación administrativa sigue pendiente de interfaz.

`ha_recovery.backup_lab` detiene controles y DataNodes antes de capturar el conjunto:
snapshot etcd con hash, objetos cifrados, inventarios y material autorizado de claves.
El bundle tiene ACL privada y hashes de archivos. Las copias de filesystem de este
procedimiento son **respaldo**, no evidencia de replicación S/S.
`RestoredHACluster` verifica hashes, usa directorios nuevos, otra membresía/token
etcd, `--bump-revision=1000000000 --mark-compacted`, cambia explícitamente la época
y rechaza handles/sesiones/ejecutores previos. Conserva contenido y resultados.
El laboratorio reutiliza puertos C/S únicamente después de detener el original;
los miembros etcd restaurados tienen endpoints nuevos. No se usa `--force-new-cluster`.
Un rollback a SQLite anterior después de escrituras HA descartaría cambios y no
es un procedimiento admitido.

## Reproducción PowerShell y alcance de las verificaciones

```powershell
.\.venv-win\Scripts\python.exe scripts/fetch_etcd.py --platform windows-amd64 --tools
.\.venv-win\Scripts\python.exe scripts/generate_proto.py --check
.\.venv-win\Scripts\python.exe scripts/verify_stage7.py --ha-only
.\.venv-win\Scripts\python.exe scripts/verify_stage7.py --measure
# Comprobación acotada de migración y restauración completas:
.\.venv-win\Scripts\python.exe -m pytest -q tests/test_stage7_control.py -k migration
```

`--ha-only` no acredita regresiones anteriores. El comando sin esa opción ejecuta
la suite conjunta; `--measure` añade 512 MiB y parche 4 KiB. Cada ejecución usa
puertos y raíces nuevas y detiene los procesos creados. Ver los resultados
efectivamente ejecutados en [evidencias](evidencias/etapa7/README.md), sin inferir
aprobación por la sola existencia de un script.

Etcd, SQLite de DataNodes, WAL, snapshots y backups están protegidos por ACL del
usuario del laboratorio; no se ha probado cifrado de volumen. AES-GCM protege los
objetos de bloques. Clientes y DataNodes no reciben credenciales de etcd; cada
control tiene identidad mTLS y permiso sobre el prefijo asignado. CA de desarrollo
y herramientas administrativas permanecen fuera de los directorios de identidad
usados por los servidores. La seguridad integral continúa en E8.

### Laboratorio interactivo persistente

En una terminal PowerShell, con una raíz nueva:

```powershell
.\.venv-win\Scripts\python.exe scripts/run_ha_lab.py --directory .runtime/ha-demo
```

El supervisor publica `.runtime/ha-demo/ready-ha.json` solo después de comprobar
registro y disponibilidad. En otra terminal se usa la misma CLI de RF1/RF2/RF3:

```powershell
.\.venv-win\Scripts\python.exe -m dfsha.client.cli --config .runtime/ha-demo/client.toml login admin
.\.venv-win\Scripts\python.exe -m dfsha.client.cli --config .runtime/ha-demo/client.toml nodes
.\.venv-win\Scripts\python.exe -m dfsha.client.cli --config .runtime/ha-demo/client.toml shell
```

La contraseña de la cuenta de desarrollo es `development-password`, introducida
en el prompt; es una cuenta del laboratorio y no credencial de producción.
Dentro de la shell: `mkdir /demo`, `send ruta-local /demo/file`,
`open /demo/file r+ a`, `read a 0 16 lectura.bin`, `write a 0 delta.bin`,
`close a`. Los argumentos son los de `dfsha.client.cli --help`.

Para detener solo este laboratorio, crear `.runtime/ha-demo/stop-ha`; el supervisor
espera el cierre de sus procesos. Para reanudar los mismos volúmenes:

```powershell
New-Item -ItemType File -Path .runtime/ha-demo/stop-ha -Force
.\.venv-win\Scripts\python.exe scripts/run_ha_lab.py --directory .runtime/ha-demo --resume
```

La reanudación conserva la época; no vuelve a migrar ni inicializa claves nuevas.
Los leases conservan sus límites y una pausa mayor que su vigencia exige reapertura.
El verificador comprueba esta ruta mediante `ExistingHACluster`; el estado aprobado
o pendiente se registra en las evidencias, sin presuponer que la documentación la valida.

### Respaldo y restauración desde la terminal

El supervisor puede capturar un bundle privado al detenerse. Usar rutas nuevas
para el bundle y la restauración, y esperar su salida antes de iniciar el restaurado:

```powershell
.\.venv-win\Scripts\python.exe scripts/run_ha_lab.py --directory .runtime/ha-demo --resume --backup-on-stop .runtime/backups/ha-demo-1
# En otra terminal:
New-Item -ItemType File -Path .runtime/ha-demo/stop-ha -Force
# Tras el cierre y confirmación del respaldo:
.\.venv-win\Scripts\python.exe scripts/run_ha_lab.py --directory .runtime/ha-restored --restore-from .runtime/backups/ha-demo-1
```

El procedimiento detiene mutaciones, mantenimiento y DataNodes antes de copiar,
verifica el bundle y restaura tres miembros en directorios independientes.
El bundle contiene claves privadas: queda fuera de Git y requiere custodia como
el volumen original. Restaurar exige login y aperturas nuevas por cambio de época.
