# Medición E7 corregida

Fuente: [measurement-fixed.json](measurement-fixed.json). Inicio UTC: 2026-09-13T23:54:34.639702+00:00.
Runtime: `F:\DFSha\.runtime\measure-e7\f7feadda-474a-496d-adfe-9da9258c266b`. Proceso supervisor terminó con código 0, recuperado mediante la sesión 60206.

512 MiB, bloques de 64 MiB, fragmentos de 256 KiB; tres controles, tres miembros etcd y tres DataNodes. R3/W2 y mayoría de metadatos 2/3 son conceptos distintos. Un solo host Windows; fallos de procesos.

SHA-256 inicial (subida y descarga): `c047731a3c134f3d34286d608e9c173027d50f43ab9d2064f3c360939977e908`.
SHA-256 tras parche y segunda descarga: `33dd21353ac79226f9ea36aa5bf30804a4226533bdc6fcd626ebd0e0661abe9d`.

| Evento | Segundos |
| --- | ---: |
| Inicio de send hasta confirmación | 186.922 |
| Inicio de write de 4096 bytes hasta commit | 29.907 |
| Solicitud de parada del control hasta completar lectura del mismo handle | 24.313 |

La última duración incluye parada del proceso, conmutación y autorización/lectura; no es solo el tiempo de detección. Se exigió W2 antes de CommitUpload/CommitWrite y se verificó convergencia a tres ubicaciones confirmadas y elegibles para cada bloque.

## Distribución y tráfico

Primera subida y primera descarga (bytes útiles confirmados por el SDK):

| node_id | Bloques primarios | Cliente → DN | DN → cliente |
| --- | ---: | ---: | ---: |
| 4c5b8909-0130-46b7-aba9-40154548b4e7 | 3 | 201326592 | 201326592 |
| bd4ad70d-c81e-4472-87ba-07425e5643b9 | 3 | 201326592 | 201326592 |
| c5a3bed6-462f-44c1-a4ee-022dd0ee37bc | 2 | 134217728 | 134217728 |

Tráfico acumulado de todo el escenario; S/S cuenta ciphertext con cabeceras. Cada enlace se cuenta por separado en emisor y receptor, no se suman ambas columnas como transferencias distintas.

| node_id | Cliente → DN | DN → cliente | S/S enviado | S/S recibido |
| --- | ---: | ---: | ---: | ---: |
| c5a3bed6-462f-44c1-a4ee-022dd0ee37bc | 134217728 | 268435456 | 268457580 | 469800765 |
| bd4ad70d-c81e-4472-87ba-07425e5643b9 | 201326592 | 402653184 | 402686370 | 402686370 |
| 4c5b8909-0130-46b7-aba9-40154548b4e7 | 201330688 | 402657280 | 536915160 | 335571975 |

Parche aislado: **4096 bytes cliente → DN**, cero DN → cliente durante el parche y **134228790 bytes S/S**, dos objetos cifrados de 67114395 bytes. El DN procesó 268435456 bytes de base y 134217728 bytes de resultado internamente, incluyendo verificaciones; almacenó un nuevo objeto cifrado de 67114395 bytes antes de sus réplicas. No se confunden esos pases internos con tráfico de cliente.

**Contenido del archivo por controles: 0 bytes**. Control sin BlockStore de contenido y rutas del SDK directas a DataNodes; los contadores anteriores verifican el recorrido útil. Esto no significa cero tráfico de red de los controles.

| Control | TLS hacia etcd | TLS desde etcd |
| --- | ---: | ---: |
| 0 | 3761565 | 2408802 |
| 1 | 405361 | 448617 |
| 2 | 1400865 | 1702122 |

Estos bytes son los observados por proxies TCP del laboratorio, incluyendo overhead TLS; no incluyen todo C/S de metadatos ni tráfico entre peers etcd.

## Copias por versión

