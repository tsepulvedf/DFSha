# Evidencias y cierre E7

E7 **COMPLETA en el laboratorio Windows de fallos de procesos**. Los resultados
E6 se conservan como antecedentes. [Inventario final verificable](verificacion-final.json):
144 aprobadas/4 fallidas en la suite conjunta y ocho aprobadas en la repetición
de cuatro casos corregidos más cuatro nuevos; **152 casos distintos aprobados**,
sin omisiones. No se presenta como una única ejecución verde de 152.
La [correspondencia de aceptación](aceptacion.md) relaciona cada criterio con
su caso concreto; el cierre depende de sus resultados, no de la cantidad de tests.

| Ejecución | Resultado observado |
| --- | --- |
| `20260914T183439Z/result.json`, `pytest.xml` | 144 aprobadas, 4 fallidas, 2246,477 s. Dos expectativas antiguas de RpcError frente a OUTCOME_UNKNOWN; Lock con deadline de 6 s; GetProtection cancelado al parar su control. No contar la suite completa como aprobada. |
| `final-corrections.xml` | 8 aprobadas, cero fallos/omisiones, 391,233 s: recuperación H1/H2, concurrencia HA y relevo de mantenimiento; cuatro pruebas TLS de reintento de consulta y rechazos que no se reintentan. |
| `package-final.json`, `installed-smoke.json` | Wheel final construido/instalado, 34 módulos importables, sesión/handle/parche y descarga reales desde site-packages con HA. |
| `measurement-final.json` | Informe terminal EJECUTADO con SDK final, 512 MiB, ambos hashes, R3/W2, delta 4096 bytes y lectura tras caída del CN. [Tablas](medicion.md). Sesión 16476 interrumpida después: código de salida no recuperable; cierre y contenido terminal comprobados. |
| `20260914T045453Z/interrupted.json` | PENDIENTE/INTERRUMPIDO: sin resultado final ni procesos activos al recuperar. No acredita aprobaciones de su suite; logs privados conservados. |
| `metadata-quorum-partition-restore.xml` | 5 aprobadas, 62,51 s. Tres miembros etcd reales; pérdida de líder/mayoría, publicación y leases, Watch/compactación, partición TCP de un cliente del adaptador, snapshot y restauración de **metadatos** en un clúster nuevo. |
| `control-patch-deadlines.xml` | 1 aprobada, 159,32 s. Tres controles y tres DataNodes: namespace compartido, sesión/handle cruzados, subida de 5.000.000 bytes, parche de dos bytes cruzando bloques y lectura tras detener el control de apertura. |
| `metadata-repeat.xml`, `watch-first.xml` | Comprobaciones iniciales del adaptador; no sumar sus casos repetidos al total anterior. |
| `control-concurrency.xml` | 2 aprobadas, 452,15 s. Caso básico y dos escritores en controles diferentes: preparaciones concurrentes, W2 antes de ambos commits, mezcla sin pérdida y respuesta perdida recuperada desde el tercer control. |
| `control-recovery.xml` | 1 aprobada (migración y restauración completas), 1 fallida (failover antes de commit); duración conjunta 163,14 s. No presentar toda la ejecución como aprobada. |
| `control-failover-fencing.xml` | 2 aprobadas, 258,073 s. Caída antes de commit, reinicio del CN, partición TCP de un CN, pérdida de líder/mayoría etcd y recuperación; escritor vencido con W2 rechazado. |
| `control-maintenance-restart.xml` | 1 aprobada (relevo del mantenimiento, rechazo de callback antiguo y snapshot protegido), 1 fallida (timeout de login antes de reiniciar); 385,53 s, con otra medición simultánea. |
| `control-restart-isolated.xml` | 1 aprobada, 87,518 s: reinicio del conjunto con volúmenes, misma época y sesión/handle aún vigentes. No acredita supervivencia tras expiración. |
| `measurement-first.json` | FALLIDO: no alcanzó W2 dentro del plazo; no se publicó el archivo. |
| `measurement-isolated.json` | FALLIDO: `PERMISSION_DENIED` durante PutBlock con 512 MiB y bloques de 64 MiB. Carrera de rutas reproducida y corregida; límites de la atribución retrospectiva en el [diagnóstico](diagnostico-putblock.md). Evidencia original conservada. |
| `measurement-traced.json` | FALLIDO al final: segunda descarga local sin overwrite explícito. Subida, hash inicial, R3, parche y lectura tras failover sí completaron; no contar toda la medición como aprobada. |
| `path-race-before.xml`, `path-race-fixed.xml` | Carrera Windows reproducida (1 fallo/1 aprobada) y corrección (2 aprobadas). [Diagnóstico](diagnostico-putblock.md). |
| `package.json` | Wheel construido e instalado en venv separado; 34 módulos de contratos importables y entradas CLI verificadas. La prueba funcional instalada se registra aparte. |
| `measurement-fixed.json` | EJECUTADO, código de salida 0 recuperado de sesión 60206. 512 MiB, ambos SHA-256 correctos, R3, parche 4096 bytes, failover. [Tablas y límites de esa ejecución](medicion-fixed.md). |

