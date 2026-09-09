# Hito 1 — RF1/RF2 C/S, etapa 3

Monolito modular con CLI/SDK por TLS, SQLite autoritativa y bloques locales AES-GCM.
El cliente no recibe una ruta del disco del servidor ni comparte su volumen de
datos. No requiere etcd. [Contrato operativo](protocolos-hito1.md),
[diseño D25–D30](etapa3-diseno.md), [evidencias](evidencias/etapa3/README.md).

## Arranque en Windows PowerShell

Desde `F:\DFSha`, reutilizar `.venv-win` de etapa 2. Solo para un checkout nuevo:
`powershell -NoProfile -File scripts/bootstrap.ps1`. No actualizar dependencias.

```powershell
Set-Location -LiteralPath F:\DFSha
.\.venv-win\Scripts\python.exe scripts/generate_proto.py --check
# Generar solo si .runtime/certs no existe o está vacío. No sobrescribir una CA vigente.
.\.venv-win\Scripts\python.exe scripts/generate_certs.py
# Solo primera inicialización: solicita contraseña, crea clave y administrador.
.\.venv-win\Scripts\python.exe -m dfsha.admin init --config deploy/monolith.example.toml --username admin
.\.venv-win\Scripts\python.exe scripts/dev.py start --profile hito1
.\.venv-win\Scripts\python.exe -m dfsha.client.cli login admin
.\.venv-win\Scripts\python.exe -m dfsha.client.cli shell
```

Certificados de desarrollo duran siete días. Si vencen, detener el servicio y generar
una CA en **otra carpeta vacía**, configurar servidor/clientes para confiar en ella.
Esto no modifica la clave de almacenamiento. Clave faltante o distinta en un
almacenamiento existente impide arrancar: restaurar la original, no reinicializar.

Puertos públicos/internos 17443/17445, solo loopback; no arrancar simultáneamente
el diagnóstico E2 en esos mismos puertos. `deploy/monolith.example.toml` es público,
sin secretos. Datos solo `.runtime/hito1`, sesión CLI `.runtime/client`, archivos
del usuario en sus propios destinos. El servidor rechaza una segunda apertura de
la misma raíz por otro monolito. Cada instancia CLI con `--session-file` distinto
conserva su propia sesión/cwd; la shell conserva cwd entre comandos.

Parada ordenada:

```powershell
.\.venv-win\Scripts\python.exe -m dfsha.client.cli logout
.\.venv-win\Scripts\python.exe scripts/dev.py stop --profile hito1
```

El script solicita parada mediante archivo propio; confirmar evento `stopped` en
el log señalado al arrancar. Alternativa visible para depuración: ejecutar
`python -m dfsha.control.server --config deploy/monolith.example.toml` en una
terminal y Ctrl+C para detener. No aprovisiona cloud ni instala Docker/WSL.

## Usuarios, demo y SDK

Administrador inicial es la identidad elegida al inicializar; usuario ordinario
tiene home privado, grupo propio y denegación por defecto fuera de permisos.
Contraseña 12..1024 bytes; se pide con getpass, o `--password-stdin` para automatizar
sin ponerla en argumentos. `useradd` crea por RPC, no editando SQLite. `chmod` usa
GetAcl/SetAcl con revisión. SDK también expone stubs de gestión de grupos/usuarios.

Dentro de la shell (crear antes un archivo local `ejemplo.bin` con el contenido deseado):

```text
useradd alice
mkdir /demo
cd /demo
pwd
put ejemplo.bin archivo.bin
ls
stat archivo.bin
get archivo.bin copia.bin
put ejemplo.bin archivo.bin --overwrite
rm archivo.bin
cd /
rmdir /demo
exit
```

Comandos equivalentes reproducibles fuera de shell:

```powershell
.\.venv-win\Scripts\python.exe -m dfsha.client.cli mkdir /demo
.\.venv-win\Scripts\python.exe -m dfsha.client.cli send ./ejemplo.bin /demo/archivo.bin
.\.venv-win\Scripts\python.exe -m dfsha.client.cli receive /demo/archivo.bin ./copia.bin
Get-FileHash -Algorithm SHA256 -LiteralPath ./ejemplo.bin, ./copia.bin
```

send/put y receive/get son alias. Destino existente se rechaza salvo `--overwrite`;
descarga conserva el destino local previo ante fallo. Shell acepta comillas y
rutas locales con `/` para evitar ambigüedad de backslash en shlex. Los comandos
JSON no imprimen tokens; el archivo de sesión **sí es secreto** y tiene ACL privada.

