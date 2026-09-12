# Medición E6: datos observados

Fuente: [measurement-final.json](measurement-final.json), 2026-09-12T19:23:04.733735+00:00.

536870912 bytes, bloques de 67108864 bytes, fragmentos de 262144; R=3/W=2.
Un host Windows; fallos de procesos. Una sesión SDK para esta medición; concurrencia en pruebas separadas.

SHA-256 original/descarga: `c047731a3c134f3d34286d608e9c173027d50f43ab9d2064f3c360939977e908`.
SHA-256 esperado tras parche/descarga reparada: `22c45085d585834221e85ede577e023e62d42d8ace4682feb7a09d6e69136250`.

## Tráfico inicial: put, tercera copia y get

C→DN y DN→C son bytes útiles. S/S son bytes de objetos cifrados, con formato y tags, sin overhead TLS/TCP.
No sumar envío y recepción S/S como si fueran copias diferentes. Se excluyen aquí parche y reparación posterior.

| node_id / dominio administrativo | C→DN | DN→C | S/S enviado | S/S recibido |
| --- | ---: | ---: | ---: | ---: |
| b2174a7e-628c-494c-a828-e3e5ca62f618 / process-b2174a7e-628c-494c-a828-e3e5ca62f618 | 134217728 | 201326592 | 268457580 | 402686370 |
| 3caf63bb-25e0-455b-b574-a4ae7d532098 / process-3caf63bb-25e0-455b-b574-a4ae7d532098 | 201326592 | 201326592 | 402686370 | 335571975 |
| eb43f1df-4051-4cae-82d3-5d4a20793377 / process-eb43f1df-4051-4cae-82d3-5d4a20793377 | 201326592 | 134217728 | 402686370 | 335571975 |

Contenido de archivo por control: **0 bytes**. El control sí intercambia metadatos.

## Parche de 4096 bytes

| node_id | C→DN | DN→C | S/S enviado | S/S recibido | base procesada | resultado procesado | nuevo objeto cifrado local |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| b2174a7e-628c-494c-a828-e3e5ca62f618 | 0 | 0 | 0 | 67114395 | 0 | 0 | 0 |
| 3caf63bb-25e0-455b-b574-a4ae7d532098 | 4096 | 0 | 134228790 | 0 | 268435456 | 134217728 | 67114395 |
| eb43f1df-4051-4cae-82d3-5d4a20793377 | 0 | 0 | 0 | 67114395 | 0 | 0 | 0 |

El coste interno incluye pasadas de autenticación/COW; no equivale a bytes enviados por el cliente.
La lectura de validación se ejecuta después de cerrar esta ventana de contadores.

## Copias por bloque y fase

Antes corresponde al archivo original; degradado/reparado al archivo después del parche (cambia solo la versión del primer bloque).
C es historial de confirmaciones; E son copias actualmente elegibles. Una copia no elegible se marca con ×.
Las identidades abreviadas se resuelven en la tabla anterior o en el JSON; cada dominio es process-node_id.