Los XML anteriores de `control-*` fallidos conservan los errores encontrados:
plazos de arranque, renovación del mantenimiento, referencia opcional de handle,
logger y deadline interno de PatchBlock. No cuentan como pruebas aprobadas.
`control-ha-deadlines.xml` y `control-optional-reference.xml` incluyen paradas
solicitadas del laboratorio tras identificar fallos; no prueban failover exitoso.

Comandos PowerShell de estas dos verificaciones aprobadas (repetir ejecuta el
código actual, que puede incorporar cambios posteriores a esos XML):

```powershell
.\.venv-win\Scripts\python.exe -m pytest -q tests/test_stage7_metadata.py --junitxml=docs/evidencias/etapa7/metadata-repeat-current.xml
.\.venv-win\Scripts\python.exe -m pytest -q tests/test_stage7_control.py --junitxml=docs/evidencias/etapa7/control-repeat-current.xml
```

Los entornos se crean bajo `.runtime/tests/<UUID>`; certificados, claves, WAL,
snapshots etcd y bloques no se incluyen en Git. El laboratorio comprueba fallos
de procesos/red local, no pérdida de hosts ni acceso desde Internet.

## Comandos del cierre

PowerShell, ejecutados secuencialmente:

```powershell
.\.venv-win\Scripts\python.exe scripts/verify_stage7.py
.\.venv-win\Scripts\python.exe -m pytest -q tests/test_control_failover_transport.py tests/test_hito1.py::test_fault_recovery_and_lost_commit_response tests/test_hito2.py::test_interruption_expiry_restart_and_late_receipts tests/test_stage7_control.py::test_cross_control_parallel_publication_and_lost_reply tests/test_stage7_control.py::test_maintenance_takeover_rejects_old_callback_and_preserves_snapshot --junitxml=docs/evidencias/etapa7/final-corrections.xml
.\.venv-win\Scripts\python.exe scripts/check_package_stage3.py --python .venv-verify-20260908T212227145653Z/Scripts/python.exe --evidence docs/evidencias/etapa7/package-final.json
.\.venv-verify-20260908T212227145653Z\Scripts\python.exe -I scripts/check_installed_stage7.py
.\.venv-win\Scripts\python.exe scripts/measure_stage7.py --evidence docs/evidencias/etapa7/measurement-final.json
```

Para una nueva reproducción integral usar `scripts/verify_stage7.py --measure`;
no reutilizar archivos de evidencia históricos. Los sidecars `command-*.txt`
conservan progreso local ante interrupciones y se excluyen de Git; el JSON final
contiene la salida revisada. Sus hashes de fuentes corresponden a los archivos
al finalizar: los tests H1/H2 se editaron después de su colección y se comprobaron
con sus expectativas nuevas en `final-corrections.xml`, no en el XML anterior.

Fallos corregidos: [D57 y diagnóstico Windows](diagnostico-putblock.md),
[D58: deadlines y cancelación de consulta](../../etapa7-ha-control.md).
La repetición conserva LOCK_CONFLICT, fencing y rechazo de callbacks antiguos;
no acepta permisos vencidos ni reintenta denegaciones/mutaciones ante CANCELLED.

Tiempos HA de la suite final: 2,735 s desde particionar CN0 hasta comprobar su
lectura coherente después de sanar los proxies; 5,109 s para dos consultas/mandatos
rechazados consecutivos sin mayoría (Stat/Mkdir, deadline de 4 s cada uno).
Son eventos del escenario completo, no una medida aislada de elección de líder.
Migración/restauración: 55 registros, un snapshot anterior retenido y seis objetos
de bloque en el respaldo; SHA-256 restaurado
`ef383a6fa2d1eb530d473bfdbb0d67884a2b5fe9bbd7241e1256496b665b3697`.
El snapshot etcd restaurado acredita nueva membresía y revisión incrementada;
el relevo de mantenimiento comprobó generaciones 1→2.
