# Medición final E7

Fuente: [measurement-final.json](measurement-final.json), inicio UTC `2026-09-14T19:23:17.285962+00:00`.
Runtime: `F:\DFSha\.runtime\measure-e7\dd7737a0-7bfd-4dcb-b1e2-296d55fb8849`.

Informe terminal EJECUTADO: validaciones completas, cierre del laboratorio y ausencia de procesos comprobados. La sesión 16476 se perdió tras una interrupción; su código de salida no fue recuperable. No se atribuye un código 0 no observado. La [medición corregida anterior](medicion-fixed.md) sí tiene salida 0 recuperada.

512 MiB; bloques de 64 MiB; fragmentos de 256 KiB; tres ControlNodes, tres miembros etcd y tres DataNodes. R3/W2 de datos y mayoría 2/3 de metadatos son conceptos distintos. Fallos de procesos en un host Windows.

SHA-256 inicial: `c047731a3c134f3d34286d608e9c173027d50f43ab9d2064f3c360939977e908`.
SHA-256 después del parche: `33dd21353ac79226f9ea36aa5bf30804a4226533bdc6fcd626ebd0e0661abe9d`.

| Evento | Segundos |
| --- | ---: |
| Inicio de send hasta commit | 157.500 |
| Inicio del parche de 4096 bytes hasta commit | 27.703 |
| Solicitud de parada del control hasta lectura del mismo handle | 21.157 |

La última duración incluye parada, conmutación y autorización/lectura; no mide solo detección. El SDK exige W2 antes del commit y la prueba espera/verifica R3 por versión.

## Distribución y tráfico

| node_id | Primarios | Cliente a DN | DN a cliente |
| --- | ---: | ---: | ---: |
| 26b8150d-4b71-40cf-bd42-fbd69cacfb7d | 3 | 201326592 | 201326592 |
| bbee4bdc-4a16-4c4f-a124-678c03a50506 | 3 | 201326592 | 201326592 |
| fb2e3c49-8ad7-47ce-991c-025b55e68cc2 | 2 | 134217728 | 134217728 |

Primera subida y descarga: bytes útiles del SDK. Acumulado completo del escenario:

| node_id | Cliente a DN | DN a cliente | S/S enviado | S/S recibido |
| --- | ---: | ---: | ---: | ---: |
| 26b8150d-4b71-40cf-bd42-fbd69cacfb7d | 201330688 | 402657280 | 536915160 | 335571975 |
| bbee4bdc-4a16-4c4f-a124-678c03a50506 | 201326592 | 402653184 | 402686370 | 402686370 |
| fb2e3c49-8ad7-47ce-991c-025b55e68cc2 | 134217728 | 268435456 | 268457580 | 469800765 |

Parche aislado: **4096 bytes cliente a DN**, 0 DN a cliente y **134228790 bytes S/S** (dos objetos cifrados de 67114395 bytes). Procesamiento interno: base 268435456, resultado 134217728 bytes; nuevo objeto almacenado 67114395 bytes antes de sus réplicas.

**Contenido del archivo por controles: 0 bytes.** Control sin BlockStore de contenido y SDK directo a DataNodes. No significa cero tráfico de red. S/S incluye ciphertext/cabeceras; no sumar emisor y receptor como dos transferencias.

| Control | TLS hacia etcd | TLS desde etcd |
| --- | ---: | ---: |
| 0 | 3824349 | 1881725 |
| 1 | 1301114 | 2560425 |
| 2 | 219287 | 371339 |

Contadores de proxies TCP; incluyen overhead TLS, no todo el C/S de metadatos ni los peers etcd.

## Copias verificadas por versión

| Estado | Índice | block_version_id | Confirmadas | Elegibles | Nodos / dominios |
| --- | ---: | --- | ---: | ---: | --- |
| Antes | 0 | 0b0328a8-ea5d-4b4c-8c8e-08d725438988 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Antes | 1 | 6608ec83-0b79-45be-a675-99a3eac88592 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Antes | 2 | 12408f26-24d8-4ea9-b80a-28ad1e9957d2 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Antes | 3 | b24cd2dc-2a08-4af9-b917-c24ced1e9a56 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Antes | 4 | 91d4ae83-e9b8-48f2-984d-942fb02a47e4 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Antes | 5 | ffe9a64f-c2d9-4f0a-89a8-a300a46090ce | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Antes | 6 | 0f6a2738-82b5-48fc-972c-1fa7c4c63d03 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Antes | 7 | d5946740-9fb8-4ec6-ab5b-bc7965fc5f03 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Después | 0 | 1346aa84-370d-4b8c-95e5-f62b03b57cc0 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Después | 1 | 6608ec83-0b79-45be-a675-99a3eac88592 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Después | 2 | 12408f26-24d8-4ea9-b80a-28ad1e9957d2 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Después | 3 | b24cd2dc-2a08-4af9-b917-c24ced1e9a56 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Después | 4 | 91d4ae83-e9b8-48f2-984d-942fb02a47e4 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Después | 5 | ffe9a64f-c2d9-4f0a-89a8-a300a46090ce | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Después | 6 | 0f6a2738-82b5-48fc-972c-1fa7c4c63d03 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |
| Después | 7 | d5946740-9fb8-4ec6-ab5b-bc7965fc5f03 | 3 | 3 | 26b8150d-4b71-40cf-bd42-fbd69cacfb7d / process-26b8150d-4b71-40cf-bd42-fbd69cacfb7d, bbee4bdc-4a16-4c4f-a124-678c03a50506 / process-bbee4bdc-4a16-4c4f-a124-678c03a50506, fb2e3c49-8ad7-47ce-991c-025b55e68cc2 / process-fb2e3c49-8ad7-47ce-991c-025b55e68cc2 |

El JSON conserva recibos, generaciones, longitudes, hashes plaintext/ciphertext y salud. Los dominios process-* no acreditan hosts independientes.

## Memoria y miembros etcd

| Rol | Pico residente (MiB) |
| --- | ---: |
| Control 0 | 65.61 |
| Control 1 | 51.80 |
| Control 2 | 45.46 |
| DataNode 0 | 56.02 |
| DataNode 1 | 56.85 |
| DataNode 2 | 56.96 |
| etcd 0 | 64.10 |
| etcd 1 | 67.20 |
| etcd 2 | 61.35 |
| Cliente y supervisor de proxies | 65.42 |

PeakWorkingSet del PID real hasta la muestra: controles antes de detener uno; DataNodes y cliente al final. No extrapolar a otros perfiles/cargas.

| Miembro | Clúster | Líder observado |
| --- | --- | --- |
| 5290404113490850435 | 1753457960808250860 | 12294821319448573120 |
| 12294821319448573120 | 1753457960808250860 | 12294821319448573120 |
| 6281884205972509296 | 1753457960808250860 | 12294821319448573120 |

MemberList/Status consultados con mTLS; misma membresía de tres nodos.

```powershell
.\.venv-win\Scripts\python.exe scripts/measure_stage7.py --evidence docs/evidencias/etapa7/measurement-repeat.json
```
