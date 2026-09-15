# Correspondencia de aceptación E7

Esta tabla identifica casos, no suma ejecuciones repetidas. El resultado final
de la suite y la comprobación adicional se registran en el [inventario](README.md).
La topología acreditada es de procesos independientes en un único host Windows.

| Criterio | Prueba o evidencia concreta |
| --- | --- |
| Un clúster etcd de tres miembros; tres controles activos | `test_cross_control_session_handle_and_data`, MemberList/Status en [medición](measurement-fixed.json) |
| Autoridad compartida; sesiones y handles entre controles | `test_cross_control_session_handle_and_data`; usuario ordinario en `test_shared_user_revocation_and_open_truncate_gc` |
| Páginas preparadas y publicación atómica; error antes de publicar | `test_paged_atomic_metadata_and_quorum`; `test_control_failover_network_partition_and_quorum` |
| Preparaciones simultáneas y mezcla de bloques distintos | `test_cross_control_parallel_publication_and_lost_reply`: barrera antes de PatchBlock, W2 en ambas operaciones antes de commits, resultado A1/B1 |
| Solapamiento y serialización del mismo handle entre controles | Conflicto de locks en el caso paralelo; BeginWrite/Close desde otro control con operación activa en el caso de autorización |
| Fencing vigente dentro de Txn, sin revivir leases | `test_shared_lease_expiry_and_publication_fence`; `test_expired_writer_with_two_copies_cannot_publish` |
| Respuesta perdida e idempotencia desde otro control | `test_cross_control_parallel_publication_and_lost_reply`; resultado y replay idéntico recuperados desde CN2 |
| Caída antes del commit; continuidad de lectura y escritura parcial | Caso failover, caso de handle compartido y [medición de 512 MiB](medicion.md) |
| Reinicio individual sin cambiar época global | `test_control_failover_network_partition_and_quorum` |
| Caída conjunta de un CN y líder etcd | `test_control_failover_network_partition_and_quorum`, lectura mediante procesos restantes |
| Pérdida de mayoría y recuperación sin publicación minoritaria | Caso failover: Stat/Mkdir fallan dentro del deadline; nombre ausente tras recuperar mayoría. Caso del adaptador comprueba raíz inalterada |
| Partición TCP real sin detener el control; retorno obsoleto | Proxies de todos los endpoints etcd de CN0, resto continúa; `test_partition_one_authority_client_without_stopping_etcd` comprueba además rechazo de mutación aislada |
| Reservas atómicas entre controles | `test_cross_control_capacity_reservations_are_atomic`, dos asignaciones concurrentes, cuota de 6 MiB por nodo, rechazo y liberación tras aborto |
| Relevo de mantenimiento; callback viejo rechazado | `test_maintenance_takeover_rejects_old_callback_and_preserves_snapshot`, lease/generación compartidos y ReportTask mTLS real |
| GC y referencias entre controles | Caso de mantenimiento conserva lector tras rm; caso de autorización inicia open/truncate mediante barrera y comprueba snapshot y retirada posterior |
| Watch desconectado y compactado | `test_watch_disconnect_and_compaction_rebuild`, reconstrucción consistente; Watch no decide autoridad |
| Reinicio de todo el conjunto con volúmenes | `test_restart_entire_lab_preserves_epoch_and_unexpired_handle`; no implica supervivencia tras expiración real |
| Migración E6 y respaldo/restauración del DFS | `test_e6_migration_and_full_backup_restore`, contenido actual, snapshot anterior retenido, identidad, resultado y nueva época; `test_etcd_snapshot_restore_new_cluster` comprueba nueva membresía/revisión |
| Autorización compartida y denegación por defecto | Caso de usuario ordinario, permisos revocados y sesión continuada; `test_etcd_application_identity_is_prefix_restricted`; negativos TLS/mTLS de la regresión anterior |
| R3/W2, 512 MiB, delta de 4 KiB, memoria y tráfico | [Medición corregida y tablas por nodo/bloque](medicion.md) |
| Corrección de rutas sin escape físico | `test_block_path_race.py`: errores reales 3/2, normalización tras resolución y rechazo de junction externa |
| Segunda descarga explícita sobre destino existente | `measurement-fixed.json`, segunda receive con `overwrite=True`; protección predeterminada conservada en RF2 |
| Contratos y paquete | Generación/importación en el verificador; [wheel instalado](package.json); comprobación funcional instalada registrada separadamente |

Los escenarios no simulan HA mediante SQLite compartida ni montajes de bloques.
La migración y los respaldos sí copian archivos durante mantenimiento: son
recuperación administrativa, no evidencia de tráfico de replicación.

Límites pendientes ajenos a la aceptación de fallos de procesos: Linux/WSL,
hosts independientes, acceso desde Internet y despliegue cloud; seguridad
integral E8, cifrado de volúmenes y custodia de producción. Q01–Q07 siguen sin
respuesta docente, incluida Q05 sobre la mediación CN→etcd→CN. La interfaz para
liberar pins administrativos de migración y la recolección física de páginas
etcd huérfanas siguen pendientes: se conserva información de forma segura y se
aplica cuota, sin prometer almacenamiento ilimitado ni eliminación automática.