```python
from pathlib import Path
from dfsha.client.sdk import Client
client = Client('localhost:17443', Path('.runtime/certs'))
# Contraseña obtenida por getpass o gestor de secretos del llamador.
client.login('alice', password)
client.cd('/home/alice')
client.send('ejemplo.bin', 'archivo.bin')
client.receive('archivo.bin', 'copia.bin')
client.logout()
client.shutdown()
```

## Perfiles y recursos

| Perfil por archivo | block_size_bytes | Streams simultáneos admitidos por proceso | Deadline bloque |
| --- | --- | --- | --- |
| Desarrollo predeterminado | 4194304 | 4 | 30 s |
| Grande | 67108864 | 2 | 120 s |
| Experimental | 134217728 | 1 | 240 s |

Cambiar `block_size_bytes` en configuración y reiniciar afecta a **archivos nuevos**.
Existentes conservan tamaño al leer y sobrescribir. Migración de particionamiento
queda fuera de E3. Transporte 262144 bytes, futuro write 16777216 bytes. No bloques
vacíos; último bloque tiene longitud real. Los locks futuros redondearán según
tamaño del archivo; bloques grandes encarecen parches y reducen granularidad.

Admisión: 4 unidades, coste 1/2/4; presupuesto conservador de diseño 384 MiB incluyendo
128 MiB base. No es límite duro del SO. Dos Argon2 simultáneos y buffers cifrados
por fragmento; cliente serializa sus bloques. Metadata O(número de bloques), máximo
de archivo por defecto 16 GiB. La medición de 1 GiB con otros dos clientes registró
**cliente máximo 54.112.256 bytes (51,6 MiB), servidor 85.471.232 (81,5 MiB)**.
Son picos residentes Windows de esa ejecución, no garantías universales ni datos
de throughput comparativo. Ver [JSON final](evidencias/etapa3/20260909T195446Z/medicion.json).

## Verificación y alcance

```powershell
.\.venv-win\Scripts\python.exe scripts/verify_stage3.py
.\.venv-win\Scripts\python.exe scripts/measure_hito1.py
# Una sola invocación con ambas comprobaciones:
.\.venv-win\Scripts\python.exe scripts/verify_stage3.py --measure
```

Tests generan CA, config, usuarios y procesos propios; no usan los datos del demo.
Escriben runtime ignorado y evidencias JSON/XML sin contraseñas/llaves/bloques. La
medición requiere 5 GiB libres, genera 1 GiB y dos archivos de 64 MiB+1, tres
procesos cliente, un servidor y checksums reales. Conserva archivos bajo runtime
para inspección, no se añaden a Git. Picos según
[PROCESS_MEMORY_COUNTERS de Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters):
se mide el PID reportado por el servidor, no el lanzador de venv de Windows.

Resultado final: **87 pruebas aprobadas, sin fallos/errores/omitidos/advertencias**
en 142,86 s, más medición concurrente aprobada; [evidencia](evidencias/etapa3/20260909T195446Z/resultado.json).
Casos funcionales: RF1/rutas/Unicode/paginación/cwd/permisos; vacío, texto/binarios,
B−1/B/B+1 en tres perfiles; snapshots y overwrite/borrado; dos lectores paralelos;
interrupción/capacidad/corrupción; reinicio, claves ausentes/incorrectas; caída tras
persistir bloques y antes de publicar; commit con respuesta perdida; revocación,
renovación y CLI/shell como proceso. Regresión E2 conserva TLS/mTLS negativo y etcd
real. No se cuentan omitidos como aprobados; ver resultado vigente en estado.md.

Linux está preparado, **no ejecutado**: activar `.venv-linux`, usar los mismos
módulos/scripts y rutas Linux en configuración. No compartir venv con Windows.
H1 no requiere WSL/etcd; el probe aislado sí requiere binario correspondiente.

Límites: un host y R1/W1, sin alta disponibilidad; SQLite/WAL contienen metadatos
legibles, no se ha acreditado volumen cifrado, backups ni recuperación externa de
claves. Los bloques/staging sí están cifrados y autenticados. Snapshot R/pins son
primitivas RF2, **no RF3 completo**. 128 MiB es funcional, no optimizado. Prueba
loopback no demuestra Internet ni distribución. Q01–Q07 siguen pendientes.

Etapa 4: separar procesos ControlNode/DataNode, registro/heartbeats reales, métricas
frescas, reservas y selección entre nodos, mapa autoritativo, bytes cliente–DN.
Pruebas con archivos 512 MiB/1 GiB y tráfico útil en varios nodos. RF3 E5, réplica
E6, control/quórum E7. Hitos: semana 8 RF1/RF2; semana 10 distribución; semana 12
HA/consistencia/seguridad; final semana 13 informe, GitHub y video 10–15 minutos.
