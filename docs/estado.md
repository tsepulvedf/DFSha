# DFSha — Estado del proyecto y continuidad

Actualizado: 2026-09-11 · **ETAPA 5 COMPLETA en Windows local**, R=1/W=1.
RF3 implementa seis modos de apertura, snapshots, lectura por rangos, write atómico
de hasta 16 MiB, PatchBlock directo cliente–DN, locks/leases con fencing comprobado
al publicar, renovación, resultados idempotentes y recuperación tras reinicio.
Se activa con `lab_hito2.py init --rf3` en una raíz nueva; H1/H2 conservan sus
perfiles. [Semántica, demo y límites](etapa5-rf3.md).

EJECUTADO: **114 pruebas aprobadas, cero fallos/errores/omisiones**, 647,27 s.
[Regresión final](evidencias/etapa5/20260911T045117Z/result.json): H1/H2, RF3,
TLS/mTLS, contratos y seguridad de dependencias. 56 RPC compilables, 34 módulos
importados; perfil E5: 54 implementadas y dos futuras. Wheel instalado con
[prueba RF3 real desde site-packages](evidencias/etapa5/installed-smoke.json).

[Medición final](evidencias/etapa5/20260911T045117Z/measurement.json): archivo de
512 MiB con bloques de 64 MiB, parche de 4096 bytes en 3,734 s y SHA-256 esperado.
El cliente transmite el delta; control transporta cero contenido. Máximos
residentes: tres sesiones SDK en un proceso **63,6 MiB**, control **64,0 MiB**,
DN máximo **55,8 MiB**. Dos preparaciones concurrentes publican versiones 3 y 4
con ambos cambios verificados. Los perfiles 4/64/128 MiB tienen pruebas funcionales;
estas mediciones no se extrapolan a todos ellos.

La regresión H2 inicial aprobó 100 pruebas, pero dos mediciones fallaron por
reinscripción tras un heartbeat sin respuesta. D44 corrige la continuidad del
registro; la [repetición H2 corregida](evidencias/etapa5/h2-measurement-fixed.json)
aprobó 512 MiB con tres procesos cliente. Los fallos permanecen en
[el inventario de evidencias](evidencias/etapa5/README.md).

Git inicial E5: main y origin/main en `92dd53b`; historial E2–E4 conservado.
Implementación y verificación terminadas; commit y sincronización E5 pendientes
del cierre Git de esta sesión. No se modificó la identidad del autor.

Límites: un control/SQLite, R=1/W=1 y un host no acreditan HA. Linux está
BLOQUEADO POR ENTORNO (WSL no instalado); Docker/Internet/cloud no ejecutados.
RNF6 integral, cifrado de volúmenes/backups y Q01–Q07 siguen pendientes.
Siguiente: **E6, replicación y recuperación de datos**; no ejecutada. E7 será
HA del control/metadatos, E8 seguridad integral, E9 cloud y E10 benchmarks.

## Etapa 4: resultado histórico conservado

Actualizado: 2026-09-10 · **ETAPA 4 COMPLETA en Windows local**, con R=1/W=1. E1–E3 preservadas; revisión docente no presupuesta.

E4 implementa un ControlNode y tres/cuatro DataNodes independientes, RF1/RF2
reutilizados, SQLite/CQRS en control sin contenido, inventarios persistidos y
objetos cifrados en cada DN, registro/heartbeats/reconciliación mTLS, colocación
por métricas y reservas, autorizaciones online y recibos durables, copia S/S y
GC por tareas. El modo H1 sigue disponible. [Demo H2](hito2.md),
[protocolos H2](protocolos-hito2.md), [D31–D35](etapa4-diseno.md),
[evidencia actual](evidencias/etapa4/README.md).

EJECUTADO en cierre E4: **100 pruebas, cero fallos/errores/omitidos**, 403,78 s;
34 módulos importados, 54 RPC compilables, **45 implementadas en E4 y 9 futuras**.
H1 conserva 30 implementadas incluyendo diagnóstico y 24 futuras. [Resultado](evidencias/etapa4/20260910T225730Z/result.json),
[XML](evidencias/etapa4/20260910T225730Z/pytest.xml). Wheel instalado fuera del
editable con [roundtrip real de 8 MiB](evidencias/etapa4/installed-smoke.json) y
[verificación de paquete](evidencias/etapa4/package.json).

