# Evidencias E4

Estado del cierre: **ETAPA 4 COMPLETA en Windows local**, 2026-09-10. No contabilizar como aprobado un caso por existir en tests o por estar descrito aquí.

- [Regresión final](20260910T225730Z/result.json): **100 aprobadas**, cero fallos/errores/omitidas, 403,78 s; [XML](20260910T225730Z/pytest.xml), 34 imports, [auditoría](20260910T225730Z/audit.json).
- [Medición final](20260910T225730Z/measurement.json): 512 MiB + dos clientes de 128 MiB+1; perfil 64 MiB, chunks 256 KiB; máximo cliente 56,2 MiB, control 82,1 MiB, DN 56,5 MiB. Metas cumplidas en esa ejecución, no extrapoladas.
- [Wheel/imports](package.json) y [smoke desde paquete instalado](installed-smoke.json): 8 MiB distribuidos en dos DN, SHA idéntico; arranque, status, cuarto nodo y parada reales.
- [Regresión anterior](20260910T011917Z/result.json): 99 aprobadas. [Casos adicionales previos al cierre](supplemental.xml): dos aprobados, luego incluidos en la regresión final.
- [Publicación Git](git-publicacion.json): implementación E4 `48509a6` publicada y hash remoto comprobado; el registro se incorpora en el cierre documental posterior.

## Archivo principal de la medición final

536870912 B, ocho bloques de 67108864 B, roundtrip 52,515 s con otros dos clientes activos. SHA-256 de entrada y salida: `2bd23440f228060ff27d371cbfad66b6eb83b03ecbb5df0ea50c05e58270c715`.

| node_id | Bloques del archivo | C→DN (B) | DN→C (B) | S/S enviado/recibido (B) |
|---|---:|---:|---:|---:|
| d0c7fbe3-ca1c-4485-85be-ad4696304b2e | 2 | 134217728 | 134217728 | 0 / 0 |
| 8b331b58-65bb-4a17-b9cc-4f34ecf9c562 | 4 | 268435456 | 268435456 | 0 / 0 |
| 61460be4-63c4-4dbd-b4ee-c3cb58a96d59 | 2 | 134217728 | 134217728 | 0 / 0 |

Esta tabla usa los contadores del cliente del archivo principal. Los contadores globales DN del JSON incluyen también los otros clientes. CN transportó metadatos, **cero contenido**; se comprobó rechazo UNIMPLEMENTED de GetBlock en su endpoint y ausencia de objetos de datos allí. No se capturaron paquetes ni se afirma cero tráfico de red.

## Copia S/S en laboratorio separado

En el XML final, propiedad `copy_evidence` de `test_distribution_roundtrip_copy_restart`: tarea `23694489-99e6-4789-bc38-804289b4cb43`, ciphertext de **4195034 B**, SHA `55e592f3338078d2c7d71b60f3bbe2a42ed58b7c66d2beeca666a86c69902938`. El plaintext del bloque tiene 4194304 B y SHA `2b07811057df887086f06a67edc6ebf911de8b6741156e7a2eb1416a4b8b1b2e`.

| node_id | C→DN (B) | DN→C (B) | DN→DN enviado (B) | DN→DN recibido (B) |
|---|---:|---:|---:|---:|
| b2f0570d-fd61-49f6-8633-2691c2616daf (origen) | 4194305 | 8388609 | 4195034 | 0 |
| f93431b7-844d-4abd-add8-fd2514ea6e38 (destino) | 4194304 | 12582912 | 0 | 4195034 |
| c282a274-e4fc-4fa8-bb36-087e74420da5 | 4194304 | 8388608 | 0 | 0 |

Los contadores son el muestreo de heartbeats incluido en esa prueba, no el del archivo de 512 MiB. Enviado y recibido describen la misma copia, no dos transferencias a sumar. Se leyó desde el destino con el origen detenido; luego se reinició destino y se recuperó su recibo. No acredita HA de todos los bloques ni reparación automática.

Punto de partida comprobado: main/origin d91e2ba; df1fd33 y 7bd8327 conservados. Antes de adaptar H1 se ejecutó [verify_stage3 --measure](../etapa3/20260910T004040Z/resultado.json): 87 pruebas en 139,08 s y roundtrip 1 GiB/3 clientes. [Medición de esa ejecución](../etapa3/20260910T004040Z/medicion.json). El contrato nodes.proto se editó aditivamente mientras concluía esa medición; sus stubs se regeneraron después, por lo que no cambió el runtime de H1 medido.

Pruebas de desarrollo E4 anteriores al cierre: smoke inicial 1 aprobado; ampliación 6 aprobadas y 1 fallo por expectativa demasiado estrecha del rechazo TLS; repetición seguridad aprobada. Una prueba de reinicio detectó que el harness aceptaba READY de la generación anterior; se corrigió y el caso pasó. Estos intentos no sustituyen la regresión fechada final.

`verify_stage4.py --measure` guarda por ejecución `result.json`, `pytest.xml`, `audit.json` y `measurement.json`. Los JSON contienen comandos/exit codes/versiones/hashes; XML los casos ejecutados. `package.json` se produce mediante comprobación del wheel en venv limpio. Los logs privados, certificados, claves y archivos grandes se conservan únicamente en runtime ignorado; no forman parte de evidencia publicable.

La tabla por nodo de `measurement.json` distingue cliente→DN, DN→cliente, entrada y salida S/S; los contadores del worker 0 atribuyen bytes al mismo archivo grande, mientras los contadores del DN incluyen los tres clientes. Cero contenido en el control se acredita con rutas de transporte, ausencia de BlockService implementado allí y ausencia de objetos en su raíz, no con afirmar que el control tiene cero tráfico de red.

Pendientes por entorno/alcance: Linux/WSL/Docker e Internet/cloud; dominios de fallo físicos; HA y mayorías etcd; replicación y reparación automáticas; protección integral de SQLite/WAL/backups; benchmarks amplios. Ninguno se cuenta como aprobado por pruebas locales.
