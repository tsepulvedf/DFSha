# Medición E8 protegida — 512 MiB

Run final `20261001T034229Z-9d313040`, terminado el 2026-10-01 a las 04:27:54 UTC
(2026-09-30, 23:27:54 Colombia). El supervisor persistió **APROBADO** y exit 0
observado del proceso de medición; fuentes sin modificaciones. No se recuperó
el exit code de la sesión externa después de la interrupción, y no se inventa.
[Resultado](20261001T034229Z-9d313040/result.json) y
[datos completos](20261001T034229Z-9d313040/measurement.json).
La ejecución anterior aprobada del 15 de septiembre conserva sus
[datos históricos](20260915T185856Z-525dabf5/measurement.json); las cifras siguientes
pertenecen exclusivamente a la repetición final tras D64.

```powershell
$verification = @('scripts/verify_stage8.py')
Get-ChildItem tests/test_stage7_*.py,tests/test_stage8_*.py | Sort-Object Name | ForEach-Object { $verification += @('--test', ('tests/' + $_.Name)) }
$verification += '--measure'
& .\.venv-win\Scripts\python.exe @verification
# Repetir solamente la medición en una raíz aislada nueva:
.\.venv-win\Scripts\python.exe scripts/verify_stage8.py --measure-only
```

Tres ControlNodes, un clúster de tres miembros etcd y tres DataNodes; usuario
ordinario, R=3/W=2, mayoría de metadatos 2. Archivo de 536870912 bytes, ocho
bloques de 67108864 bytes y fragmentos de 262144 bytes. Simulación de fallos de
procesos en un equipo Windows; no acredita pérdida de host ni acceso Internet.

SHA-256 original y descarga:
`c047731a3c134f3d34286d608e9c173027d50f43ab9d2064f3c360939977e908`.
Después del parche y segunda descarga:
`33dd21353ac79226f9ea36aa5bf30804a4226533bdc6fcd626ebd0e0661abe9d`.

| Evento medido | Segundos |
| --- | ---: |
| Inicio de send hasta su confirmación | 141,187 |
| Primera descarga completa | 24,141 |
| Llamada de parche de 4096 bytes hasta commit | 32,610 |
| Solicitud de detener el control activo hasta lectura exitosa con el mismo handle | 23,625 |

El último tiempo incluye la parada ordenada; no es latencia pura de detección.
`copies_before` y `copies_after_patch` acreditan tres recibos verificados y tres
copias elegibles por bloque vigente. W=2 se valida en la publicación; el ensayo
de tercera copia demorada pertenece además a la regresión de E6. No se deduce un
instante exacto de W=2 de una tabla capturada después de converger a R=3.

| node_id | Bloques primarios de subida | Cliente→DN inicial | DN→cliente primera descarga | S/S enviado por el parche | S/S recibido por el parche |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0ff9c8a8-712a-47f9-9812-221f77a51794 | 3 | 201326592 | 201326592 | 134228790 | 0 |
| 42ce6147-c5ef-4412-aca4-3b258feafcea | 2 | 134217728 | 201326592 | 0 | 67114395 |
| 7c73b3e6-7581-4474-90f7-e699f11675c7 | 3 | 201326592 | 134217728 | 0 | 67114395 |

Cada nodo terminó con las ocho versiones del manifiesto; los dominios son
`process-<node_id>`, etiquetas administrativas de proceso, no dominios físicos.
El parche transmitió **4096 bytes cliente→DN**, cero bytes de base DN→cliente y
**134228790 bytes cifrados S/S** (dos copias de 67114395 bytes; no sumar de nuevo
la recepción). El primario procesó 268435456 bytes de base y 134217728 de resultado
por las pasadas de autenticación/reconstrucción. No son bytes adicionales del cliente.
El contenido de archivos por los controles fue **0 bytes**, según el recorrido y
contadores de aplicación; esto no afirma tráfico de red cero ni es captura PCAP.

| Rol | Máximo residente observado por proceso, bytes |
| --- | --- |
| ControlNodes 0/1/2 | 71032832 / 55508992 / 49537024 |
| DataNodes 0/1/2 | 60698624 / 60772352 / 60579840 |
| etcd 0/1/2 | 68526080 / 71323648 / 66158592 |
| Cliente y supervisor de proxies, mismo proceso | 68628480 |

Los proxies midieron tráfico TLS de metadatos hacia/desde etcd por control:
2905872/3183102, 2834100/2274792 y 233913/667068 bytes. Estos contadores no incluyen
todo el tráfico C/S ni reemplazan los contadores de contenido.

La medición incluye D64, cache CLI cifrado, retención de salida nativa y validación
de rutas de claves en backup. Precedieron 36 casos E7/E8 sobre las mismas fuentes.
La membresía observada devuelve un único cluster_id `9416767923718602248`, tres
miembros y líder `3998544468149949074`; los tres endpoints coinciden en la autoridad.
Cada ejecución conserva sus huellas; no se presenta la cobertura histórica
agrupada como una sola suite. Los máximos son de este escenario y perfil, no una
garantía para todas las cargas ni una medición Linux.