Medición E4 final: 512 MiB/3 clientes, SHA-256 idéntico, ocho bloques de 64 MiB
en tres DN; control con cero contenido. Máximos residentes: cliente **56,2 MiB**,
control **82,1 MiB**, DataNode **56,5 MiB**; límites 256/512 MiB satisfechos en
esa ejecución. [Medición y tabla por nodo](evidencias/etapa4/20260910T225730Z/measurement.json).
La copia S/S y lectura sin origen se comprueban en otro laboratorio, con
recibo recuperado tras reiniciar destino. Los resultados iniciales de 99 pruebas
y su medición se conservan como historial.

Git al comenzar E4: main limpia y origin/main en `d91e2ba5a2dd7addbacbc7e94a0fe3deeae1a9e1`,
historial E2 `df1fd33`, E3 `7bd8327` y cierre E3 `d91e2ba` conservados.
E4 publicada: **`48509a69f1d459b3902119ea13f85daed71ab0a6`**, push normal a
origin/main, hash remoto idéntico verificado. [Evidencia Git](evidencias/etapa4/git-publicacion.json).
Este registro de publicación se incorpora en un commit documental posterior;
la referencia funcional anterior permanece estable. No hay bloqueo de identidad
ni autenticación. Ningún recurso cloud fue aprovisionado.

Límites E4: R=1/W=1, un control/SQLite, un solo host; no etcd requerido, HA ni
replicación automática. Q01–Q07 siguen sin nuevas respuestas. Linux/Docker,
Internet y VMs no acreditados. E5 RF3 completo será siguiente, E6 replicación,
E7 HA control y metadatos, E8 seguridad integral, E9 cloud, E10 benchmarks.

## Etapa 3: resultado histórico conservado

**ETAPA 3 COMPLETA en Windows, alcance H1 local.** RF1/RF2,
CLI/shell/SDK TLS, usuarios/grupos/ACL, SQLite/CQRS, bloques AES-GCM, snapshots,
overwrite, pins, idempotencia y recuperación. RF3 completo, distribución,
replicación, HA, RNF6 integral y cloud siguen pendientes. [Demo](hito1.md),
[contrato efectivo](protocolos-hito1.md), [D25–D30](etapa3-diseno.md).

EJECUTADO: **87 pruebas, cero fallos/errores/omitidos/advertencias**, 142,86 s;
34 módulos de contratos, catálogo 51 RPC (27 H1, tres diagnósticas, 21 futuras),
wheel instalado/importado fuera del editable. Medición 1 GiB/3 clientes: máximo
cliente **51,6 MiB**, servidor **81,5 MiB**, metas 256/512 MiB satisfechas en esa
ejecución. [Resultado final](evidencias/etapa3/20260909T195446Z/resultado.json),
[XML](evidencias/etapa3/20260909T195446Z/pytest.xml),
[medición](evidencias/etapa3/20260909T195446Z/medicion.json), [paquete](evidencias/etapa3/paquete.json).
Fallos iniciales conservados: ACL Windows, reconexión, margen del deadline y
conexiones frías de login; corregidos y reejecutados sin ocultar resultados.

Git vigente: **main publicada y siguiendo origin/main** en
https://github.com/tsepulvedf/DFSha.git. Referencia E2 `df1fd33`; implementación E3
`7bd83277dd592124d10f2ced996940e27a9107c8`. Push ejecutado sin force; `git ls-remote`
confirmó ese mismo hash remoto. Identidad Git existente, sin inventar autor.
[Evidencia de publicación](evidencias/etapa3/git-publicacion.json). El cierre
documental se registra en un commit posterior, conservando el commit funcional.

Bloqueo temporal del revisor automático por cuota resuelto al reanudar.
Linux/WSL/Docker/cloud no ejecutados; H1 Windows no depende de ellos ni de etcd.
Q01–Q07 sin nuevas aclaraciones. Próxima etapa prevista en ese cierre: E4, procesos separados,
registro/heartbeats, métricas/reservas/colocación y bytes directos cliente–DN;
pruebas 512 MiB/1 GiB. RF3 E5, réplica E6, control/etcd HA E7. W=2 de datos final
no es mayoría de metadatos.

<a id="etapa2"></a>
## Etapa 2: resultado histórico conservado

Esta sección registra el cierre E2 anterior a `df1fd33`; números y estados Git
son históricos. Para estado actual rige E4 arriba.

