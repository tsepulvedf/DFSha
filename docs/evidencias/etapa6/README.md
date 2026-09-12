# Evidencias E6 — replicación y recuperación

Fecha de cierre: 2026-09-12. Windows local, un ControlNode SQLite, tres DataNodes
y ampliación a cuatro, volúmenes separados; R3/W2 en dominios de proceso simulados.
No acredita hosts independientes, Linux, Internet, HA del control ni seguridad integral.

Implementación y evidencias publicadas en `7005b09`, push normal y hash remoto
verificado: [registro Git](git-publicacion.json). Este registro documental se
incorpora después del commit funcional. [Revisión publicable](delivery-review.json)
comprobó 60 archivos y no detectó claves privadas, volúmenes ni archivos gigantes.
La [auditoría](audit-final.json) verifica 58 filas RPC, enlaces y fuentes originales.

## Ejecuciones y correcciones conservadas

| Evidencia | Resultado real y alcance |
| --- | --- |
| [Regresión E5 de partida](../etapa5/20260911T103142Z/result.json) | 114 aprobadas en 594,65 s, medición E5 aprobada antes de integrar E6 |
| [Primera comprobación](first-check.xml) | 1 aprobada en 20,60 s: W2 antes de tercera copia |
| [Desarrollo E6](development-check.xml) | 10 aprobadas en 473,41 s; incluye los tres perfiles |
| [Recuperación inicial](recovery-check.xml) | 1 aprobada y 1 FALLIDA: la expectativa de NORMAL inmediato ignoraba una tercera copia todavía pendiente |
| [Recuperación corregida](recovery-repeat.xml) | 3 aprobadas en 124,84 s, esperando convergencia observable; no se elimina el fallo anterior |
| [Regresión completa](20260911T202330Z/result.json), [JUnit](20260911T202330Z/pytest.xml) | **130 aprobadas en 1413,54 s**, cero fallos/errores/omisiones; H1/H2/E5/E6, TLS y contratos |
| [GC complementaria](gc-check.xml) | 1 aprobada en 39,10 s: todas las copias físicas persisten con lector y desaparecen tras close; amplía un caso ya contado |
| [Generación física](delete-generation-check.xml) | 1 aprobada en 0,21 s: comparación de recibo impide borrado de instancia reemplazada; prueba aislada con autorización sustituida, no evidencia de distribución |
| [Wheel final](package-final.json), [smoke instalado](installed-smoke.json) | Paquete construido e instalado; procesos reales desde site-packages, R3/W2, 8 MiB, parche de cinco bytes entre bloques y snapshot anterior |
| [Medición final](measurement-final.json), [tablas](medicion.md) | 512 MiB, tres copias reales, hashes, caída, cuarto nodo, reparación, tráfico y memoria por PID real |

Son **131 casos distintos aprobados** entre la regresión de 130 y la comprobación
aislada adicional; las repeticiones no se suman como cobertura nueva. La prueba
física de generación complementa corrupción/reparación por red y el rechazo real
de callbacks con época anterior. No simula una distribución mediante mocks.

La [primera medición completa](20260911T202330Z/measurement.json) aprobó contenido,
replicación y recuperación, pero tomó los PID lanzadores venv para memoria CN/DN:
**esos máximos y memory_goals_met no son válidos para servidores**. Además, su
client_useful_traffic era una copia superficial mutable y patch_traffic incluía
una lectura de validación de 4096 bytes. Usar transfer_traffic para el tráfico
inicial de ese archivo; no usar sus contadores afectados como ventana de parche.

[Primera corrección](measurement-corrected.json) tomó PID reales y ventanas de
tráfico independientes, pero no capturó la memoria del nodo ya detenido. La
medición final conserva también su máximo antes de detenerlo y sustituye ambas
para el cierre. Se mantienen todas las fuentes para auditar las correcciones.

El primer intento del smoke instalado terminó con SyntaxError en el script
(asignación en iterable de comprensión). Se corrigió el script, sin modificar
el paquete, y la repetición enlazada pasó. package.json y contract-audit.json
son comprobaciones preliminares, sustituidas por package-final.json y la
auditoría documental final; no son pruebas adicionales de RF/RNF.

## Cobertura y límites

tests/test_stage6.py comprueba tercera diferida, rechazo W insuficiente por bloque,
recibo duplicado, commit con primario detenido, escritores distintos preparados
con barreras, fencing vencido, respuesta perdida, perfiles 4/64/128, copia corrupta
y lectura alternativa con stream interrumpido, retorno y volumen perdido aislado,
clave incorrecta, promoción R1 incluyendo snapshot retenido, callback de otra
época, permisos de protección/promoción y GC con tombstone.

La regresión heredada conserva rutas, RF1/RF2/RF3, errores de capacidad, acceso
directo no autorizado, certificados inválidos, revocación y fallos de transferencia.
No se presenta cada combinación posible de fallo R3 como ejecutada por heredar
una prueba R1. No se ensayó caída eléctrica, pérdida física de host, particiones
de red entre VMs ni agotamiento prolongado con todos los clientes y reparaciones.
La medición de memoria E6 usa una sesión SDK; dos clientes/handles concurren en
las pruebas con barreras. Los benchmarks de concurrencia amplia quedan E10.

La cuarentena retiene evidencia y consume cuota; no se purga automáticamente.
SQLite/WAL/inventarios/backups no tienen cifrado de volumen acreditado. W cuenta
datos, no votos ni quórum de metadatos. Etcd/HA E7, seguridad E8 e Internet/cloud
siguen pendientes; Q01–Q07 sin nuevas respuestas.

## Comandos PowerShell desde F:\DFSha

```powershell
.\.venv-win\Scripts\python.exe scripts/verify_stage6.py --measure
.\.venv-win\Scripts\python.exe scripts/measure_stage6.py --evidence docs/evidencias/etapa6/measurement-repeat.json
.\.venv-win\Scripts\python.exe -m pytest -q tests/test_stage6.py -k "restart_pending_and_gc_tombstone or late_delete_physical_generation_guard"
.\.venv-win\Scripts\python.exe scripts/check_package_stage3.py --python .venv-verify-20260908T212227145653Z/Scripts/python.exe --evidence docs/evidencias/etapa6/package-repeat.json
.\.venv-verify-20260908T212227145653Z\Scripts\python.exe -I scripts/check_installed_stage6.py
.\.venv-win\Scripts\python.exe scripts/summarize_stage6.py
```

El helper de wheel conserva su nombre histórico stage3; construye el código actual.
El venv de comprobación indicado existe en esta máquina; en otra se prepara uno
aislado con el mismo lock siguiendo entorno.md. No se guardan claves, bases,
bloques ni archivos gigantes en estas evidencias.
