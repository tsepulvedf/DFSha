# AWS Academy — preparación del 2 de octubre de 2026

**E9 PARCIAL. Sin recursos creados ni acceso autenticado.**
El proveedor está confirmado; USD 50 generales no autorizan gasto. Perfil `academy`
todavía no configurado, CLI ausente en las rutas revisadas, región desconocida.
No se verificaron gratuidad, saldo, cuotas o permisos. No se ejecutó E10.

| Ejecución | Resultado observado | Alcance |
| --- | --- | --- |
| [access.json](access.json) | BLOQUEADO_POR_ENTORNO, exit 2 real, lista de comandos AWS vacía | Perfil/token/región/CLI; no acceso a cuenta implícita |
| [preparation.json](preparation.json) | 31 aprobados, 11,07 s, exit 0 | Primera preparación |
| [preparation-final.json](preparation-final.json) | 31 aprobados, 10,74 s, exit 0 | Repetición tras ajuste de solicitudes |
| [closure.json](closure.json) | 31 aprobados / 3 fallidos, 10,76 s, exit 1 | Al añadir renovación: doble urllib del test usó `.method` inexistente en GET |
| [closure-corrected.json](closure-corrected.json) | **34 aprobados, 10,49 s, exit 0** | Corrección `get_method()`; mismos rechazos y efectos esperados |
| [guard-dependency.json](guard-dependency.json) | 16 aprobados, 0,83 s, exit 0 | Ajuste final: servicios dependen del timer activo, no del oneshot periódico; casos superpuestos |
| [script-checks.json](script-checks.json) | Seis comandos exit 0 | Cinco `--help` y sintaxis bash del instalador; no Linux runtime |
| [costs.json](costs.json) | Estimación condicional | Referencia us-east-1, sin beneficio descontado ni autorización |

No sumar ejecuciones repetidas. Los 34 reúnen 16 casos Academy y 18 anteriores
E9. Después solo cambió la dependencia systemd de la guardia; esos 16 casos se
repitieron sobre su fuente final, con hashes separados. Los 18 anteriores E9
incluyen clúster real de tres etcd locales y rechazo de peer incorrecto.
Las respuestas AWS, IMDS y poweroff están aisladas/simuladas en pruebas:
acreditan reglas y generación, **no detención de VMs**. La prueba negativa
comprueba que no hay consulta de recursos tras identidad inválida/token ausente,
que no se reemplazan otros perfiles y que una ventana excesiva no altera el deadline.
Se preserva la prueba original Windows de configuración/TLS/etcd; no se alteró
el paquete del servicio, la toolchain, los contratos ni los perfiles E8.

Comandos exactos PowerShell, desde F:\DFSha:

```powershell
.\.venv-win\Scripts\python.exe scripts/cloud_preflight.py --output .runtime/academy/access-20261002.json
.\.venv-win\Scripts\python.exe scripts/academy_cost.py --output docs/evidencias/etapa9/academy/costs.json
.\.venv-win\Scripts\python.exe -m pytest -q tests/test_academy_preparation.py tests/test_stage9_deployment.py --junitxml=.runtime/academy/closure-corrected.xml
```

El supervisor guardó `$LASTEXITCODE` inmediatamente después de pytest/preflight,
sin deducirlo de un log. Logs/XML completos y códigos originales en `.runtime/academy/`.
Los JSON publicables incluyen resultados individuales y hashes de fuentes finales.
Los comandos con secretos son interactivos y **no se ejecutaron** aquí.
No hay pruebas activas pendientes de consultar.

[Propuesta económica y runbook completo](../../../aws-academy.md).
Antes de declarar E9 completa faltan cuenta/región/permiso económico, creación
autorizada, controles Linux efectivos, timer/stop real, prueba Internet 512 MiB,
fallo/reingreso de VM, backup/restauración y métricas. Aceptar USD 4 no equivale
a comprobar esos criterios ni a un máximo monetario garantizado.
