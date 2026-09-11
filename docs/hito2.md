# Hito 2: ControlNode y DataNodes separados

El perfil histórico de este documento se conserva. Para RF3 usar la extensión
[etapa5-rf3.md](etapa5-rf3.md) y `init --rf3` en una raíz nueva; no reutilizar
destructivamente estos volúmenes. E5 no introduce replicación automática ni HA.

Implementación E4 sobre Windows nativo, con R=1/W=1. La verificación y las mediciones de cierre se registran en [evidencias E4](evidencias/etapa4/README.md). Este laboratorio no acredita acceso por Internet ni resistencia a pérdida del host. RF3 completo corresponde a E5; replicación automática a E6; HA de control/etcd a E7.

## Arranque reproducible

Desde PowerShell en `F:\DFSha`, usar el Python ya existente del proyecto. No es necesario reinstalar dependencias, Docker ni etcd. Cada `init` exige una raíz nueva: no migra ni modifica los datos de H1.

```powershell
$py = '.\.venv-win\Scripts\python.exe'
& $py scripts/lab_hito2.py init --root .runtime/demo-h2 --block-size 67108864
& $py scripts/lab_hito2.py start --root .runtime/demo-h2
& $py scripts/lab_hito2.py status --root .runtime/demo-h2
```

`init` crea claves/certificados de siete días, configuraciones privadas separadas, inventarios SQLite y la lista de cuatro identidades preautorizadas. `start` arranca un control y los primeros tres DataNodes. Los puertos libres se eligen durante init, se guardan en configuración y se conservan tras reinicio. La disponibilidad exige inventario reconciliado y la generación correcta, no un sleep fijo. Cada proceso usa un volumen propio; no monta el volumen de otro.

Cuenta exclusiva del laboratorio: `admin`, contraseña `development-password`. No usarla fuera de esta demostración local. El cliente lee únicamente `client.toml`, con entrada del control y CA pública; no contiene ubicaciones de bloques ni claves privadas.

```powershell
$config = '.runtime/demo-h2/client.toml'
$session = '.runtime/demo-h2/demo-session.json'
& $py -m dfsha.client.cli --config $config --session-file $session login admin
& $py -m dfsha.client.cli --config $config --session-file $session mkdir /demo
& $py -m dfsha.client.cli --config $config --session-file $session put README.md /demo/readme
& $py -m dfsha.client.cli --config $config --session-file $session ls /demo
& $py -m dfsha.client.cli --config $config --session-file $session get /demo/readme .runtime/demo-h2/readme-out.md
& $py -m dfsha.client.cli --config $config --session-file $session nodes
& $py -m dfsha.client.cli --config $config --session-file $session shell
```

En la shell: `cd /demo`, `pwd`, `stat readme`, `ls`, `exit`. `send/receive` son alias de `put/get`; overwrite requiere `--overwrite`. Gestión mínima de usuarios: `useradd nombre` pide contraseña, crea grupo privado y `/home/nombre`; permisos/ACL y rutas conservan semántica de H1. Contraseñas no se pasan como argumentos ni se registran en logs. Cada session-file mantiene cwd e identidad propios.

```powershell
& $py scripts/lab_hito2.py add-fourth --root .runtime/demo-h2
& $py scripts/lab_hito2.py status --root .runtime/demo-h2
# Los nuevos uploads pueden usar el cuarto nodo sin cambiar client.toml.
& $py scripts/lab_hito2.py stop --root .runtime/demo-h2
# Los datos se conservan; start reinicia control y primeros tres nodos.
```

`stop` escribe señales únicamente en la raíz de laboratorio seleccionada y espera cierre; no mata procesos ajenos por PID. Un proceso terminado abruptamente puede dejar ready.json: revisar su log y arrancar el mismo perfil para reconciliar, sin borrar datos ni claves.

## Copia S/S administrativa

`nodes` devuelve node_id y métricas. Con sesión admin, elegir un destino que no tenga ya el bloque:

```powershell
& $py -m dfsha.client.cli --config $config --session-file $session copy-block /demo/readme 0 UUID-DEL-DESTINO
& $py -m dfsha.client.cli --config $config --session-file $session copy-status UUID-DE-TAREA
```

Los UUID de esas dos líneas se toman de las respuestas reales, no son valores predefinidos. ACCEPTED significa tarea persistida; esperar FINISHED con recibo. El contenido va origen→destino por mTLS, nunca por el control o filesystem compartido. La [prueba automática](../tests/test_hito2.py) detiene el origen, resuelve y lee desde la copia; además reinicia el destino y recupera su recibo por VerifyReceipt. Es una primitiva aislada, no una política de reparación o HA del archivo.

## Verificaciones

```powershell
& $py scripts/verify_stage4.py --measure
& $py scripts/check_package_stage3.py --python .venv-verify-20260908T212227145653Z/Scripts/python.exe --evidence docs/evidencias/etapa4/package.json
& .\.venv-verify-20260908T212227145653Z\Scripts\python.exe -I scripts/check_installed_hito2.py
```

