# Dos fallos recuperados de la regresión Windows

`20260930T231040Z-3b63eca4` terminó con **114 aprobados y dos fallidos**, pytest
exit 1 registrado y fuentes sin cambios. El supervisor escribió estado FALLIDO;
la sesión de ejecución externa ya no existía al recuperarla y no se atribuye un
exit code externo no observado. El XML/log completo permanece privado en
`.runtime/verification-e8/20260930T231040Z-3b63eca4/`.

## Inyección de respuesta perdida

`test_cross_control_parallel_publication_and_lost_reply` conservó los cambios
disjuntos; falló posteriormente al esperar COMMITTED para la inyección de respuesta
perdida. GetOperation devolvió PREPARING. El archivo
`after_commit_drop_response` seguía presente: la inyección aún no había ocurrido.
El control registró `CommitWrite:SERVICE_UNAVAILABLE:etcd_metadata.py:214` a las
23:26:30 UTC: no obtuvo la barrera durante su espera acotada de ocho segundos.

La prueba ahora consulta la operación mediante el control alternativo después
de cada intento. Solo repite la solicitud **idéntica**, hasta tres intentos, si la
autoridad conserva PREPARING y el marcador sigue presente. Exige COMMITTED,
marcador consumido y reproducción del resultado original desde otro control.
No convierte cualquier excepción en demostración de respuesta perdida, no
cambia los TTL y no repite una publicación confirmada.

## Lease de barrera abandonada después de un fallo de red

`test_rolling_peer_and_datanode_certificates_then_quorum_loss` restauró mayoría,
pero BeginRead agotó su deadline. Los controles registraron reiteradamente
`SERVICE_UNAVAILABLE` al esperar la barrera. El adaptador conservaba por hilo el
lease de esa barrera aun cuando no pudo confirmar su liberación. Un intento
posterior hacía KeepAlive del mismo lease antes de competir por otra adquisición;
podía prolongar la barrera abandonada que estaba esperando.

Se aisló el mecanismo en `test_stage8_gate_recovery.py`, con tres procesos etcd
y un proxy TCP: adquirir, preparar un registro, particionar antes del cleanup,
abortar, recuperar red y volver a intentar. Antes de corregir, el run
`20261001T033756Z-f6944354` falló en 6,10 s porque conservó el lease
`4086059195795752206` en caché. Es un identificador de diagnóstico, no una credencial.

El adaptador ahora descarta el lease en caché ante adquisición/renovación incierta
o una transacción no confirmada. La liberación sigue comparando el propietario;
si falla, etcd deja expirar la adquisición anterior sin KeepAlive posteriores.
No se elimina una barrera ajena ni se renueva un lock de datos vencido. El nuevo
intento recibe otra identidad. La prueba exige ausencia del registro abortado y
publicación observable del nuevo registro desde otro cliente autoritativo.
La repetición en `20261001T034010Z-c326ea4d` aprobó este caso. El cierre
`20261001T034229Z-9d313040` aprobó los 36 casos E7/E8 afectados y la medición de
512 MiB; `20261001T034403Z-581a2df8` aprobó los mismos 36 en Linux. Las pruebas
de certificados/pérdida de quórum y respuesta perdida pasaron en ambas plataformas.

Los IDs de ejecución usan UTC; `20261001T03…Z` corresponde a la noche del
30 de septiembre en Colombia. Estos fallos se conservan separados de cualquier
repetición posterior aprobada.
