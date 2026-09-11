# DFSha

**Etapa 5 completa en Windows local: RF3 y concurrencia parcial.** Open/close,
lectura por rangos, parches COW y locks funcionan en el perfil `--rf3`, reutilizando el control y DataNodes
de H2. [Semántica y reproducción](docs/etapa5-rf3.md); [estado real](docs/estado.md).
Los resultados E4 siguientes son históricos, no mediciones de RF3.

Verificación E5: **114 pruebas aprobadas, sin omisiones**, contratos regenerados y
paquete instalado probado. Parche de 4 KiB sobre 512 MiB: 4096 bytes cliente→DN,
cero contenido en control y hash final correcto. Dos escritores preparan bloques
distintos antes de publicar y conservan ambos cambios. [Resultados y memoria](docs/etapa5-rf3.md#resultados-del-cierre).
Siguiente etapa: E6, replicación y recuperación; todavía no ejecutada.

Proyecto 1 de SI3007/ST0263, período 2026-2. Opción 1: cliente/servidor de una organización, con composición S/S mediante red privada.

**Etapa 4 completa en Windows local: control y DataNodes independientes.**
RF1/RF2 reutilizan la lógica H1; el cliente resuelve destinos y transfiere directamente
con DataNodes. R=1/W=1, SQLite en control, registro/inventarios/heartbeats mTLS,
reservas y copia S/S ordenada. [Arranque y demo H2](docs/hito2.md),
[protocolos](docs/protocolos-hito2.md), [evidencias](docs/evidencias/etapa4/README.md).

Validación E4: **100 pruebas aprobadas**, wheel instalado con transferencia real,
512 MiB/3 clientes y bytes útiles repartidos entre tres DN. Picos residentes en
esa medición: cliente 56,2 MiB, control 82,1 MiB, DN 56,5 MiB; perfil 64 MiB.
R=1/W=1 no acredita HA. Estos resultados corresponden al cierre histórico E4.

**Etapa 3 histórica completa: RF1/RF2 en un monolito modular C/S con SQLite y bloques cifrados.**
CLI/shell/SDK, usuarios/permisos, snapshots, overwrite explícito, recuperación y
transferencias TLS. 51 RPC: 27 funcionales locales, tres diagnósticas y 21 futuras.
En aquel cierre RF3, replicación automática y HA quedaban pendientes. H1 sigue reproducible.

Validación final Windows: **87 pruebas aprobadas**, roundtrip 1 GiB y tres clientes;
picos residentes cliente 51,6 MiB y servidor 81,5 MiB. [Resultados](docs/evidencias/etapa3/20260909T195446Z/resultado.json).

Arranque, demo y comandos: **[Hito 1](docs/hito1.md)**. Validación conjunta:
`.\.venv-win\Scripts\python.exe scripts/verify_stage3.py`; medición independiente:
`.\.venv-win\Scripts\python.exe scripts/measure_hito1.py`.

Repositorio único: [tsepulvedf/DFSha](https://github.com/tsepulvedf/DFSha), origin de
`F:\DFSha`, rama main publicada y siguiendo origin/main. Referencias E2 `df1fd33`,
E3 `7bd8327`/`d91e2ba`, implementación E4 **`48509a6`**: push y hash remoto
verificados sin force. [Estado](docs/estado.md) y [evidencia Git E4](docs/evidencias/etapa4/git-publicacion.json).
El registro de publicación se conserva en un commit documental posterior.

## Base de etapa 2 preservada

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

Diseño: [especificación](docs/especificacion.md), [arquitectura](docs/arquitectura.md), [decisiones](docs/decisiones.md), [matriz](docs/matriz-requisitos.md). H1 usa SQLite/bloques locales; etcd no es dependencia del monolito. Siguiente etapa: **E4, separar control y DataNodes con transferencia directa y colocación real**. H1 semana 8; H2 semana 10; H3 semana 12; final semana 13. E4 no se ejecuta en esta entrega.
