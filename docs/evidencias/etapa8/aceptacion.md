# E8 — correspondencia entre criterios y comprobaciones

Este inventario no suma repeticiones como casos distintos. El [cierre](cierre.md)
reúne 177 casos Windows mediante ejecuciones identificadas. La selección final
`20261001T034229Z-9d313040` aprobó 36 E7/E8 y la medición de 512 MiB; cada comando
tiene exit 0 persistido. Linux `20261001T034403Z-581a2df8` aprobó esos 36 casos
con exit 0 del contenedor. Los intentos fallidos/interrumpidos se conservan.

| Criterio / requisito | Implementación | Caso observable |
| --- | --- | --- |
| RNF6 autenticación, administración y grupos | IdentityService, Commands, SDK/CLI; Argon2id | `test_groups_shared_revocation_password_and_prepared_commit`: usuario ajeno rechazado, grupo lector, recorrido permitido sin listado, administración ajena denegada |
| Revocación compartida | Sesión y revisión de ACL autoritativas etcd | Mismo caso: quitar grupo impide leer snapshot; cambio de contraseña y disable revocan; enable no revive sesión; commit con W2 preparado y ACL revocada se rechaza |
| Caducidad y logout | Sesión opaca; plazo del control y lease | Caso anterior reduce plazo de fixture y espera tiempo real por otro CN; `test_ordinary_cli_ha_uses_encrypted_session_and_logout` comprueba logout y archivo cifrado |
| Autorización de bloques | AuthorizeBlock y AuthorizeInternal, permiso por sesión/rango/destino | `test_scoped_capabilities_write_only_and_revoked_lease`: permiso alterado, rango diferente, sesión ajena/ausente, otro DN, resultado ajeno y lease revocado rechazados |
| Parche solo escritura | PatchBlock COW con base dentro de DN | Caso anterior: delta de 3 bytes, cero lectura de base al cliente, bytes restantes preservados; medición de 4096 bytes separa tráfico S/S |
| Roles e identidades internas | mTLS, identidad ligada a node_id, política administrativa compartida | Regresiones H2/E6 de recibos/roles; `test_rotation_snapshots_and_revoked_node_existing_channel` rechaza registro por el mismo canal tras retirar autorización |
| TLS y certificados | CA/SAN, hojas distintas y peers con CN permitido | Transporte histórico conserva negativas CA/SAN/sin certificado; E8 rechaza hoja vencida antes del handler, rota hojas CN/DN/etcd y conserva acceso |
| etcd RBAC | Autenticación habilitada, roles de prefijo, root separado | `test_protected_etcd_rbac_peer_roles_and_auxiliary_scope`: Put fuera de prefijo o por DN falla y clave sigue ausente; sin certificado falla; DN rechazado como peer |
| RNF6 datos, metadatos e inventarios | DFSHAB01 y MetadataCipher, claves por propósito | `test_metadata_cipher_rejects_tamper_wrong_key_and_identity`, SQLite/WAL cifrado y `test_protected_metadata_real_ha`; no basta la búsqueda auxiliar de cadenas |
| Integridad, rutas y recuperación de copia | Autenticación completa antes de plaintext; confinamiento tras resolve | Regresiones corrupción/lectura alternativa/reparación E6 y `test_block_path_race.py`, incluidos junction de lectura/escritura y de GC |
| Custodia y rotación | GetKeyStatus mTLS, provisión→carga→activación, versiones inmutables | `test_rotation_snapshots_and_revoked_node_existing_channel`: activación prematura rechazada, tres nodos cargados, lectura vieja/nueva y recuperación sin origen |
| Retirada segura de claves | Guard offline conservador; no borra claves | Mismo caso rechaza retirada con backup retenido y conserva los bytes de las claves; inventario de objetos mantiene claves antiguas |
| Backup cifrado y restauración | Archivo AEAD con manifiesto autenticado y clave externa | `test_backup_requires_key_and_recovers_independent_environment`, `test_protected_ha_backup_and_restore`: clave ajena no crea destino; corrupción no publica marcador; restauración conserva bytes, propietario y contraseña |
| Límites y auditoría | Admisión compartida, slots Argon2, cuotas, logs permitidos/rotativos | `test_argon2_bounded_concurrency_and_effective_parameters`, `test_audit_rejects_secrets_and_rotates`, `test_native_output_is_drained_and_retention_bounded` |
| Retención administrativa segura | Backup offline, barrera etcd, eliminación por raíz y lotes | `test_offline_retention_keeps_live_snapshot_and_replay_results`: rechazo en activo/digest incorrecto; conserva snapshot y resultados después de recoger páginas |
| RNF2/RNF3/RF3 sin degradación | Autoridad compartida, leases/fencing, R3/W2 | Regresiones E5/E6/E7: escritores disjuntos, estado incierto, partición por proxy, pérdida de mayoría, relevo/GC, migración/restauración |
| Recursos y recorrido de datos | Streaming acotado, control solo metadatos | [Medición 512 MiB](medicion-protegida.md): hashes, ocho bloques con tres copias, 4 KiB de delta, memoria por rol, cero contenido por CN |
| Barrera con liberación incierta | D64, lease descartado sin liberar propietario ajeno | `test_failed_cleanup_discards_cached_gate_lease`: partición real, registro abortado ausente, nueva adquisición/publicación verificadas |
| Bootstrap privado y reanudación | Contraseña por entrada protegida, sin persistirla en configuración | `test_private_bootstrap_and_resume_after_admin_password_change`: rechaza contraseña de fixture, cambia contraseña, reinicia y conserva identidad/datos |

Los rechazos comprueban códigos concretos y efectos relevantes: ausencia de la
clave/entrada prohibida, snapshot anterior conservado, cero bytes de base,
ausencia de destino/marcador de restauración o contenido intacto tras la negativa.
Los tests criptográficos aislados no se presentan como evidencia de red.

Límites permanentes: un host, sin Internet; administrador del host fuera del
modelo de confidencialidad; sin resistencia bizantina ni CRL declarada; estructura
opaca/tamaños y métricas visibles según el alcance documentado. Los resultados
idempotentes/tombstones no expiran por edad; la compactación MVCC y la retirada
física automatizada de claves quedan como administración futura, sin saltarse
las guardas. Q03 y Q05 continúan sin respuesta docente.
