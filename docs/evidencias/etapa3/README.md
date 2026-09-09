# Evidencias de etapa 3

Git: [publicación verificada](git-publicacion.json), commits E2 `df1fd33` y H1
`7bd8327`, origin/main sin reescritura de historial. Runtime/secretos fuera de Git.

**Cierre vigente: [20260909T195446Z](20260909T195446Z/resultado.json), EJECUTADO.**
[87 pruebas](20260909T195446Z/pytest.xml), cero fallos/errores/omitidos/advertencias,
142,86 s; [medición](20260909T195446Z/medicion.json) 1 GiB + dos clientes 64 MiB+1,
hashes correctos; pico cliente 54.112.256 B y servidor 85.471.232 B. No prueba
Linux, distribución, cloud ni optimización del perfil experimental.

El cierre reemplaza los estados parciales anteriores, que permanecen abajo como
historial. La advertencia de hilo de conectividad en 20260909T195004Z se corrigió
usando Health TLS acotado antes de Login; no se silenció la advertencia.

Referente E2 revisado: commit `df1fd33`, 70 pruebas reejecutadas antes de cambios
(XML local `.runtime/etapa3-baseline.xml`). PDF leído nuevamente completo:
[lectura-pdf.txt](lectura-pdf.txt); originales PDF/guía intactos por SHA-256.

- Pruebas de desarrollo: 13 casos H1 aprobados en `.runtime/hito1-third.xml`
  (196,62 s), más dos casos adicionales en `.runtime/hito1-extra.xml` (25,16 s).
  No se suman como una regresión conjunta de la versión final.
- [Primera medición fallida](medicion-inicial-fallida.json): un cliente obtuvo
  INVALID_ARGUMENT en SealManifest, dos completaron; no acredita 1 GiB. El pico
  de servidor de ese archivo corresponde al lanzador venv y **no es válido**.
- [Medición completada](medicion.json): 1 GiB y dos clientes de 64 MiB+1 por TLS,
  hashes verificados y PID real del servidor. El fallo inicial no reapareció en
  esta ejecución. La regresión conjunta posterior sí lo reprodujo y localizó la
  validación de deadline (monolith.py, punto de control anterior a efectos).
  Se observó 300,999... s para una llamada solicitada de 300 s; margen inicial
  de 1 s era demasiado estricto cerca del límite. Corregido a 2 s de tolerancia
  de representación, sin modificar plazos del SDK. Evidencia fallida conservada
  en 20260909T193923Z (84 aprobadas, tres fallidas; no es cierre).
- Carpetas con fecha UTC: `verify_stage3.py` escribe comandos exactos, versiones,
  XML y hashes del código efectivamente probado. Estado PENDIENTE/FALLIDO no es
  aprobación; únicamente EJECUTADO y cero fallos/omitidos acredita la suite.

La ejecución 20260909T194544Z aprobó **87 pruebas**, pero su medición posterior
falló por DEADLINE_EXCEEDED al establecer las tres conexiones de login. Se
conserva como FALLIDO global. SDK ahora espera canal TLS listo (10 s acotados)
antes de la RPC de autenticación (5 s); no repite login ni oculta errores.
El archivo [paquete.json](paquete.json) registra wheel instalado/importado en el
venv limpio E2, reemplazando solo DFSha, sin reinstalar las dependencias fijadas.

Claves, sesiones, bases, staging, archivos grandes y logs completos se conservan
solo en runtime ignorado. Windows local; no evidencia Linux/cloud/distribución.
