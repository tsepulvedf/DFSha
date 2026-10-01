# DFSha — Hito 3: evidencia y límites

Estado: E8 cerrada en el perfil protegido de laboratorio el 2026-10-01.
El hito reúne las capacidades locales de E5–E8; el despliegue académico,
dominios físicos y acceso desde Internet siguen pendientes de E9.

| Área | Implementación y evidencia | Estado |
| --- | --- | --- |
| Concurrencia y RF3 | [E5](etapa5-rf3.md): snapshots, parches atómicos, fencing y mezcla de bloques compatibles | Regresiones E8 acreditadas por caso; concurrencia entre controles repetida tras D64 |
| Replicación y recuperación | [E6](etapa6-replicacion.md): R=3/W=2, tareas persistentes, reparación y GC | Verificada en laboratorio de procesos; conservar sus perfiles |
| Control y consistencia | [E7](etapa7-ha-control.md), [aceptación](evidencias/etapa7/aceptacion.md): tres controles y un clúster etcd de tres miembros | E7 completa en Windows local; 152 casos distintos por ejecuciones identificadas, no una sola suite íntegra |
| Seguridad transversal | [E8](seguridad.md), [criterios](evidencias/etapa8/aceptacion.md), [cierre](evidencias/etapa8/cierre.md) | Perfil protegido verificado: 177 casos Windows por ejecuciones identificadas; 36 E7/E8 en Linux; 512 MiB protegidos en Windows |
| Hosts e Internet | Infraestructura académica, dominios físicos y cliente externo | Pendiente E9; varios procesos en un equipo no acreditan tolerancia de host |

El quórum de metadatos es la mayoría de etcd; W=2 cuenta copias durables de cada
versión nueva de bloque. Los bytes de contenido no atraviesan el ControlNode.
Q03 y Q05 continúan sin aclaración docente verificable. No se atribuye al docente
la aceptación de la mediación CN→etcd→CN ni se omite RF3.
