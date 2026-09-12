# DFSha — Entorno reproducible de etapas 2–6

**E6, Windows nativo:** Python 3.12.10, SQLite 3.49.1, grpcio/grpcio-tools
1.83.1, protobuf 7.36.1, cryptography 50.0.1, argon2-cffi 25.1.0, pytest 9.1.1.
Se conserva requirements.lock y el entorno `.venv-win`; no se instaló otro stack.
`scripts/verify_stage6.py --measure` comprueba dependencias, stubs, regresiones y
medición real. `--replication-only` limita las pruebas a E6.

Arranque reproducible: `scripts/lab_hito2.py init --replication --root
.runtime/demo-e6 --block-size 67108864`, seguido de start/status/add-fourth/stop
con la misma raíz. [Comandos completos](etapa6-replicacion.md#reproducción-en-powershell).
Cada proceso tiene raíz persistente, inventario y claves separados del contenido;
la configuración administrativa liga dominios simulados e identidades mTLS.
La memoria se toma del PID anunciado por el servidor, no del lanzador venv.
[Mediciones y correcciones](evidencias/etapa6/README.md).

Linux sigue BLOQUEADO POR ENTORNO: WSL no instalado. Cuando esté disponible,
desde el mismo checkout y un venv Linux separado: `python scripts/verify_stage6.py
--measure`. Ese comando no se acredita ejecutado en Linux. No hay etcd obligatorio,
provisión cloud, cifrado de volumen ni ensayo de pérdida eléctrica en E6.

**E5:** el mismo Python 3.12.10 de `.venv-win` y lock de dependencias. Sin
reinstalación del stack, etcd ni migración de datos. Contratos con la misma
toolchain; 34 módulos generados importan. Configuración nueva:
`scripts/lab_hito2.py init --rf3 --root .runtime/demo-e5`; perfiles seleccionables
con `--block-size 4194304`, `67108864` o `134217728`. Todos los comandos se ejecutan
con `.\.venv-win\Scripts\python.exe` desde `F:\DFSha`.
Ver [arranque, CLI y verificación](etapa5-rf3.md). `verify_stage5.py --measure`
incluye regresión y medición del delta; `--rf3-only` es una comprobación enfocada,
no acredita H1/H2 por sí sola. Los resultados finales se registran en estado.

Revisión de esta sesión: Git y wsl.exe están en PATH; Python y Docker no. No se
encontró Docker en su ruta habitual de Program Files. Windows sigue siendo la
ruta ejecutable canónica; no se crea una copia del repositorio para Linux.
`wsl --status` fue EJECUTADO y terminó con código 1: subsistema Linux no instalado.
La ejecución Linux está BLOQUEADA POR ENTORNO; no se instaló WSL ni se requirió
reinicio del sistema. Puede repetirse en Linux con el entorno aislado documentado
y `python scripts/verify_stage5.py --measure` cuando esté disponible.

**E4 usa el mismo entorno Windows y dependencias fijadas.** No se requieren
servicios etcd ni cambios de toolchain. Configuración y comandos completos en
[hito2.md](hito2.md); verificación `.\.venv-win\Scripts\python.exe scripts/verify_stage4.py --measure`
desde el proyecto.
Un proceso control y tres/cuatro procesos DataNode, con claves/volúmenes
independientes y CA pública del cliente separada. TLS público y mTLS privado
loopback: no demuestra Internet ni aislamiento por VM. Linux/Docker no
verificados en E4. H1 conserva su raíz y arranque; no hay migración destructiva.

Recomprobación 2026-09-10: `.venv-win` ejecuta Python 3.12.10. En el PATH de
esta sesión no aparecen `python` ni `docker`; Git está en `C:\Program Files\Git\cmd`.
No existe Docker en `C:\Program Files\Docker\Docker\resources\bin\docker.exe`.
`wsl.exe --status` devuelve código 1 e informa que el subsistema no está instalado:
tener ese launcher de Windows no significa tener Linux disponible. Se mantiene
la ejecución con ruta explícita del venv y la validación Linux BLOQUEADA POR
ENTORNO; no se instalaron componentes del sistema ni se exigió reinicio.

Para el monolito funcional y comandos actuales: [hito1.md](hito1.md). Stack fijado
sin cambios; la sección final registra la actualización E3. Lo siguiente conserva
la comprobación de herramientas/dependencias E2, con Linux aún pendiente.

2026-09-08. Ruta ejecutada: **Python 3.12 nativo de Windows, `.venv-win`, gRPC y binario oficial etcd aislado**. Carpeta canónica `F:\DFSha`. Se aprovecha Python existente; no se instalaron Python del sistema, WSL ni Docker. Los scripts Python/TOML/Protobuf y bootstrap Bash preparan Linux; **Linux no fue ejecutado**. La prueba local no acredita Internet, VMs ni HA.

## 1. Inventario comprobado

[Comandos y salidas de entorno/Git](evidencias/etapa2/entorno-git.json). E1 y las primeras comprobaciones restringidas no describen necesariamente el entorno actual: el launcher llegó a informar que no había Python; la inspección final autorizada sí ve instalación y registro. No se infiere una instalación del sistema realizada por este trabajo.

| Herramienta | Estado real verificado |
| --- | --- |
| Git | 2.51.2.windows.1, `C:\Program Files\Git\cmd\git.exe`. |
| Python elegido | **3.12.10**, `C:\Users\Tommysepf\AppData\Local\Programs\Python\Python312\python.exe`. Inicialmente localizado fuera del PATH visible en la ejecución restringida; inspección final lo encuentra como `python` y en `py -0p`. `python3` es un alias WindowsApps; no se usa como prueba de intérprete. |
| Otra instalación | El launcher final registra también 3.11; no se utiliza ni se instala una ruta alternativa. |
| Entorno aislado | `.venv-win\Scripts\python.exe`. La comprobación limpia crea `.venv-verify-<run_id>`, instala un wheel sin editable/PYTHONPATH y vuelve a generar/importar. Todos ignorados por Git. |
| SQLite | 3.49.1 del módulo sqlite3; reapertura y rollback real probados. MetadataStore todavía no implementado. |
| Docker / Compose | Ausentes de PATH, rutas habituales ProgramFiles/LocalAppData y servicios inspeccionados. No hay cliente verificado: **no** se clasifica como «cliente disponible, motor detenido». Compose no se puede ejecutar. No se descartan ubicaciones arbitrarias no conocidas. |
| WSL | `wsl.exe` existe, pero `--status` y `--list --verbose` indican subsistema no instalado. Sin distribución utilizable comprobada; Python no se ejecuta dentro de WSL/contenedores. |
| etcd | 3.6.14, Git SHA `fc04cf7`, Go 1.25.12, windows/amd64; `.tools/etcd-3.6.14/windows-amd64/etcd.exe`. |
| Permisos del agente | Sandbox restringe red y rutas del perfil. Descargas, Git y Python requirieron ejecución autorizada; no se cambiaron políticas del sistema para evitarlo. |
| Cloud | Cuenta/cuotas/dominios/responsables pendientes (Q07). No se aprovisionaron recursos. |

etcd clasifica Linux AMD64/ARM64 en tier 1 y Windows AMD64 en tier 3 con pruebas limitadas. Windows se usa aquí **solo para compatibilidad de API**; el destino distribuido sigue siendo Linux. No se acredita durabilidad ante fallo de host ni soporte productivo Windows. [Plataformas oficiales](https://etcd.io/docs/v3.6/op-guide/supported-platform/).

## 2. Versiones exactas y compatibilidad

| Componente | Versión instalada/fijada | Evidencia |
| --- | --- | --- |
| Python | 3.12.10; proyecto exige 3.12.* | Intérprete existente y patch registrado. |
| grpcio / grpcio-tools | **1.83.1 / 1.83.1** | Generación/importación, TLS/mTLS y streaming. |
| protobuf | **7.36.1** | Intervalo exigido por grpcio-tools: `>=7.35.1,<8.0.0`; validaciones de runtime conservadas. |
| cryptography | **50.0.1** | x509, AES-GCM y rechazo de ciphertext/AAD alterados. |
| argon2-cffi / bindings | **25.1.0 / 26.1.0** | Hash Argon2id y verificación positiva/negativa. |
| pytest | **9.1.1** | Procesos/puertos reales, resultados XML. |
| pip-tools | **7.6.1** | Resolución conjunta con hashes. |
| setuptools / wheel | **84.0.0 / 0.48.0** | Build/instalación limpia; licencias de terceros incluidas por license-files. |
| etcd | **3.6.14** | API v3 directa por mTLS/RBAC: KV/Txn/Lease/Lock/Watch. |

Todas las transitivas, incluido pip de herramientas, están en [requirements.lock](../requirements.lock) con hashes. Cada resultado.json registra versiones instaladas y pip check. Este último comprueba restricciones de versiones, no ausencia de vulnerabilidades. El lock se resolvió en Windows CPython 3.12; incluye paquetes portables como colorama también en Linux, cuya instalación sigue **PENDIENTE** de ejecución. No se afirma validación cruzada por disponer de un script.

Fuentes de mantenedores consultadas y comprobadas mediante ejecución conjunta: [grpcio-tools 1.83.1](https://pypi.org/project/grpcio-tools/1.83.1/), [protobuf 7.36.1](https://pypi.org/project/protobuf/7.36.1/), [cryptography 50.0.1](https://pypi.org/project/cryptography/50.0.1/), [argon2-cffi 25.1.0](https://pypi.org/project/argon2-cffi/25.1.0/) y [compatibilidad Protobuf](https://protobuf.dev/support/cross-version-runtime-guarantee/).

Procedencia/licencias etcd en [third_party/README.md](../third_party/README.md) y [sources.lock.json](../third_party/sources.lock.json). Binarios del [release oficial](https://github.com/etcd-io/etcd/releases/tag/v3.6.14), URLs/hashes en [etcd-artifacts.json](../deploy/etcd-artifacts.json). ZIP Windows SHA-256 `117a5c7cc0315984388ccffe1f3bd0e95fc2d5663440dea61c27d3fdc0e879b2`; tar Linux preparado `ffe840ff9295808e88cce2794a18a5ac87f12a5203c8314d0bf6aa119b41bac5`. No se modifica código generado para ocultar incompatibilidad.

## 3. PowerShell: preparación y verificación

No es necesario activar el entorno ni cambiar PATH. Bootstrap usa el Python 3.12 existente; `-PythonExe` permite especificar otra ubicación real.

```powershell
Set-Location -LiteralPath F:\DFSha
powershell -NoProfile -File scripts/bootstrap.ps1 -PythonExe "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
.\.venv-win\Scripts\python.exe scripts/verify_stage2.py --clean-env
.\.venv-win\Scripts\python.exe scripts/audit_stage2.py --evidence docs/evidencias/etapa2/auditoria-local.json
```

Bootstrap comprueba Python 3.12, crea `.venv-win` si falta, instala el lock **con hashes**, instala DFSha sin resolver dependencias implícitas, genera/importa stubs, descarga solo el binario etcd del host y ejecuta pip check. No instala herramientas del sistema. Si falta el binario, verify falla con evidencia; no lo sustituye por un mock.

Verify produce un directorio UTC nuevo con argv/cwd, códigos/salidas, tiempos, versiones, XML y hashes del código probado. `--clean-env` añade reinstalación lock, build/instalación wheel y generación/importación sin editable. Sin el flag esa verificación limpia figura pendiente **en esa ejecución**, sin convertir una prueba no realizada en aprobada.

Mantenimiento deliberado separado del arranque:

```powershell
.\.venv-win\Scripts\python.exe scripts/lock_dependencies.py
.\.venv-win\Scripts\python.exe scripts/vendor_etcd.py
.\.venv-win\Scripts\python.exe scripts/generate_proto.py
.\.venv-win\Scripts\python.exe scripts/generate_proto.py --check
.\.venv-win\Scripts\python.exe scripts/audit_stage2.py --write-catalog
```

Vendor verifica originales offline; `--restore` recupera solo fuentes ausentes de sus URLs fijadas. `--refresh` cambia inventario/versiones: no usarlo al arrancar; requiere revisar diff/licencias y repetir compatibilidad. La generación usa salida nueva bajo build para evitar stubs residuales. `--check` compara bytes de src e importa todos los módulos. El catálogo derivado de descriptores complementa la semántica de protocolos.md.

Si una política institucional impide ejecutar `.ps1`, usar los comandos Python internos o solicitar habilitación puntual al administrador; no se modifica una política global. Si falta Python 3.12 en otra máquina, preparar **una** ruta soportada y repetir bootstrap; aquí no hizo falta instalarlo.

### Diagnóstico manual con procesos separados

Primera generación en directorio vacío; certificados válidos siete días. El generador rechaza sobreescribir una CA: para rotar, detener servidor, generar en otra carpeta y ajustar certificate_dir/`--cert-dir`. Las pruebas automatizadas generan una CA independiente por ejecución.

```powershell
.\.venv-win\Scripts\python.exe scripts/generate_certs.py --output .runtime/certs
.\.venv-win\Scripts\python.exe scripts/dev.py start
.\.venv-win\Scripts\python.exe -m dfsha.client.diagnostic --target localhost:17443
.\.venv-win\Scripts\python.exe -m dfsha.client.diagnostic --target localhost:17445 --identity client
.\.venv-win\Scripts\python.exe scripts/dev.py stop
```

Start lanza proceso oculto Windows y registra listeners/PID/rutas en `.runtime/dev/active.json`. Stop crea un archivo de control con ruta validada, sin matar un PID reutilizado; comprobar evento `stopped` en el log indicado. Gracia de cierre DFSha: 3 s. Fixtures pytest poseen y esperan sus procesos incluso ante fallo. Alternativa en primer plano: `python -m dfsha.control.server --config deploy/local.example.toml`, cliente en otra terminal y Ctrl+C.

El TOML separa public_bind 17443 TLS e internal_bind 17445 mTLS. Loopback obligatorio; cuatro workers y ocho RPC concurrentes por listener; mensajes≤1 MiB, stream sintético≤64 MiB, chunks≤256 KiB. Cliente: deadlines 5/15 s, configurables con `--deadline`/`--stream-deadline` hasta 30 s. Health informa `filesystem_implemented=false` y `sqlite-planned`: no abre SQLite ni demuestra RF1/RF2.

### etcd y seguridad de las pruebas

`python -m pytest tests/test_etcd.py -q` inicia/finaliza instancia principal y una auxiliar para indisponibilidad, sin servicio Windows. Puertos loopback efímeros, mTLS de cliente/peer, gateway deshabilitado. CN=root administra; dfsha-probe solo accede al prefijo de prueba; dfsha-denied no tiene permisos. Bootstrap ocurre en una instancia **nueva propia**, nunca un clúster compartido. Usuarios sin contraseña autentican por certificado.

Cada ejecución usa `/dfsha-stage2/<UUID>/`. Solo la consulta negativa `/dfsha-stage2/forbidden` toca otra clave y debe rechazarse, sin escritura. Al salir borra el prefijo propio, verifica cero claves, revoca leases propios y elimina usuarios/rol del probe. Certificados/logs/WAL quedan en `.runtime/` ignorado para inspección, sin procesos activos. Root permanece únicamente en ese WAL aislado. Cleanup local se copia a evidencia pública. Terminate de etcd Windows **no acredita cierre graceful ni resiliencia**; permite verificar error controlado de indisponibilidad. El servidor DFSha sí cierra ordenadamente.

Claves de desarrollo fuera de Git: ACL Windows al usuario actual/SYSTEM/administradores; POSIX 0700 directorio y 0600 claves. Generación x509/RSA con cryptography. gRPC verifica CA y SAN DNS/IP, sin overrides ni canales inseguros. Logs de aplicación admiten solo campos permitidos. Pruebas negativas sobre IP con SAN válido evitan que un intento IPv6 de localhost consuma el deadline antes del rechazo TLS; las positivas también verifican DNS localhost. AES-GCM/Argon2id se prueban aisladamente: **no equivalen a RNF6 completo**, almacenamiento DFS cifrado ni cuentas/ACL implementadas.

## 4. Linux preparado, pendiente de ejecución

Para WSL2, el equipo/administrador debe habilitar subsistema, reiniciar si Windows lo requiere y preparar una distribución con Python 3.12/venv. No se ejecutaron esos pasos. Se prefiere Linux nativo/WSL2 o contenedores Linux para etcd cuando estén disponibles; no se instalan alternativas múltiples ahora.

En WSL el **mismo** proyecto es `/mnt/f/DFSha`; no copiarlo a otro home. Entornos `.venv-win` y `.venv-linux` separados, nunca reutilizar ejecutables. En Linux nativo usar el checkout canónico de esa máquina; el remoto vacío aún no contiene este código hasta sincronizarlo.

```bash
cd /mnt/f/DFSha                         # WSL: corresponde a F:\DFSha
bash scripts/bootstrap.sh
.venv-linux/bin/python scripts/verify_stage2.py --clean-env
.venv-linux/bin/python scripts/audit_stage2.py --evidence docs/evidencias/etapa2/auditoria-linux.json
```

Fetch selecciona tar linux-amd64 fijado; ARM64 no preparado se rechaza. Venv en DrvFs puede ser más lento, pero no se comparte con Windows. WAL/datos etcd se guardan en `$XDG_STATE_HOME/dfsha-stage2/<UUID>` o `~/.local/state/dfsha-stage2/<UUID>` sobre disco Linux nativo. **No configurar XDG_STATE_HOME bajo /mnt/f**. No existen Dockerfile/Compose porque esa no es la ruta elegida. Docker/VMs finales, cifrado de volúmenes, recuperación de claves y mayoría etcd siguen pendientes E7–9.

## 5. GitHub: creado, accesible, vinculado, no sincronizado

Repositorio único: [tsepulvedf/DFSha](https://github.com/tsepulvedf/DFSha). La inspección inicial encontró F:\DFSha sin Git. **Antes de inicializar**, `git ls-remote --symref` consultó refs/historial, salida vacía con código 0. La API GitHub confirmó default_branch=main, tamaño 0, público. No se supuso rama ni se omitió historial existente.

Vinculación ejecutada una vez, no repetir inicialización sobre un checkout existente:

```powershell
git init --initial-branch=main
git remote add origin https://github.com/tsepulvedf/DFSha.git
git config branch.main.remote origin
git config branch.main.merge refs/heads/main
```

Estado: .git y origin correctos; HEAD main **sin primer commit**, sin rama remota materializada porque no existen refs. Archivos del proyecto aún sin seguimiento. `git log` falla de forma esperada por ausencia de commits. No se asignó identidad de autor ni se hizo commit/push. Lectura remota verificada nuevamente; permiso/autenticación de escritura **no comprobado**. Sincronización efectiva **PENDIENTE**; no bloquea preparación técnica E3.

Inspección posterior conservando evidencia anterior:

```powershell
powershell -NoProfile -File scripts/inspect_environment.ps1 -Remote -OutputPath docs/evidencias/etapa2/entorno-git-nueva.json
git status --short
git remote -v
git ls-remote --symref origin
```

Antes de commit/push volver a consultar remoto por si otra sesión añadió historial y usar identidad real del equipo. «Creado»/«vinculado» no significan código publicado. Q01–Q07 siguen pendientes; la URL GitHub ya está definida y no debe volver a figurar como pendiente de creación.
# Etapa 3: ruta comprobada

Windows/Python 3.12.10 y lock E2 conservados; paquete propio 0.3.0, SQLite 3.49.1.
No se instala otra ruta ni Docker/WSL. Monolito no conecta etcd al arrancar.
[Hito 1](hito1.md) contiene PowerShell, perfiles, inicio/parada y pruebas.
Linux pendiente; no compartir venv Windows/Linux ni crear otro checkout.

```powershell
.\.venv-win\Scripts\python.exe scripts/verify_stage3.py
.\.venv-win\Scripts\python.exe scripts/measure_hito1.py
```

Medición: PeakWorkingSetSize del PID real del servidor. Clave/staging/bloques/sesión
en runtime ignorado; ACL privadas del usuario actual/SYSTEM/Administradores.
SQLite/WAL/volumen y backups no tienen cifrado integral acreditado. Clave ausente
o incorrecta impide arranque; restaurar la original, no generar otra.
