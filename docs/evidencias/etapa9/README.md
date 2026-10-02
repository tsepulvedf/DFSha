# Evidencias E9 — preparación parcial

**Actualización 2026-10-02:** AWS Academy confirmado. [Preparación de acceso,
coste y parada](academy/README.md) conserva bloqueo real de credenciales/región,
34 casos locales finales y propuesta no autorizada. El informe siguiente es la
preparación del 1 de octubre; el proveedor ya no está pendiente.

Fecha local: 2026-10-01. Los run_id usan UTC y pueden comenzar por 20261002.
**E9 no está completa.** Proveedor académico y presupuesto no definidos;
no se aprovisionaron recursos. [Propuesta, scripts y límites](../../despliegue.md).

| Comprobación | Resultado real | Evidencia |
| --- | --- | --- |
| Estado E8 | `fe63534`/`b1c57b5`, main/origin 0/0 antes de editar | Git revisado, PDF con SHA256 original; no se reinterpretan 177 casos como una sola suite |
| Acceso académico | BLOQUEADO POR ENTORNO; sin CLI/perfiles AWS/GCP hallados ni cuenta elegida | [preflight](preflight.json), ninguna llamada a cuenta implícita |
| Preparación inicial | 17 aprobados y 1 fallido, exit 1 | [intento preservado](preparation.json); etcd rechazó allowed-cn como string JSON |
| Dependencias, contratos y regresión | 93 aprobados en 112,45 s; tres comandos exit 0, supervisor exit 0 observado | [resultado](20261002T001950Z-7ab94a83/result.json), [salida observada](20261002T001950Z-7ab94a83/observed-exit.json) |
| Preparación final/negativa adicional | 18 aprobados en 9,39 s, exit 0 | [repetición](preparation-final.json); peer con identidad incorrecta rechazado, miembros siguen disponibles |
| Shell y CLI | Nueve comandos exit 0 | [script-checks](script-checks.json); `bash -n` es sintaxis, no instalación Linux |
| Wheel instalado | Siete comandos exit 0 | [paquete](installed-package.json); entorno limpio existente, imports sin editable |
| VMs, Internet, parada de host, R3 sobre hosts, backup cloud | NO EJECUTADOS / BLOQUEADOS | No hay resultados ni métricas que puedan publicarse como cloud |

El run principal conserva huellas sin cambios durante su ejecución. Después se
añadió una comprobación negativa al test de configuración etcd; los 18 casos de
preparación se repitieron. No cambió código de aplicación después del run de 93.
Esos 18 se superponen, no se suman para afirmar 111 casos distintos. Los 93
incluyen diagnóstico/UNIMPLEMENTED del perfil de pruebas, no afirman que RF1/RF2/RF3
estén pendientes en el servicio funcional. La regresión usa procesos y sockets
reales **locales**, tres etcd del mismo clúster con configuración JSON y el HA
protegido de E8. Los inventarios de tests dicen TEST_FIXTURE_NOT_DEPLOYED.

Se confirmó Docker cliente instalado y motor detenido; no es ausencia del cliente.
Se descargaron herramientas Linux etcd 3.6.14 con archivo oficial verificado:
`ffe840ff9295808e88cce2794a18a5ac87f12a5203c8314d0bf6aa119b41bac5`.
No se ejecutaron esas herramientas en una VM Linux. El artefacto inicial en
`.runtime/cloud-artifacts-e9-initial` se identifica como dirty/base E8; no se
presenta como un despliegue del commit E8. Después se construyó el artefacto final
desde `94dbc639d2ec42b3fe9049b80bf74be1bb0d164d`, árbol limpio y exit 0 observado.
[Identidad y hashes](artifact.json); wheel privado en
`.runtime/cloud-artifacts-e9-94dbc63/dfsha-0.3.0-py3-none-any.whl`, SHA-256
`fde02754f291a35eded59ae9fd3bcb1711bada09c98c1bf2396ed6511fdb6382`.
Los cambios posteriores a ese commit son documentación/evidencia, no aplicación.
El commit se publicó sin force push y fetch confirmó la misma referencia local/remota.

Reproducción PowerShell desde `F:\DFSha`:

```powershell
.\.venv-win\Scripts\python.exe scripts/cloud_preflight.py
.\.venv-win\Scripts\python.exe scripts/verify_stage9.py --local
.\.venv-win\Scripts\python.exe -m pytest -q tests/test_stage9_deployment.py
.\.venv-win\Scripts\python.exe scripts/check_package_stage3.py --python .venv-verify-20260908T212227145653Z/Scripts/python.exe --evidence .runtime/verification-e9/installed-repeat.json
```

El primer comando debe registrar bloqueo mientras no se configure proveedor; no
significa prueba cloud aprobada. El verificador registra resultados por fase y
un resumen atómico. `intended_exit_code` es lo que devolverá el script, distinto
del exit real recogido por el ejecutor. Logs/XML completos siguen privados en
`.runtime/verification-e9/`; los resúmenes no publican credenciales.

Pendientes esenciales: acceso/cuotas/coste; aprovisionador del proveedor elegido;
montajes y controles Linux efectivos; bootstrap remoto/reinicio; validación externa
512 MiB, hashes/tráfico/memoria/CPU/disco; caída de VM y retorno; quórum; cuarta VM
si se autoriza; backup/restauración cloud independiente. GCP requiere concretar su
adaptador de asociación VM/discos al obtener el proyecto. No se ejecutó E10.

No se crearon recursos cloud; no hay recursos E9 encendidos, detenidos o con coste
persistente atribuible a este trabajo. No se conoce el estado/coste de recursos
preexistentes de una cuenta aún no accesible. La estimación publicada es propuesta,
no facturación observada ni autorización de gasto.