| Estado | Índice | block_version_id | Confirmadas | Elegibles | Nodos / dominios |
| --- | ---: | --- | ---: | ---: | --- |
| Antes del parche | 0 | 34f4e52c-8ce9-473f-b219-46bf352d41d7 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Antes del parche | 1 | 5a26952a-34a9-47d6-8106-6121f9f63182 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Antes del parche | 2 | 5f016b0d-b271-4438-bcf0-bef3fe016da1 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Antes del parche | 3 | 7d4185a8-5726-4e2d-adc4-ee6bc3c94f27 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Antes del parche | 4 | 35150e6d-fd42-4e8b-9d79-432025f6eb46 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Antes del parche | 5 | eaa228d3-70e3-4313-b198-f6ca0a445698 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Antes del parche | 6 | 7f8cae67-dd86-4077-b46e-7936e36460c8 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Antes del parche | 7 | ba6e96e2-efa4-40ae-9837-0a21f4df4c74 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Después del parche | 0 | f2384c35-c255-47b8-adec-e43a4257a5fa | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Después del parche | 1 | 5a26952a-34a9-47d6-8106-6121f9f63182 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Después del parche | 2 | 5f016b0d-b271-4438-bcf0-bef3fe016da1 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Después del parche | 3 | 7d4185a8-5726-4e2d-adc4-ee6bc3c94f27 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Después del parche | 4 | 35150e6d-fd42-4e8b-9d79-432025f6eb46 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Después del parche | 5 | eaa228d3-70e3-4313-b198-f6ca0a445698 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Después del parche | 6 | 7f8cae67-dd86-4077-b46e-7936e36460c8 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |
| Después del parche | 7 | ba6e96e2-efa4-40ae-9837-0a21f4df4c74 | 3 | 3 | 4c5b8909-0130-46b7-aba9-40154548b4e7 / process-4c5b8909-0130-46b7-aba9-40154548b4e7, bd4ad70d-c81e-4472-87ba-07425e5643b9 / process-bd4ad70d-c81e-4472-87ba-07425e5643b9, c5a3bed6-462f-44c1-a4ee-022dd0ee37bc / process-c5a3bed6-462f-44c1-a4ee-022dd0ee37bc |

Cada ubicación incluye en el JSON su recibo durable, generación, longitud, hash plaintext/ciphertext y salud. Los dominios `process-*` son simulados, no hosts independientes.

## Memoria y membresía

| Rol / Índice | Pico residente reportado (MiB) |
| --- | ---: |
| Control 0 | 66.21 |
| Control 1 | 46.34 |
| Control 2 | 49.80 |
| DataNode 0 | 60.78 |
| DataNode 1 | 56.64 |
| DataNode 2 | 56.12 |
| etcd 0 | 63.11 |
| etcd 1 | 70.05 |
| etcd 2 | 63.76 |
| Cliente y supervisor de proxies | 64.80 |

Valores PeakWorkingSet del PID real hasta el instante de cada muestra. Los controles se muestrearon antes de detener uno; los DataNodes y cliente al final. El proceso cliente también hospeda el supervisor y proxies. No extrapolar estos picos a otras cargas o perfiles.

| Miembro etcd | Clúster | Líder observado |
| --- | --- | --- |
| 14739887032187302312 | 13806066471760757987 | 8791705754363490418 |
| 371834853243985474 | 13806066471760757987 | 8791705754363490418 |
| 8791705754363490418 | 13806066471760757987 | 8791705754363490418 |

Se consultó MemberList/Status mediante mTLS; cada miembro informó los mismos tres miembros del clúster.

## Reproducción

```powershell
.\.venv-win\Scripts\python.exe scripts/measure_stage7.py --evidence docs/evidencias/etapa7/measurement-repeat.json
```

La segunda descarga usa overwrite=True de forma explícita. Las ejecuciones fallidas se conservan; esta medición no sustituye la regresión ni el inventario de aceptación E7.
