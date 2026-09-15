# Diagnóstico de PutBlock en Windows

Evidencia original preservada: `measurement-isolated.json`, comando:

```powershell
.\.venv-win\Scripts\python.exe scripts/measure_stage7.py --evidence docs/evidencias/etapa7/measurement-isolated.json
```

Configuración: 536870912 bytes, bloques de 67108864 bytes, fragmentos de 262144,
tres ControlNodes, tres miembros etcd y tres DataNodes; R3/W2, TLS/mTLS. La raíz
original es `.runtime/measure-e7/753bb8fa-193f-4ee5-a269-2397cf1994bc`.
El log de `datanode-2` registra `PutBlock:PERMISSION_DENIED`. Sus directorios
inspeccionados son directorios ordinarios, sin enlaces. El log original no guardó
el identificador del bloque rechazado ni la línea: esos datos no se inventan
retrospectivamente.

La inspección de los inventarios originales en modo SQLite `mode=ro` encontró
la operación `6b152a2f-1f82-409c-88ff-c6bfad6aa138`: sus primeros bloques fueron
confirmados por DN3 y DN1. DN2 solo conserva una **réplica S/S** del bloque
`57104afe-913f-404f-8393-b0b20d966457`, recibo asociado a la tarea
`0727970a-77a9-48d5-8732-6309d645c2bc`, sin entrada `put_ledger` de cliente.
Su confirmación durable es `1789324640654` ms UTC. Esto concuerda con la
creación del primer directorio de ese archivo por replicación mientras el cliente
intentaba el siguiente primario en DN2. La operación y réplica son comprobables;
el orden exacto entre syscalls del fallo original no quedó registrado.

## Causa reproducida y corrección

`EncryptedBlockStore.path` resuelve la ruta antes de verificar que pertenece a
la raíz. En Windows/Python 3.12.10, `ntpath.realpath(strict=False)` puede conservar
el prefijo extendido `\\?\` cuando el directorio padre aparece durante esa
resolución. La primera consulta devuelve ERROR_PATH_NOT_FOUND (3); al aparecer
el padre, otra consulta del archivo aún inexistente devuelve ERROR_FILE_NOT_FOUND
(2). El código de Python solo elimina ese prefijo si los errores coinciden.
`Path.is_relative_to` considera distintos los anclajes con y sin prefijo, aunque
designen la misma raíz. Esa comparación producía un falso rechazo de contención.

La prueba `test_new_file_directory_created_during_resolution` sincroniza un hilo
que crea el directorio con la primera consulta real del sistema operativo. No
fabrica resultados de Windows: conserva las llamadas originales y sus errores.
Antes de corregir: `path-race-before.xml`, una falla en la comprobación de
contención y una negativa aprobada. Después: `path-race-fixed.xml`, dos aprobadas.
Este caso reducido reproduce una causa del rechazo local observado; el original
carece de la traza necesaria para reconstruir su intercalado exacto.

`containment_path` iguala únicamente las representaciones DOS/UNC equivalentes
para comparar la ruta **ya resuelta** con la raíz. No cambia destinos físicos,
no ignora enlaces, no amplía permisos ni plazos y no reintenta un rechazo legítimo.
Una junction cuyo destino sale del almacén sigue devolviendo PERMISSION_DENIED.
También se aplica la comparación coherente a la lectura/verificación del objeto.

## Trazabilidad y clasificación

Se agregaron trazas sin cuerpos, claves ni tokens: operación, versión de bloque,
nodo/generación, control emisor, endpoint que validó, plazo y momento de validación.
Los rechazos internos incluyen archivo/línea. La medición posterior recoge estos
eventos; los campos ausentes en ejecuciones anteriores permanecen desconocidos.
PutBlock no abre un handle de archivo: usa operación de upload, sesión y permiso
por destino. Los handles se utilizan posteriormente para lectura y parche.

Según los [códigos oficiales gRPC](https://grpc.io/docs/guides/status-codes/),
PERMISSION_DENIED corresponde a falta de autorización de una identidad conocida;
credenciales inválidas usan UNAUTHENTICATED, dependencia no disponible UNAVAILABLE,
y vencimiento de una llamada DEADLINE_EXCEEDED. El arreglo no cambia ese mapa:
el error era una comparación física falsamente negativa. No hay evidencia de
que este rechazo concreto proviniera de un timeout etcd transformado en permiso.

Las primeras trazas de `measurement-traced.json` muestran autorizaciones mediante
distintos controles y varios minutos de plazo restante. No demuestran por sí
solas la corrección: esa ejecución comenzó antes del cambio de contención.

```powershell
.\.venv-win\Scripts\python.exe -m pytest -q tests/test_block_path_race.py --junitxml=docs/evidencias/etapa7/path-race-repeat.xml
```

La aceptación completa exige la medición posterior de 512 MiB y la regresión E7;
no se sustituye por el caso reducido. Laboratorio de procesos en un solo host.
