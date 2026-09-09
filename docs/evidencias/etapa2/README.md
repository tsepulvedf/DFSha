# Evidencias de etapa 2

2026-09-08. **EJECUTADO:** verificación final local con 70 pruebas aprobadas, cero fallos/errores/omitidos, más reinstalación de dependencias y generación/importación desde un wheel en entorno limpio. Ruta Windows Python 3.12.10 y etcd 3.6.14. Ningún resultado acredita RF1/RF2/RF3 funcionales, HA, consenso distribuido, rendimiento del DFS ni cloud.

## Ejecución final

Comando PowerShell, cwd `F:\DFSha`:

```powershell
.\.venv-win\Scripts\python.exe scripts/verify_stage2.py --clean-env
```

| Artefacto | Qué registra |
| --- | --- |
| [resultado.json](20260908T212227145653Z/resultado.json) | Estado EJECUTADO; argv/cwd/códigos/salidas/timings, Python/plataforma/SQLite/paquetes y SHA-256 del código/configuración probados. Todos los subcomandos terminaron con código 0. |
| [pytest.xml](20260908T212227145653Z/pytest.xml) | 70 casos, 24.65 s de suite, sin errores/fallos/skip. Tiempo de ejecución de tests, no benchmark del DFS. |
| [contratos.json](20260908T212227145653Z/contratos.json) | Regeneración byte a byte y 34 módulos importados; hashes de módulos generados propios/oficiales. |
| [etcd-cleanup.json](20260908T212227145653Z/etcd-cleanup.json) | Prefijo único de prueba, cero claves restantes y usuarios/rol del probe eliminados. |
| [server-events.json](20260908T212227145653Z/server-events.json) | Solo eventos estructurados con campos permitidos, listeners y último evento stopped. No contraseñas/tokens/claves. |
| [manual](manual-20260908T212226Z.json) | Comandos exactos generate_certs, dev start, cliente público, cliente mTLS y dev stop; respuestas verificadas y cierre observado. |
| [entorno-git.json](entorno-git.json) | Inspección de herramientas/rutas/servicios, versiones Python/etcd/Git, remotos, main sin commits, lectura de refs y API GitHub real. |
| [auditoria-documental.json](auditoria-documental.json) | Auditoría final de catálogo/filas/enlaces/documentos y hashes de fuentes. Resultado documental separado de pytest. |
| [revision-publicable.json](revision-publicable.json) | Archivos candidatos a Git sin entornos/datos/claves privadas; UTF-8, cierres de bloques de código y columnas de tablas comprobados. Es revisión local, no publicación. |
| [preservacion-etapa1.json](preservacion-etapa1.json) | Los cinco documentos archivados de E1 coinciden con los hashes de su auditoría original. PDF/guía también comprobados por auditoría documental. |

En resultado.json también constan pip check sin conflictos, instalación `--require-hashes` en `.venv-verify-20260908T212227145653Z`, build/instalación wheel sin dependencias implícitas, generación con `--check` desde ese entorno y `python -I scripts/check_imports.py --require-installed`. Los 34 imports proceden de `Lib/site-packages/dfsha` del entorno nuevo; no de editable/PYTHONPATH. El wheel incluye las cuatro licencias de terceros. Las fuentes .proto oficiales y sus licencias se comprobaron por hashes, sin editar código generado.

## Correspondencia entre casos y alcance

| Casos | Resultado observado | Lo que acredita |
| --- | --- | --- |
| Cliente separado, público/interno (2) | 8.388.625 B enviados y recibidos por listener; SHA-256 contra fixture independiente, chunks máximos 262.144 B. | gRPC TLS/mTLS y streaming incremental bidireccional mediante dos RPC; no almacenamiento de archivos. |
| TLS negativos (4) | CA no confiable, cliente ausente, cliente de CA ajena y SAN incorrecto rechazados con UNAVAILABLE. | Verificación TLS real; no basta un timeout genérico para dar estos casos por aprobados. |
| Streams/tamaño/plazo (7) | Encabezado ausente, offset incorrecto, chunk excesivo, checksum errado, stream corto, mensaje >1 MiB y deadline se rechazan. | Validaciones del diagnóstico/límite gRPC, errores estables donde aplica y cancelación. |
| Contratos futuros (47) | Cada RPC responde UNIMPLEMENTED / NOT_IMPLEMENTED_STAGE2. | No existen éxitos ficticios; cobertura del registro de interfaces futuras. |
| Seguridad de bibliotecas (2) | AES-GCM roundtrip; ciphertext/AAD alterados fallan; Argon2id correcto verifica, incorrecto falla. | Compatibilidad de dependencias, no RNF6 integral. |
| etcd real (6) | Put/Get; CAS acepta y luego rechaza revisión obsoleta; lease TTL=1 expiró observado en 2.5 s; Lock/Unlock y Txn con dueño viejo rechazada; Watch con revisión de Put; AuthStatus activo, RBAC deniega usuario/rango y TLS deniega clientes; proceso detenido genera error controlado. | Acceso Python API v3 con autenticación/autorización y coordinación básica. No clúster ni MetadataStore definitivo. |
| SQLite (1) | Dato sobrevive reapertura; transacción fallida revierte cambio previo. | Capacidad de persistencia local para preparar H1, independiente de etcd. |
| Tamaños de contratos (1) | Página de 64 bloques: 8399 B; CommitWrite de cinco cambios y tres recibos por cambio: 7701 B. | Margen wire del fixture bajo 64 KiB/1 MiB; no demuestra número de operaciones del futuro Txn distribuido. |

