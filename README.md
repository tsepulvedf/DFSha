# DFSha

Proyecto 1 de SI3007/ST0263, período 2026-2. Opción 1: cliente/servidor de una organización, con composición S/S mediante red privada.

**Etapa 2: base de diagnóstico ejecutable y contratos v1.** Hay 50 RPC definidas: tres de diagnóstico implementadas y 47 futuras que devuelven UNIMPLEMENTED. RF1/RF2/RF3, distribución, replicación y HA siguen pendientes. Se conserva el diseño de etapa 1.

Repositorio único: [tsepulvedf/DFSha](https://github.com/tsepulvedf/DFSha). Lectura remota verificada; `F:\DFSha` vinculada a origin, rama main sin primer commit. **Los cambios todavía no están sincronizados con GitHub.** La API confirmó main y ausencia de historial antes de inicializar. No se creó otro remoto ni una identidad de autor.

## Verificación reproducible

Ruta comprobada: Windows, Python **3.12.10**, gRPC/grpcio-tools **1.83.1**, Protobuf **7.36.1**, etcd **3.6.14** aislado. Dependencias/hashes en requirements.lock; diagnóstico no requiere Docker/WSL ni etcd externo. [Entorno y versiones completas](docs/entorno.md).

PowerShell desde el proyecto:

```powershell
Set-Location -LiteralPath F:\DFSha
powershell -NoProfile -File scripts/bootstrap.ps1
.\.venv-win\Scripts\python.exe scripts/verify_stage2.py --clean-env
.\.venv-win\Scripts\python.exe scripts/audit_stage2.py
```

Bootstrap utiliza Python 3.12 existente; si hace falta pasar `-PythonExe "ruta\python.exe"`. Tests generan certificados y procesos/puertos propios, verifican TLS/mTLS, streams, bibliotecas de seguridad y etcd real, y detienen sus procesos. Evidencias nuevas en `docs/evidencias/etapa2/<fechaUTC>/`; no se usan mocks para declarar compatibilidad.

Diagnóstico manual, primera generación en carpeta vacía:

```powershell
.\.venv-win\Scripts\python.exe scripts/generate_certs.py
.\.venv-win\Scripts\python.exe scripts/dev.py start
.\.venv-win\Scripts\python.exe -m dfsha.client.diagnostic --target localhost:17443
.\.venv-win\Scripts\python.exe -m dfsha.client.diagnostic --target localhost:17445 --identity client
.\.venv-win\Scripts\python.exe scripts/dev.py stop
```

Los listeners TLS público/mTLS interno solo escuchan en loopback. Health informa `filesystem_implemented=false`; streaming procesa datos sintéticos sin persistirlos. Claves, certificados, WAL, entornos y logs fuera de Git. Para regenerar contratos: `python scripts/generate_proto.py`; añadir `--check` para comparar, usando el Python del entorno.

Linux preparado mediante `bash scripts/bootstrap.sh` y `.venv-linux/bin/python scripts/verify_stage2.py --clean-env`, **pendiente de ejecución**. En WSL la ruta canónica es `/mnt/f/DFSha`; WAL etcd sobre disco Linux nativo. Windows etcd valida API, no acredita despliegue final Linux.

## Organización y continuidad

| Ruta | Responsabilidad |
| --- | --- |
| [src/dfsha](src/dfsha/) | client, control, datanode, common; interfaces MetadataStore/Coordinator/BlockStore/Authorizer. Stubs propios/oficiales en dfsha.v1/dfsha._vendor. |
| [proto/dfsha/v1](proto/dfsha/v1/) | Fuentes de contratos propios. |
| [third_party](third_party/) | Fuentes oficiales originales, revisiones, hashes y licencias. |
| [tests](tests/) / [scripts](scripts/) | Verificaciones, bootstrap, generación, procesos, auditoría. |
| [deploy](deploy/) | Configuración pública/interna sin secretos y artefactos etcd fijados. |
| [Estado](docs/estado.md) | Resultado, límites, hitos y siguiente etapa. |
| [Protocolos](docs/protocolos.md) | RPC, idempotencia, seguridad, errores, deadlines y confirmaciones. |
| [Evidencias E2](docs/evidencias/etapa2/README.md) | Resultados ejecutados y fallos iniciales conservados. |

Diseño: [especificación](docs/especificacion.md), [arquitectura](docs/arquitectura.md), [decisiones](docs/decisiones.md), [matriz](docs/matriz-requisitos.md). H1 usará SQLite/bloques locales; el probe etcd no es dependencia del servidor. Siguiente etapa: **E3, RF1/RF2 completos del monolito**, tras verificar E2. H1 semana 8; H2 semana 10; H3 semana 12; final semana 13. No se avanzó automáticamente a E3.