| Fase | Índice | block_version_id | R | C | E | Nodos (elegibilidad) | tareas pendientes |
| --- | ---: | --- | ---: | ---: | ---: | --- | ---: |
| antes | 0 | 552e84c1-72e8-4b2d-a3cc-2dfe8e7a4416 | 3 | 3 | 3 | 3caf63bb, b2174a7e, eb43f1df | 0 |
| antes | 1 | 9a9a8376-ea29-4ba3-99a0-fb1254468fe0 | 3 | 3 | 3 | 3caf63bb, b2174a7e, eb43f1df | 0 |
| antes | 2 | 9db63804-cca6-46e9-89ee-720c33e96b3c | 3 | 3 | 3 | 3caf63bb, b2174a7e, eb43f1df | 0 |
| antes | 3 | 46385862-1fb6-4fb4-b5ea-17be819fdfe0 | 3 | 3 | 3 | 3caf63bb, b2174a7e, eb43f1df | 0 |
| antes | 4 | 66a057f6-e250-4d18-b67c-71a018fb639d | 3 | 3 | 3 | 3caf63bb, b2174a7e, eb43f1df | 0 |
| antes | 5 | 0ee62deb-b6dd-441d-9be9-df57caf63643 | 3 | 3 | 3 | 3caf63bb, b2174a7e, eb43f1df | 0 |
| antes | 6 | 65490800-9db4-4ff3-8bec-210b336e890d | 3 | 3 | 3 | 3caf63bb, b2174a7e, eb43f1df | 0 |
| antes | 7 | a645ec92-53bf-4eae-8eaa-2dd86119f263 | 3 | 3 | 3 | 3caf63bb, b2174a7e, eb43f1df | 0 |
| caído | 0 | de4ac525-ef5c-4797-8eb1-336d10b6f8a5 | 3 | 3 | 2 | 3caf63bb, b2174a7e ×, eb43f1df | 0 |
| caído | 1 | 9a9a8376-ea29-4ba3-99a0-fb1254468fe0 | 3 | 3 | 2 | 3caf63bb, b2174a7e ×, eb43f1df | 0 |
| caído | 2 | 9db63804-cca6-46e9-89ee-720c33e96b3c | 3 | 3 | 2 | 3caf63bb, b2174a7e ×, eb43f1df | 0 |
| caído | 3 | 46385862-1fb6-4fb4-b5ea-17be819fdfe0 | 3 | 3 | 2 | 3caf63bb, b2174a7e ×, eb43f1df | 0 |
| caído | 4 | 66a057f6-e250-4d18-b67c-71a018fb639d | 3 | 3 | 2 | 3caf63bb, b2174a7e ×, eb43f1df | 0 |
| caído | 5 | 0ee62deb-b6dd-441d-9be9-df57caf63643 | 3 | 3 | 2 | 3caf63bb, b2174a7e ×, eb43f1df | 0 |
| caído | 6 | 65490800-9db4-4ff3-8bec-210b336e890d | 3 | 3 | 2 | 3caf63bb, b2174a7e ×, eb43f1df | 0 |
| caído | 7 | a645ec92-53bf-4eae-8eaa-2dd86119f263 | 3 | 3 | 2 | 3caf63bb, b2174a7e ×, eb43f1df | 0 |
| reparado | 0 | de4ac525-ef5c-4797-8eb1-336d10b6f8a5 | 3 | 4 | 3 | 3caf63bb, 7d505fb2, b2174a7e ×, eb43f1df | 0 |
| reparado | 1 | 9a9a8376-ea29-4ba3-99a0-fb1254468fe0 | 3 | 4 | 3 | 3caf63bb, 7d505fb2, b2174a7e ×, eb43f1df | 0 |
| reparado | 2 | 9db63804-cca6-46e9-89ee-720c33e96b3c | 3 | 4 | 3 | 3caf63bb, 7d505fb2, b2174a7e ×, eb43f1df | 0 |
| reparado | 3 | 46385862-1fb6-4fb4-b5ea-17be819fdfe0 | 3 | 4 | 3 | 3caf63bb, 7d505fb2, b2174a7e ×, eb43f1df | 0 |
| reparado | 4 | 66a057f6-e250-4d18-b67c-71a018fb639d | 3 | 4 | 3 | 3caf63bb, 7d505fb2, b2174a7e ×, eb43f1df | 0 |
| reparado | 5 | 0ee62deb-b6dd-441d-9be9-df57caf63643 | 3 | 4 | 3 | 3caf63bb, 7d505fb2, b2174a7e ×, eb43f1df | 0 |
| reparado | 6 | 65490800-9db4-4ff3-8bec-210b336e890d | 3 | 4 | 3 | 3caf63bb, 7d505fb2, b2174a7e ×, eb43f1df | 0 |
| reparado | 7 | a645ec92-53bf-4eae-8eaa-2dd86119f263 | 3 | 4 | 3 | 3caf63bb, 7d505fb2, b2174a7e ×, eb43f1df | 0 |

## Tiempos y memoria

| Medición | Segundos |
| --- | ---: |
| upload_seconds | 57.844 |
| download_seconds | 14.969 |
| patch_commit_seconds | 8.828 |
| detect_seconds_from_stop | 6.047 |
| alternate_seconds_from_open | 0.828 |
| repair_seconds_from_fourth_start | 37.187 |

Windows PeakWorkingSetSize del PID anunciado por el proceso servidor; no del lanzador venv. Máximo desde el arranque.
El nodo detenido se mide antes de su salida; los demás al finalizar. No son máximos de todos los perfiles.

| Proceso / node_id | PID real | Máximo residente MiB |
| --- | ---: | ---: |
| cliente | 5320 | 63.02 |
| control | 12436 | 63.11 |
| b2174a7e-628c-494c-a828-e3e5ca62f618 | 25872 | 56.03 |
| 3caf63bb-25e0-455b-b574-a4ae7d532098 | 25064 | 56.23 |
| eb43f1df-4051-4cae-82d3-5d4a20793377 | 23376 | 56.05 |
| 7d505fb2-8efc-4ba6-8796-d60faaa844d4 | 25820 | 52.57 |