Indisponibilidad de etcd: tras detener la instancia auxiliar propia, gRPC devolvió `DEADLINE_EXCEEDED` dentro del plazo de 2 s; wrapper produjo `{status:FALLIDO,code:DEADLINE_EXCEEDED,reason:DEADLINE_EXCEEDED}`. El caso **pasa por observar el error esperado**; no significa que el servicio detenido respondió correctamente. El contrato admite también UNAVAILABLE cuando el transporte detecta antes el fallo.

La fixture elimina solo su prefijo, revoca leases creados y elimina usuarios/rol de prueba. WAL/CA/logs efímeros se conservan localmente ignorados para inspección; root de bootstrap permanece en el WAL propio sin servidor activo. No se limpiaron recursos de un servicio compartido ni se ejecutó un borrado global de claves. Los procesos de diagnóstico cierran ordenadamente; terminate de etcd Windows no se presenta como prueba de cierre graceful o durabilidad frente a caída.

## Historial conservado, no sumar fallos como aprobados

| Archivo/ejecución | Estado histórico y resolución |
| --- | --- |
| [transporte-inicial.xml](transporte-inicial.xml) | **FALLIDO:** 59 pasaron, 3 fallaron por esperar UNAVAILABLE cuando localhost agotaba deadline durante intentos de conexión. Corregido usando IPv4 con SAN válido para esos negativos; no se desactivó TLS. |
| [etcd-inicial.xml](etcd-inicial.xml) | **FALLIDO:** 4 pasaron, 2 fallaron por la misma expectativa de transporte. Datos/CAS/lease/lock/Watch ya funcionaban; no se contaron las negativas como aprobadas. |
| [negativas-corregidas.xml](negativas-corregidas.xml) | **Iteración intermedia FALLIDA:** 5 pasaron, quedó 1 de indisponibilidad. Se precisó el contrato UNAVAILABLE/DEADLINE_EXCEEDED acotado; negativas de certificados permanecen estrictas. |
| [primera suite completa](20260908T194904553251Z/resultado.json) | **EJECUTADO:** 69 casos y wheel limpio; antecede refinamientos finales de campos/paquetización y caso de tamaños. Conservar sus hashes como versión histórica. |
| [contratos iniciales](contratos.json) | Generación/importación inicial exitosa; hashes anteriores a la revisión final, no sustituye contratos.json del último run. |

Otros comandos ejecutados en la preparación, registrados aquí como bitácora sin inventar una captura de salida que no se guardó: `git init --initial-branch=main`, `git remote add origin https://github.com/tsepulvedf/DFSha.git`, configuración branch.main.remote/merge; `python -m piptools compile --extra dev --allow-unsafe --generate-hashes --strip-extras --output-file requirements.lock pyproject.toml`; después `python scripts/lock_dependencies.py`; `python scripts/vendor_etcd.py --refresh`, `python scripts/fetch_etcd.py`; finalmente `powershell -NoProfile -File scripts/bootstrap.ps1` con código 0. Python corresponde a `.venv-win\Scripts\python.exe` en esos comandos. Los subcomandos de verificación final sí tienen stdout/stderr conservados.

Auditoría auxiliar local: `.\.venv-win\Scripts\python.exe .runtime/review_stage2.py` terminó con código 0; comprobó exclusiones, formato, ZIP original y coincidencia de los **99 archivos** de código/configuración con los hashes de la suite final. Ese script temporal queda fuera de Git; la auditoría reproducible entregada es `scripts/audit_stage2.py`. Los intentos auxiliares iniciales `node -e`/`python -c` fallaron por citado de PowerShell antes de validar archivos; se resolvió ejecutando desde archivo, sin atribuirles éxito.

**Limitaciones:** Linux/WSL/Docker no ejecutados, no CI remota ni código sincronizado en GitHub, sin VMs académicas/provisión, RF1/RF2/RF3 no implementados, sin réplica/HA/consenso o pruebas de mayoría. Q01–Q07 siguen pendientes. La memoria de aplicación se acota por diseño de iteradores/tamaños observados; no se midió RSS. No hay resultados para metas 1 GiB/10 clientes/crecimiento de namespace.
