# Evidencia E5

Las ejecuciones se conservan separadas. No sumar pruebas repetidas ni trasladar
mediciones de un perfil a otro. Todos los laboratorios de esta sesión son locales
en Windows; R=1/W=1, un control SQLite y tres DataNodes.

| Ejecución | Estado real | Alcance |
| --- | --- | --- |
| [Baseline H2](../etapa4/20260911T035537Z/result.json) | 100 pruebas aprobadas; medición FALLIDA | DATA_UNAVAILABLE durante PutBlock bajo tres clientes. |
| [Repetición H2](h2-measurement-repeat.json) | FALLIDA | Reprodujo rechazo de AuthorizeBlock/ResolveBlocks y reinscripción tras heartbeat sin respuesta. |
| [H2 corregido](h2-measurement-fixed.json) | EJECUTADO, aprobado | 512 MiB más dos clientes de 128 MiB; hashes idénticos y memoria dentro de metas. Corrección D44. |
| [Regresión RF3 inicial](20260911T043304Z/result.json) | EJECUTADO, aprobado | 113 pruebas, 605,47 s; H1/H2/RF3 y contratos. |
| [Medición RF3 inicial](20260911T043304Z/measurement.json) | EJECUTADO, aprobado | 4096 bytes de delta sobre 512 MiB, bloque de 64 MiB, hash final esperado. Campos de tráfico ausentes equivalen a cero; el cierre los explicita. |
| [Paquete inicial](package.json) | EJECUTADO, aprobado | Wheel instalado sin editable e importación; anterior a los últimos ajustes. |
| [Paquete final](package-final.json) | EJECUTADO, aprobado | Wheel reconstruido con los ajustes finales, pip check, importación aislada y CLI. El nombre del helper conserva etapa3 por continuidad. |
| [Smoke del wheel](installed-smoke.json) | EJECUTADO, aprobado | 8 MiB, parche de cinco bytes entre bloques, snapshots y descarga desde site-packages; cuatro procesos reales. |
| [Regresión final](20260911T045117Z/result.json) | EJECUTADO, aprobado | 114 pruebas en 647,27 s, cero fallos/errores/omisiones; 34 módulos importados y 56 RPC. Incluye los ajustes de renovación, reloj monotónico y D44. |
| [Medición final](20260911T045117Z/measurement.json) | EJECUTADO, aprobado | 512 MiB / bloques 64 MiB; delta 4096 bytes, 3,734 s, SHA-256 idéntico; dos cambios concurrentes verificados y memoria dentro de metas. |
| [Publicación Git](git-publicacion.json) | EJECUTADO | Implementación 94d6407 publicada en origin/main; hash remoto idéntico y checkout limpio antes del commit documental de este registro. |

La ejecución final terminó correctamente. Los fallos no se sustituyen por resultados
posteriores ni se cuentan como aprobados. Logs privados, claves, volúmenes y
archivos grandes permanecen bajo `.runtime/`, excluido de Git.

Fuentes preservadas: PDF SHA-256
`0ec8cc4cf92f9cf9345d5cf147d096a9cc74f78146aabce823d3890a31b446bf`
y guía SHA-256
`755d2bebc288133e54e4f3161a433c35e6d08a9f0a7c8dce9b9b031e41c902b3`.
PDF leído íntegramente (siete páginas). Q01–Q07 sin aclaraciones nuevas.
