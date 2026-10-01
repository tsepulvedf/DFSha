# Evidencias E8 — ejecución incremental

E8 cerrada en el perfil protegido: [cierre y límites](cierre.md).
Los resultados históricos E7 no se atribuyen a E8.
Cada directorio de run conserva huellas de fuentes, comandos, PID, tiempos y
códigos de salida observados. `cases.jsonl` se sincroniza por fase de pytest.
Los logs completos y XML con diagnósticos están fuera de Git en
`.runtime/verification-e8/<run_id>/`. No deducir éxito de una fase setup o teardown.

| Ejecución | Resultado conocido | Alcance |
| --- | --- | --- |
| baseline.xml | 7 casos aprobados, exit desconocido | Regresión inicial seleccionada |
| storage.xml | 3 aprobados, exit 0 observado | AEAD de metadatos, SQLite/WAL y perfil HA protegido |
| 20260915T052544Z-6d500e30 | 3 aprobados, 1 fallido, exit 1 | Deadline Login; evidencia preservada |
| 20260915T052855Z-10b19c88 | 2 aprobados, 2 fallidos, exit 1 | Límite de deadline del servidor aún antiguo |
| 20260915T053056Z-5ba7edd9 | 1 fallido, exit 1 | El test no consumía el generador de ls |
| 20260915T053444Z-3a21c8f3 | Caso de autorización aprobado; supervisor detectó modificación de fuentes | No es una suite final inmutable |
| 20260915T054248Z-87e6bd4a | 2 aprobados, 1 fallido, exit 1 | Restauración abrió un inventario cifrado sin codec |
| 20260915T102901Z-14ee6862 | 4 aprobados, exit 0; fuentes sin cambios | Restauración protegida, rotación/snapshots/revocación y claves |
| 20260915T103652Z-bbd837f8 | 11 aprobados en 586,27 s; pytest/pip/protos/catálogo exit 0 | Medición interrumpida durante arranque; exit desconocido; recovery-observation.json |
| 20260915T185856Z-525dabf5 | 9 casos aprobados en 250,31 s; medición y supervisor exit 0 | Bootstrap, límites, junction, retención, certificados y 512 MiB; [medición](medicion-protegida.md) |
| 20260916T001016Z-5da64251 | 5 casos aprobados; supervisor exit 1 por cambios de fuentes | CLI cifrada, logs acotados, permisos de bloque y restauración; la regresión final repite estos casos |
| 20260916T001443Z-b0ae98f1 | Linux: 19 casos aprobados en 165,81 s; supervisor exit 1 | Auditoría posterior falló por documentación ausente en la imagen; no fue un fallo de los 19 casos |
| 20260916T002301Z-f5084da3 | Linux: 19 casos y verificador aprobados; exit 0 observado en Docker | Repetición después de incorporar docs; imagen instalada, red externa deshabilitada |
| 20260916T001737Z-8b37116e | Windows: INTERRUMPIDO, exit desconocido | 59 casos con tres fases aprobadas; el siguiente no terminó teardown; recovery-observation.json |
| 20260930T231040Z-3b63eca4 | Windows: 114 aprobados/2 fallidos en 2817,20 s, pytest exit 1 | Sin cambios de fuentes; [diagnóstico](diagnostico-regresion.md); no se da por aprobada la selección |
| 20260930T231236Z-6a12916f | Linux: 19 aprobados en 171,25 s; supervisor/contenedor exit 0 | Dockerfile corregido, sin copia manual; paquete instalado y fuentes sin cambios |
| 20261001T033756Z-f6944354 | Windows: fallo esperado de reproducción, 6,10 s, exit 1 | Proxy TCP reprodujo lease abandonado retenido en caché antes de corregirlo |
| 20261001T034010Z-c326ea4d | Windows: 2 aprobados en 65,18 s, exit 0 | Recuperación de la barrera y arranque privado/reanudación con contraseña cambiada |
| 20261001T034229Z-9d313040 | Windows: 36 aprobados en 2299,16 s y medición 512 MiB aprobada | Cinco comandos con exit 0 persistido, fuentes sin cambios; exit de sesión externa desconocido |
| 20261001T034403Z-581a2df8 | Linux: 36 aprobados en 439,88 s; contenedor exit 0 | Misma selección E7/E8, paquete instalado y fuentes sin cambios |

Los intentos fallidos permanecen diferenciados. No sumar casos repetidos para
presentarlos como pruebas distintas ni afirmar que una selección sustituye la
regresión de RF1/RF2/RF3, failover y recuperación. Todas las topologías de esta
carpeta son procesos en un único equipo; las ejecuciones Linux usan un contenedor
aislado dentro del mismo host. Ninguna acredita pérdida de host.

`installed-package.json` contiene siete comandos con exit 0 observados:
construcción/instalación del wheel en `.venv-verify-20260908T212227145653Z`,
pip check, importación instalada y entradas CLI. Esa ejecución corresponde al
estado previo a las adiciones posteriores de bootstrap/retención; las repeticiones
siguientes cubren el código posterior. No es una prueba HA desde el paquete instalado.

`installed-package-final.json` repitió los siete comandos con exit 0 sobre el
estado final de aplicación. `installed-ha-final.json` ejecutó Python `-I` desde
ese venv, con dos casos aprobados en 89,98 s: cache cifrado y CLI ordinaria usando
conexiones reales al perfil HA, incluyendo logout. No usó el paquete editable.

`installed-package-gate-fix.json` repitió los siete comandos tras D64 y el cambio
del launcher; exit 0 observado. Los 36 casos Linux finales usan el paquete
instalado con esa corrección. [Cobertura Windows por caso](final-coverage.json):
177 distintos aprobados, sin contar duplicados ni fases incompletas.
