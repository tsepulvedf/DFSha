# Cierre E8 — 2026-10-01

**E8 completa para el perfil protegido y modelo de amenazas de laboratorio.**
Tres ControlNodes activos, un clúster etcd de tres miembros y tres DataNodes,
R=3/W=2, TLS/mTLS, metadatos autoritativos compartidos, cifrado aplicativo de
datos/metadatos/inventarios/backups y autorización por usuario/grupo. Los bytes
siguen viajando directamente con los DataNodes. No se ejecutó E9.

Implementación, pruebas y evidencias: commit `b1c57b5`, publicado sin force push.
Fetch posterior confirmó HEAD y origin/main en
`b1c57b5f4109674b8bc186f62c0d55f81e003c24`, sin cambios pendientes antes de añadir
este registro documental de publicación. No se modificó la toolchain fijada.

## Ejecuciones y cobertura

| Ejecución | Resultado | Interpretación |
| --- | --- | --- |
| Windows `20260916T001737Z-8b37116e` | 59 casos con las tres fases aprobadas antes de interrumpirse; exit desconocido | No se declara aprobada toda la ejecución; se conservan sus casos terminados |
| Windows `20260930T231040Z-3b63eca4` | 114 aprobados y 2 fallidos; pytest exit 1 | Los fallos se diagnosticaron y corrigieron; el run sigue FALLIDO |
| Windows `20261001T034229Z-9d313040` | 36 E7/E8 aprobados en 2299,16 s; medición 512 MiB aprobada | Cinco comandos con exit 0 persistido, fuentes sin cambios; sesión externa no recuperable |
| Linux `20261001T034403Z-581a2df8` | Los mismos 36 E7/E8 aprobados en 439,88 s | Wheel instalado, verificador/contenedor exit 0, fuentes sin cambios |

La unión contiene **177 casos distintos aprobados**, con asignación del último
resultado completo en [final-coverage.json](final-coverage.json). No se suman
repeticiones ni se presenta como una única ejecución íntegra. La recopilación
final contiene los mismos 177 casos, sin huecos de cobertura.

Entre las ejecuciones antiguas y el cierre cambió la recuperación del lease de
barrera etcd; todos los casos HA E7/E8 y la medición se repitieron. Los cambios
del launcher permiten contraseña privada y reanudación; los fixtures históricos
conservan su valor predeterminado. Se añadieron dos casos específicos. El ajuste
Docker incorpora documentación al paquete de verificación. Los perfiles SQLite,
RF1/RF2/RF3 y sus casos anteriores no fueron modificados para hacerlos pasar.
Las huellas y diferencias de fuentes quedan en el inventario de cobertura.

El fallo de respuesta perdida no demostraba un commit: se exige ahora que
GetOperation sea COMMITTED y que se haya consumido el punto de inyección antes
de afirmar ese escenario. La barrera descartaba incorrectamente su liberación
incierta pero conservaba el lease reutilizable; un reintento podía prolongarla.
D64 descarta ese lease, permite su expiración real y conserva CAS/fencing.
[Diagnóstico y reproducción previa al arreglo](diagnostico-regresion.md).

## Reproducción

PowerShell, desde `F:\DFSha`, mismo entorno fijado:

```powershell
# Selección exacta del cierre, seguida de 512 MiB protegidos:
$verification = @('scripts/verify_stage8.py')
Get-ChildItem tests/test_stage7_*.py,tests/test_stage8_*.py | Sort-Object Name | ForEach-Object { $verification += @('--test', ('tests/' + $_.Name)) }
$verification += '--measure'
& .\.venv-win\Scripts\python.exe @verification

# Toda la suite en una nueva ejecución (los resultados anteriores son agrupados):
.\.venv-win\Scripts\python.exe scripts/verify_stage8.py --regression
# Solo la medición:
.\.venv-win\Scripts\python.exe scripts/verify_stage8.py --measure-only
```

Linux se ejecutó con imagen `dfsha-e8-validation:closure`, red externa deshabilitada,
2 CPU, 3 GiB de límite y volumen propio. [Estado real del contenedor](20261001T034403Z-581a2df8/container-exit.json)
y [comandos internos exactos](20261001T034403Z-581a2df8/result.json).

```powershell
docker build -f deploy/Dockerfile.verify-e8 -t dfsha-e8-validation:closure .
docker run --name dfsha-e8-reproduce --network none --cpus 2 --memory 3g --pids-limit 512 --mount type=volume,source=dfsha-e8-runtime-reproduce,target=/workspace/.runtime dfsha-e8-validation:closure python scripts/verify_stage8.py
```

El último comando reproduce los casos E8 predeterminados; para la selección de
36 añadir los `--test` que constan en el resultado. Usar nombres nuevos para
otra ejecución; no eliminar recursos de otros laboratorios. La imagen contiene
etcd Linux y dependencias fijadas. La medición de 512 MiB aquí acreditada es Windows.

## Evidencia funcional y límites

La [matriz de aceptación](aceptacion.md) relaciona criterios con casos reales:
revocación entre controles después de open/W2, grupos y recorrido, roles internos,
RBAC/peers etcd, certificados, claves, backups, retención y límites. E7 se repitió
para failover, mayoría, partición TCP, fencing, idempotencia, mantenimiento/GC,
migración/restauración y continuidad de handles. No se aceptaron permisos vencidos
ni se aumentaron arbitrariamente TTL para aprobar.

La [medición](medicion-protegida.md) conserva hashes, tabla por nodo, memoria,
tráfico de metadatos y delta. El paquete actualizado pasó siete comprobaciones
en [installed-package-gate-fix.json](installed-package-gate-fix.json); Linux usa
ese código instalado. Los dos casos CLI instalados anteriores conservan su
[evidencia](installed-ha-final.json), sin cambio posterior de esa funcionalidad.

RNF6 se acredita sobre las rutas y amenazas descritas en [seguridad](../../seguridad.md).
No implica cifrado de todos los sectores, paginación/hibernación o volcados del
SO; esos controles del host no fueron ensayados. UUID, estructura opaca y tiempos
de coordinación siguen visibles. Un administrador con claves queda fuera del
modelo de confidencialidad; no hay resistencia bizantina ni CRL declarada.
La custodia en otro medio, hosts independientes e Internet están pendientes.
Q03 y Q05 siguen sin respuesta docente. La retirada de claves es conservadora;
no hay borrado automático ni recifrado automático de la clave maestra de metadatos.
Los ledgers/tombstones se retienen; compactación MVCC es administración separada.
