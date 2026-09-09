# Fuentes de terceros

`sources.lock.json` fija URL, revisión y SHA-256 de cada fuente original y licencia.
Los `.proto` de etcd 3.6.14 proceden de etcd-io/etcd; sus imports requieren gogo/protobuf
1.3.2, grpc-gateway 2.26.3 y el commit indicado de googleapis. Las licencias originales
están en `licenses/` (etcd/gateway/googleapis Apache 2.0; gogo BSD de tres cláusulas).

`scripts/vendor_etcd.py` verifica sin red; `--restore` recupera únicamente fuentes
ausentes desde sus URLs fijadas. `--refresh` cambia el inventario: usar solo durante
una actualización deliberada, revisar el diff y repetir todas las verificaciones.

`scripts/generate_proto.py` conserva intactos estos originales. En `build/proto/`
antepone `dfsha/_vendor/` a las rutas de imports externos y compila esas copias con
grpcio-tools. No cambia paquetes Protobuf, servicios, mensajes ni números de campo:
la API wire sigue siendo la oficial. Los módulos generados viven bajo `dfsha._vendor`
para evitar contaminar paquetes globales como `google`. Los tipos incorporados de
Google proceden de la distribución fijada de grpcio-tools/Protobuf. No se editan stubs
ni se eliminan sus validaciones de versión. `--check` compara bytes e importa todos.

El binario de compatibilidad se obtiene por separado con `scripts/fetch_etcd.py`:
release oficial y hashes fijados en `deploy/etcd-artifacts.json`; no se versiona.