El primer comando ejecuta pip check, generación/importación, regresión E2/H1/E4 por conexiones reales, auditoría y medición de 512 MiB + dos archivos de 128 MiB+1 con tres clientes en procesos separados. Crea evidencias fechadas con comandos, hashes, configuración y picos de memoria del SO; los datos grandes quedan en `.runtime/`, excluidos de Git. Para una medición aislada: `& $py scripts/measure_hito2.py`; acepta `--bytes 1073741824` y `--block-size 4194304|67108864|134217728` como opciones separadas, no como texto literal con barras.

El segundo comando utiliza el venv limpio existente, reinstala solamente el wheel DFSha sin dependencias y prueba importación y entrypoints con `-I`. Si ese venv no existe en otra máquina, preparar uno con las dependencias fijadas siguiendo [entorno](entorno.md), y pasar su ruta real. No se presenta como ejecutado automáticamente por crear el script.

Para repetir únicamente H1: `& $py scripts/verify_stage3.py --measure`. El monolito y sus raíces originales siguen disponibles; ese verificador excluye test_hito2 y conserva sus demás verificaciones. Los números históricos de E3 no se extrapolan al perfil distribuido.

## Colocación, recursos y persistencia

El control excluye nodos no READY, métricas vencidas y espacio insuficiente para `longitud + 4096 + 20×ceil(longitud/262144)`. Usa máximo entre ocupado reportado y ubicaciones confirmadas, más reservas aún no confirmadas, para evitar doble conteo. Compara ocupación relativa en bandas de cinco puntos porcentuales, luego streams activos; aplica round robin persistido entre equivalentes. Cada bloque reserva destino dentro de la transacción de AllocateBlocks. Cuotas de laboratorio pueden diferir por nodo aunque el disco físico del host sea compartido.

Cada SDK transfiere un bloque a la vez; varios SDK progresan concurrentemente. DataNodes usan 4 unidades globales de admisión con pesos 1/2/4 para perfiles de 4/64/128 MiB, máximo 24 RPC y buffers de fragmentos acotados. Las tareas de copia tienen dos workers como máximo y comparten la misma admisión. CN conserva metadatos proporcionales a archivos/bloques, no a su contenido. Los tres perfiles se interpretan por `snapshot.block_size_bytes`; cambiar el perfil de creación no cambia archivos previos ni overwrite. 128 MiB es funcional experimental, no optimizado.

El contenedor cifrado H1 conserva versión y formato; se añadió campo opcional block_index al header autenticado para recuperar un objeto persistido antes del commit de inventario. Los contenedores H1 anteriores siguen legibles. Recibos, inventario, generaciones y tareas persisten en cada DN; namespace, operaciones, snapshots, ledger, ubicaciones y decisiones de GC solo en el control. Mapa de ubicaciones separado de manifiesto. Las raíces de H1 no se convierten.

Interrumpir una subida produce aborto o expiración, nunca publicación parcial. Reiniciar control aborta uploads PREPARING, conserva commits y pins válidos; reiniciar DN invalida autorizaciones de su encarnación anterior y reconcilia objetos. GC procede de tareas persistidas del control, con exclusión por pins y referencias; no de falta de comunicación. Corrupción produce DATA_LOSS, copia única inaccesible produce UNAVAILABLE. Recuperación automática de réplicas está fuera de E4.

La KEK de contenido se provisiona a los DN autorizados fuera de sus bloques y Git; CN tiene otra clave para metadatos/ledger. Clave faltante o fingerprint distinto impide arranque, sin regeneración silenciosa. AES-GCM cifra staging y bloques, no SQLite, WAL ni inventarios. ACL de archivos locales y TLS/mTLS sí se aplican; volumen, backups, rotación y separación entre cuentas/VMs siguen pendientes E8/E9.

## Correspondencia y límites

ControlNode cumple responsabilidades de namespace/manifiestos/ubicaciones asociadas al NameNode de HDFS; DataNode cumple la capa de almacenamiento. Los contratos, algoritmos y SQLite de DFSha son propios. Un nodo puede terminar teniendo todos los bloques de un archivo, especialmente con tres nodos y R=3 futuro; RNF4 se demostrará también por bloques y tráfico útil repartidos, no por prohibir esa situación.

Q01–Q07, incluida Q02 para archivos pequeños/vacíos y Q05 sobre comunicaciones, siguen pendientes. Un CN y una SQLite son puntos únicos de fallo en este hito. Tres procesos en el mismo Windows no aportan dominios físicos independientes. R=3/W=2, tres ControlNodes y tres etcd siguen como objetivo final; W de datos nunca equivale a quórum de metadatos. El siguiente trabajo es E5 (RF3 parcial por offset y concurrencia), sin ejecutarlo en E4.