Ruta ejecutada: **Windows, Python 3.12.10 en .venv-win**, grpcio/grpcio-tools 1.83.1, Protobuf 7.36.1, cryptography 50.0.1, argon2-cffi 25.1.0, pytest 9.1.1 y etcd 3.6.14 oficial. Dependencias transitivas con hashes; [entorno.md](entorno.md) contiene comandos PowerShell/Linux y versiones. Python existente finalmente se reconoce en PATH/launcher; las observaciones de E1 fueron revisadas. Docker/Compose no encontrados en PATH/rutas habituales/servicios; WSL indica subsistema no instalado. Windows etcd valida compatibilidad, Linux sigue pendiente de ejecución.

Repositorio único: [tsepulvedf/DFSha](https://github.com/tsepulvedf/DFSha). **Remoto creado y lectura verificada; carpeta local vinculada a origin; cambios NO sincronizados.** Se consultó remoto vacío antes de inicializar; main proviene de la API GitHub. HEAD main aún sin primer commit, archivos sin seguimiento. No se asignó autor, no se hizo commit/push ni se verificó permiso de escritura. Antes de publicar, reconsultar historial. [Evidencia de vinculación](evidencias/etapa2/entorno-git.json).

| Entrega | Estado y alcance |
| --- | --- |
| Estructura | src/dfsha/{client,control,datanode,common}, proto/dfsha/v1, tests, deploy, scripts y evidencias creados. MetadataStore/Coordinator/BlockStore/Authorizer son interfaces, no negocio simulado. |
| Contratos | 50 RPC propias, tablas completas en [protocolos](protocolos.md), [catálogo](rpc-catalog.json), stubs generados en src; oficiales etcd con fuentes/licencias/hashes intactos en third_party. 47 RPC futuras UNIMPLEMENTED, verificadas una por una. |
| Ejecución | Tres RPC DiagnosticService implementadas, servidor/cliente como procesos separados, TLS público y mTLS interno, loopback, deadlines, logging permitido y cierre ordenado. |
| Seguridad | CA/SAN correctos y rechazos de CA ajena/nombre incorrecto/cliente sin certificado; AES-GCM positivo/tamper/AAD y Argon2id correcto/incorrecto. Seguridad del DFS E3/E8 PENDIENTE. |
| etcd | Instancia aislada real: KV, CAS aceptado/rechazado, lease creado/vencido, Lock/Unlock y fence obsoleto, Watch, mTLS/RBAC y error por servicio detenido. Prefijo propio limpiado; WAL/logs locales ignorados conservados. No hay clúster/HA. |
| H1 local | Configuración SQLite/bloques locales y prueba SQLite de persistencia/rollback. Arranque no depende de etcd. Adaptadores/operaciones RF1/RF2 empiezan en E3. |
| Reproducibilidad | Bootstrap PowerShell probado; generación/importación, wheel limpio y scripts start/client/stop probados. Bash/Linux preparados, PENDIENTES de ejecución. |
| Evidencias | [Índice E2](evidencias/etapa2/README.md), JSON/XML con comandos exactos/versiones/hashes; fallos iniciales conservados con corrección y reejecución. |
| Documentación | README, entorno/protocolos, decisiones D03/D05/D19 y D21–24, matriz con filas E2, arquitectura con integridad precisada y este estado. Especificación/PDF/guía preservados. |

**EJECUTADO:** suite final de 70 casos; 0 fallos/errores/omitidos, incluyendo límites de mensajes y las 47 operaciones pendientes. Streaming: 8 MiB+17 B por dirección y listener, chunks≤256 KiB, hash independiente correcto. Fixtures de página64/CommitWrite5: 8399/7701 bytes; no se miden RSS ni rendimiento del DFS. [Resultado de ejecución](evidencias/etapa2/20260908T212227145653Z/resultado.json) y [XML](evidencias/etapa2/20260908T212227145653Z/pytest.xml).

**FALLIDO, RESUELTO:** pruebas iniciales exigían UNAVAILABLE en todos los rechazos/conexiones detenidas y encontraron DEADLINE_EXCEEDED antes de terminar el intento de conexión. Negativas TLS aisladas sobre IPv4 con SAN válido pasan sin relajar CA/SAN; indisponibilidad acepta y documenta ambos códigos de transporte dentro del plazo. Esas ejecuciones fallidas no cuentan como aprobadas. Restricciones iniciales de permisos/red se resolvieron mediante ejecución autorizada; no se eludió sandbox ni se instaló otra ruta del sistema.

**PENDIENTE:** sincronización GitHub, ejecución Linux, Q01–Q07, cuentas/cuotas/roles/custodios cloud, implementación RF1/RF2 E3, RF3 E5, replicación E6, consenso/HA E7, RNF6 integral E8 y demostración Internet E9. Estas tareas futuras no bloquean la base local de E2. **BLOQUEADO POR ENTORNO** solo aplica a ejecutar aquí Docker/WSL hoy; la ruta elegida está operativa.

Comandos de continuidad PowerShell:

```powershell
Set-Location -LiteralPath F:\DFSha
powershell -NoProfile -File scripts/bootstrap.ps1
.\.venv-win\Scripts\python.exe scripts/verify_stage2.py --clean-env
.\.venv-win\Scripts\python.exe scripts/audit_stage2.py
```

Conservar PDF/guía y la evidencia E1. Los cinco documentos originales de E1 están archivados en [documentos-originales.zip](evidencias/etapa1/documentos-originales.zip); su verificacion-documental.json sigue siendo evidencia histórica de esa versión, no hashes de los documentos ahora actualizados.

La siguiente etapa autorizable es **E3: implementar RF1/RF2 completos en un servidor modular con SQLite/local**, autenticación/TLS/persistencia e interrupciones verificables, para H1 semana 8. No se implementaron ahora esas operaciones. RF3 sigue obligatorio para la versión final.

### Criterios de cierre E2

| Criterio solicitado | Resultado verificable |
| --- | --- |
| Entorno elegido ejecuta verificaciones | CUMPLE: Windows/Python existente, bootstrap y procesos reales. |
| Dependencias fijadas/compatibles | CUMPLE: lock con hashes, pip check, wheel en venv nuevo. |
| Contratos se generan/importan | CUMPLE: fuentes propias/oficiales, 34 módulos, --check y -I sin editable. |
| Cliente/servidor por TLS | CUMPLE: procesos separados, público TLS e interno mTLS. |
| Streaming y negativas pasan | CUMPLE: hash/tamaño, límites, CA/SAN/cliente, deadline y cierre. |
| Python↔etcd real | CUMPLE: KV/Txn/lease/lock/Watch/mTLS/RBAC/indisponibilidad, cleanup prefijo propio. |
| Scripts/documentación repetibles | CUMPLE para ruta Windows: bootstrap, verificación y diagnóstico manual ejecutados; catálogo/enlaces auditados. Linux preparado pero no probado. |
| Monolito preparado para persistencia local | CUMPLE en alcance E2: interfaces/config SQLite/local y prueba de biblioteca; negocio E3. |
| Funciones futuras pendientes explícitas | CUMPLE: 47 UNIMPLEMENTED probadas; RF3 final obligatorio y E5 planificada. |
| Estado Git/acceso preciso | CUMPLE: remoto leído y origin vinculado; sin commits/push/sincronización, permiso escritura no probado. |

No quedan bloqueos que impidan cerrar **esta** etapa en su ruta elegida. Se puede comenzar E3 cuando sea la etapa activa solicitada; no se adelanta su implementación en E2.

<a id="inventario"></a>
## 1. Inventario y materiales consultados en E1 (histórico)

Carpeta de trabajo: `F:\DFSha`, Windows PowerShell. Al comenzar solo había dos archivos bajo `docs/`; se buscaron archivos ocultos e instrucciones `AGENTS.md` en la carpeta y su raíz. No existían `docs/estado.md`, código, tests, contratos, configuración, README, `.git`, `.agents` ni `.codex` locales. El archivo global de instrucciones consultado estaba vacío (0 bytes), sin reglas adicionales. No se accedió a conversaciones, memorias o archivos de otros proyectos de ChatGPT.

| Documento consultado | Relevancia y alcance de lectura |
| --- | --- |
| [SI3007-262-proyecto1-dfs.docx.pdf](enunciado/SI3007-262-proyecto1-dfs.docx.pdf) | Fuente principal. **Siete páginas leídas íntegramente**, extracción por página y revisión visual de pp. 2, 5, 6 y 7 para RNF8, comunicaciones, entregables, cronograma y rúbrica. Tamaño: 203.468 bytes. |
| [Prompts_Codex_DFSha_Opcion1_CS.md](propuesta/Prompts_Codex_DFSha_Opcion1_CS.md) | Guía complementaria completa, 761 líneas. Propone stack y once etapas; no prueba decisiones de otros chats ni resultados implementados. |
| Solicitud del usuario de etapa 1 | Opción 1, reglas de corrección, parámetros a evaluar, semántica snapshot propuesta, cinco documentos y límite de alcance. |
| [Fuentes técnicas oficiales](decisiones.md#fuentes) | Capacidades/compatibilidad documental de gRPC/Protobuf, etcd, SQLite, bibliotecas de seguridad, Docker y redes/discos cloud. Consultadas el 2026-09-07; no equivalen a pruebas de integración. |

Identidad de los archivos fuente, sin modificaciones realizadas sobre ellos:

```text
PDF SHA-256
0EC8CC4CF92F9CF9345D5CF147D096A9CC74F78146AABCE823D3890A31B446BF

Guía SHA-256
755D2BEBC288133E54E4F3161A433C35E6D08A9F0A7C8DCE9B9B031E41C902B3
```

Mapa de lectura del PDF:

| Página | Contenido revisado |
| --- | --- |
| 1 | Identificación del curso, nota sobre refinamiento hasta el 26 de agosto, objetivo, cliente/servicio, RF1–RF3 y RNF1. |
| 2 | RNF2–RNF8, opciones 1/2 y comienzo del marco teórico. RNF8 no añade requisitos concretos. |
| 3 | Discusión de bloques/objetos y referencias GFS/HDFS; material teórico, no una orden de instalar esos sistemas. |
| 4 | Definición del equipo, arquitectura según opción, ejemplos y ejecución sobre Internet. |
| 5 | Roles, cinco relaciones, ejemplos de protocolos, VMs, API por nodo y tres entregables con sus contenidos. |
| 6 | Semanas 6–13, hitos y primeras cuatro filas de evaluación. Semanas 9/11 vacías. |
| 7 | Replicación/consistencia, seguridad, video/informe/GitHub y recursos sugeridos. Numeración 5 repetida, sin corregirla al citar. |

<a id="archivos"></a>
## 2. Archivos entregados en E1 (histórico)

| Archivo creado | Contenido |
| --- | --- |
| [especificacion.md](especificacion.md) | Objetivo, problema, actores, alcance, RF1/RF2/RF3, rutas, modos, snapshots, offsets, locks, borrado, permisos, casos/metas y Q01–Q07. |
| [arquitectura.md](arquitectura.md) | Evolución H1–H3/final, responsabilidades/estado, metadatos, cinco relaciones, diagramas inicial/final/despliegue/secuencias, R/W, fallos, seguridad e infraestructura. |
| [decisiones.md](decisiones.md) | D01–D20, alternativas, clasificación de ejemplos, capacidades consultadas, compatibilidad pendiente y registro RNF8. |
| [matriz-requisitos.md](matriz-requisitos.md) | RF/RNF y obligaciones transversales, entregables, hitos, rúbrica, reglas USR, criterios, componentes y pruebas/evidencias previstas. |
| [estado.md](estado.md) | Inventario, acciones/resultados, límites, plan y continuidad. |
| [lectura-pdf.txt](evidencias/etapa1/lectura-pdf.txt) | Evidencia auxiliar: extracción íntegra por página con hash/método. El PDF sigue siendo la autoridad de contenido y formato. |
| [verificacion-documental.json](evidencias/etapa1/verificacion-documental.json) | Resultado de comprobaciones estructurales de los documentos; no certifica funcionamiento del DFS. |

Los diagramas se entregan en Mermaid editable dentro de arquitectura.md: componentes/despliegue del monolito, componentes finales, mediación del control, secuencia de escritura, secuencia de lectura y despliegue de VMs. La sintaxis y el alcance se revisan como documentación; no representan procesos desplegados.

<a id="verificacion"></a>
## 3. Acciones ejecutadas en E1 (registro histórico)

| Estado | Acción/comando realizado | Resultado y alcance |
| --- | --- | --- |
| EJECUTADO | `Get-Location`, `rg --files --hidden` con exclusiones iniciales y búsquedas de AGENTS.md. | Inventario inicial de dos documentos; carpeta actual confirmada; sin instrucciones locales adicionales. |
| FALLIDO | `git status --short`. | `fatal: not a git repository`. Diagnóstico: no hay Git inicializado. No se crearon commits, ramas ni remoto. |
| EJECUTADO | `Get-Content` de la guía; relectura por rangos con `-Encoding UTF8`. | Lectura completa. La primera visualización tenía caracteres mal decodificados por PowerShell; se corrigió la lectura, sin modificar el archivo. |
| EJECUTADO | `Get-Item` y `Get-FileHash ... -Algorithm SHA256` del PDF. | Tamaño/hash identificados; el hash posterior coincide con el inicial. |
| BLOQUEADO POR ENTORNO | `Get-Command python,python3,pdftotext,mutool,...`; `py -0p` y `py -c ...`. | No hay Python registrado (`No installed Pythons found!`) ni lector PDF de consola encontrado en PATH. No se ejecutó código Python del proyecto. |
| EJECUTADO | `Get-Command py,node,npm,dotnet,...`; `node --version`. | Node.js v22.16.0 disponible; py es solo lanzador sin Python registrado. Docker no fue encontrado en PATH; una instalación fuera de PATH no fue verificada. |
| FALLIDO, RESUELTO PARA LECTURA | `npm.cmd cache ls pdf`. | EPERM al leer caché predeterminada. Se usó aprobación del entorno para descargar un lector en carpeta temporal; no se cambió el stack del proyecto. |
| EJECUTADO | `npm.cmd install --prefix "$env:TEMP\dfsha-stage1-pdf" --cache "$env:TEMP\dfsha-stage1-npm-cache" --no-save --ignore-scripts pdfjs-dist@5.4.149`. | Descarga temporal autorizada; tres paquetes agregados. Herramienta de lectura documental, no dependencia de DFSha. |
| EJECUTADO | Script temporal Node con PDF.js: `getDocument`, `getTextContent` para páginas 1–7; renderizado con canvas de pp. 2/5/6/7 y visualización. | Siete páginas extraídas y leídas; tablas/elipsis contrastadas visualmente. Texto conservado en lectura-pdf.txt. |
| EJECUTADO | Consultas web a documentación oficial y fichas de paquetes mantenidas. | Fuentes enlazadas en decisiones.md; capacidades y mínimos Python contrastados. No se ejecutó stack DFSha. |
| EJECUTADO | Edición de cinco Markdown y generación de evidencia textual. | Únicamente documentación; archivos originales preservados. |
| EJECUTADO | Auditoría Node de existencia, enlaces/anchors locales, estructura de tablas, cobertura de IDs y hashes de fuentes. | Resultado concreto en verificacion-documental.json; las verificaciones de servicio no están incluidas. |
| PENDIENTE | Generar/renderizar diagramas con la toolchain documental final y exportar informe. | E1 entrega fuente Mermaid; la revisión visual del PDF fuente no debe confundirse con renderizado de los diagramas de diseño. |
| PENDIENTE | RPC real, pruebas RF/RNF, benchmark, Docker y despliegue cloud. | Corresponden a etapas posteriores; ninguna cuenta como aprobada. |

Durante **E1** no se instalaron Python, Docker, etcd ni dependencias de aplicación; tampoco se crearon src/proto/tests/deploy, VMs ni certificados. E2 añade la base descrita al inicio; los requisitos funcionales de los hitos y cloud siguen PENDIENTES.

<a id="restricciones"></a>
## 4. Restricciones, información faltante y riesgos

El entorno permite escritura de proyecto en `F:\DFSha` y temporales, con restricciones de red/permisos. La lectura del PDF se resolvió con una herramienta temporal aprobada; no queda bloqueada la especificación por falta de PDF.

| Situación | Estado y siguiente acción |
| --- | --- |
| Python y herramientas de ejecución | RESUELTO E2: Python 3.12.10 existente/venv operativo. Docker/Compose/WSL no disponibles; no impiden ejecutar la ruta nativa escogida. Linux pendiente. |
| Git local, remoto y README | RESUELTO vínculo E2: origin al remoto indicado, acceso de lectura verificado, README creado. Sincronización y permiso de escritura PENDIENTES; no hay commits. |
| Cuenta AWS Academy/GCP, IAM, créditos, cuotas, zonas, direcciones y dominio | PENDIENTE de información/verificación. No se intentó un despliegue ni se ha demostrado una denegación del proveedor. Se diseñó inventario/red/capacidad en A10–11. |
| Integrantes, responsabilidades, fechas calendario y custodios de claves | PENDIENTE del equipo; no se asignan nombres ni fechas de entrega inferidas. |
| Versión definitiva docente y aclaraciones | Q01–Q07 registradas en especificación. Mantener la fuente actual hasta recibir material accesible posterior. |
| Binding Python de etcd/protos y versiones exactas | RESUELTO compatibilidad E2 por API/stubs oficiales y conexiones reales. Adaptadores MetadataStore/Coordinator y clúster definitivo PENDIENTES E7. |
| Tres miembros por host físico/zona | Solo VMs/volúmenes independientes diseñados; independencia física real requiere verificar proveedor/colocación. Tres contenedores locales no acreditan pérdida de host. |
| Coste de etcd, introspección por bloque, GC y colocalización | Riesgos de rendimiento a medir; topes/paginación y carga acotada definidos. No existe resultado de benchmark. |

La interpretación de RNF4 para archivos pequeños, el conjunto exacto de mecanismos RNF6, el nivel de transparencia, la semántica de RF3 y la mediación CN–etcd–CN permanecen explícitos para revisión docente. No impiden completar el diseño solicitado y no se declaran aceptados por el docente.

<a id="plan"></a>
## 5. Plan de ejecución y entregas

El PDF es autoridad para las semanas. Las etapas son organización interna tomada de la guía, compatibles con el cronograma. Las semanas 9/11 no incorporan hitos docentes nuevos. No convertir la fecha de esta sesión a una semana del curso sin calendario del grupo.

| Etapa | Trabajo y dependencia | Resultado verificable | Hito / estado real |
| --- | --- | --- | --- |
| 1 | Leer fuentes, inventariar y formalizar. | Cinco documentos, matriz, decisiones y diagramas; fuente íntegra revisada. | Semana 7, especificación; EJECUTADO documentalmente. Revisión/entrega académica pendiente. |
| 2 | Partir del diseño E1; preparar Python/toolchain/entorno y contratos. | Estructura, dependencias fijadas, stubs, configuración, TLS/mTLS, logging, protocolos/entorno; RPC real y acceso etcd v3 comprobados. | Preparación H1; EJECUTADO, evidencia E2 arriba. |
| 3 | Con E2 verificable, implementar un cliente y un servidor modular. | RF1/RF2 completos, persistencia, TLS/auth y cifrado local; pruebas de árbol, transferencias/interrupciones; docs/hito1.md y referencia Git. | Semana 8, H1; PENDIENTE. |
| 4 | Solo después de H1 validado, separar CN/DN. | Registro/descubrimiento, particionamiento en bloques, streams a varios DN, lectura/escritura distribuida, APIs S/S y docs/hito2.md. Si R=1/W=1 temporal, declarar ausencia de HA. | Semana 10, H2; PENDIENTE. |
| 5 | Sobre el sistema distribuido, implementar RF3. | Handles/snapshots, offsets, PatchBlock, locks/fencing, concurrencia por bloque y tombstones con pruebas. | Hacia H3; PENDIENTE. |
| 6 | Replicar y recuperar datos usando las mismas versiones/operaciones. | R=3/W=2, recibos auténticos, retry idempotente, corrupción/reparación, prueba de cuarto DN y GC segura. | Hacia H3; PENDIENTE. |
| 7 | Migrar estado de control a autoridad compartida. | Tres CN/tres etcd, Txn/CAS, leases/fencing distribuidos, failover, quórum, backup/restore y migración verificada. | Hacia H3; PENDIENTE. |
| 8 | Completar y auditar seguridad transversal. | TLS/mTLS, usuario/grupo/ACL, autorización DN, cifrado y claves recuperables; docs/seguridad.md y docs/hito3.md con pruebas E5–8. | Semana 12, H3; PENDIENTE. |
| 9 | Con sistema verificado y cuenta disponible, desplegar. Preparación de acceso desde E1. | VMs académicas distintas, C/S por Internet y S/S privado, persistencia y prueba de perder host desde cliente externo; docs/despliegue.md. | Antes de final; PENDIENTE. |
| 10 | Consolidar pruebas continuas y cargas según recursos. | Metodología, scripts, CSV/JSON, gráficas reales y docs/pruebas-resultados.md; cubrir tres dimensiones RNF1. | Antes de final; PENDIENTE. |
| 11 | Auditar PDF/clarificaciones contra implementación y evidencia. | Informe PDF/Word revisado, GitHub reproducible, video 10–15 min y docs/auditoria-final.md. | Semana 13, final; PENDIENTE. |

Los contenidos obligatorios del informe y la rúbrica completa están en [matriz, entregables](matriz-requisitos.md#entregables) y [matriz, evaluación](matriz-requisitos.md#rubrica). La suma de pesos es 100%; no se inventan aspectos donde el PDF deja elipsis.

<a id="aceptacion"></a>
## 6. Aceptación de etapa 1

| Criterio solicitado | Verificación documental / estado |
| --- | --- |
| PDF íntegro y fuentes identificadas | CUMPLE: siete páginas leídas, hash y extracción; revisión visual de páginas críticas y fuentes técnicas enlazadas. |
| Todos los requisitos/obligaciones en matriz | CUMPLE: RF1–3, RNF1–8, objetivo, definición/opción 1, comunicaciones/APIs, infraestructura, entregables, semanas/hitos y siete criterios de evaluación. |
| Criterio observable y evidencia prevista por requisito | CUMPLE documentalmente: matriz y catálogo T-ID, con etapas/componentes previstos. No son resultados funcionales. |
| RF3 con semántica y plan | CUMPLE: S6, A6–8; modos/offsets/EOF, snapshots, write/close, locks, escritores compatibles y borrado. Implementar E5, coordinación final E7. |
| Cinco relaciones descritas | CUMPLE: A4; CN–CN mediado por etcd, con Q05 registrada. |
| Monolito y distribuido diferenciados | CUMPLE: A1–2 y diagramas; H1 se conserva y no reclama HA. |
| Disponibilidad incluye datos/control/metadatos/acceso | CUMPLE en diseño: A8–10 también cubren claves, DNS/entradas, quórum y dominios de fallo. |
| Propuestas separadas de PDF | CUMPLE: clases PDF/USR/INT/DIS, D01–D20 y tratamiento de ejemplos/elipsis. |
| Cinco archivos existentes y coherentes | CUMPLE documentalmente, sujeto al resultado conservado de auditoría estructural y revisión cruzada. |

**Etapa 1 completa como entrega de especificación y diseño del archivo disponible.** No declara aprobación docente, cumplimiento funcional final ni validación cloud. La toolchain pendiente entonces quedó comprobada en E2; las consultas docentes siguen abiertas.

<a id="retomar"></a>
## 7. Instrucciones para continuar en otra sesión

Leer primero este estado, [matriz-requisitos.md](matriz-requisitos.md), [decisiones.md](decisiones.md) y cualquier AGENTS.md nuevo; inventariar cambios antes de editar. Preservar PDF/guía y la evidencia del monolito cuando exista. Ejecutar solo la etapa autorizada y sus dependencias imprescindibles. Actualizar matriz al recibir aclaraciones docentes; no copiar propuestas técnicas como requisitos del PDF.

El siguiente trabajo es **etapa 5: RF3 y concurrencia parcial**, solo cuando se
autorice. Preservar H1 y H2 comprobados, contratos y perfiles por archivo. Diseñar
e implementar read/write por offset, PatchBlock, modos de apertura y locks con
fencing, sin perder cambios compatibles. Réplica automática E6, control HA E7.
No volver a ejecutar E4 como una etapa pendiente ni avanzar automáticamente a E5.

Reglas que deben persistir: RF3 final obligatorio; bytes finales cliente–DataNode; lectura/escritura mediante varios nodos; ubicación dinámica; W de datos separado de quórum; publicación atómica; fencing en commit; deltas compatibles sin sobrescribir cambios ajenos; tombstones/GC seguros; HA también de control/metadatos/entrada/claves; autorización DN; criptografía/consenso de bibliotecas; evidencia local y cloud diferenciada. Nada no ejecutado cuenta como aprobado.
# Actualización histórica: etapa 3

El prompt de etapa 3 del usuario sustituye las propuestas anteriores que contradiga.
[Decisiones D25–D29 y diseño previo a implementación](etapa3-diseno.md).
Referencia revisada de etapa 2: commit `df1fd33`; regresión ejecutada: 70 pruebas aprobadas.
La implementación y verificación E3 están COMPLETAS en alcance H1 local;
la ejecución final y los límites se registran al comienzo de este documento.
