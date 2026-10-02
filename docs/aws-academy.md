# E9 — AWS Academy: acceso, consumo y ventana de ejecución

Actualización 2026-10-02. **Preparado localmente; acceso y despliegue bloqueados.**
AWS Academy está confirmado por el usuario. USD 50 es el presupuesto general
indicado, no saldo consultado ni autorización para gastarlo. Ni USD 5/8 h ni
la propuesta siguiente están autorizados. No se ha creado ningún recurso cloud.
Los resultados E8 y los 93 casos locales E9 no acreditan esta infraestructura.

## Acceso dedicado, sin secretos en la conversación

No se encontró AWS CLI en PATH/instalación estándar ni `.aws/config` o
`.aws/credentials` en el perfil del usuario. No hay región, cuenta, cuota,
permisos o beneficios gratuitos comprobados. No se utilizó una cuenta personal.

1. Abrir el laboratorio **AWS Academy** existente y sus instrucciones vigentes.
   Revisar regiones/tipos permitidos, duración de sesión y presupuesto mostrado.
   La guía pública antigua no determina las restricciones de este laboratorio.
2. Instalar AWS CLI v2 mediante el [instalador oficial para Windows](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).
   Es una instalación local, no aprovisionamiento AWS. Registrar `aws --version`.
3. Obtener acceso temporal en AWS Details del laboratorio. Son tres valores:
   access key, secret key **y session token**. No pegarlos en chat, argumentos,
   historial PowerShell, documentos o Git.
4. Con la región permitida ya identificada, usar el helper interactivo:

```powershell
# Sustituir solo la region por la permitida; no usar el ejemplo como autorizacion.
.\.venv-win\Scripts\python.exe scripts/academy_profile.py --region REGION_PERMITIDA
```

Pide los tres secretos sin eco y escribe `%USERPROFILE%\.aws\credentials`
sección `[academy]` y config `[profile academy]` con ACL local protegida.
Conserva los valores de otros perfiles; normaliza comentarios/espaciado INI.
Rechaza un perfil academy existente salvo `--refresh`: usarlo únicamente tras
comprobar que ese perfil corresponde al laboratorio. No lo ejecuté sin secretos.
Para renovar la sesión repetir con `--refresh`; no cambiar cuenta/región a ciegas.
Una interrupción entre ambos archivos exige comprobarlos, no muestra secretos.

```powershell
aws --version
aws configure list-profiles
aws configure get region --profile academy
# Lectura STS; cotejar Account con la consola abierta desde Academy:
aws sts get-caller-identity --profile academy --region REGION_PERMITIDA
.\.venv-win\Scripts\python.exe scripts/cloud_preflight.py --profile academy --account CUENTA_ACADEMY --region REGION_PERMITIDA --deployment-id UUID_PROYECTO --output .runtime/academy/preflight.json
```

La identidad obtenida debe coincidir con la académica. El preflight elimina
credenciales/redirecciones AWS heredadas del entorno del proceso hijo; usa el
perfil explícito y exige token. No muestra stderr bruto, claves ni tokens.
Consulta STS, región/AZ, tipos y ofertas por AZ, redes/rutas, AMI Canonical,
recursos etiquetados del proyecto, cuotas y Free Tier. `AccessDenied` o
`ExpiredToken` quedan diferenciados; una cuota denegada sigue sin verificar.
`LECTURA_VERIFICADA` **no prueba** RunInstances/StopInstances, capacidad de seis
vCPU restantes, autorización económica o beneficio gratuito. Consultar también
las restricciones visibles del laboratorio y verificar las solicitudes con
`--dry-run` después de completar AMI/red/SSH. DryRunOperation indica permiso,
no reserva capacidad ni garantiza que el lanzamiento futuro funcione.

## Qué se puede llamar gratis

| Observación | Interpretación válida ahora |
| --- | --- |
| `FreeTierEligible` en tipos/AMI | Elegibilidad técnica; no demuestra beneficio de la cuenta |
| `freetier get-free-tier-usage` | Oferta/uso de esa cuenta, si permite consultarlo; comprobar vigencia/límite y servicio |
| USD 50 indicados por el usuario | Créditos generales, no gasto cero, saldo actual desconocido |
| Oferta pública de 100 GB/mes de salida | Existe una franquicia pública, pero consumo restante/agregación de cuenta no comprobados |
| Créditos de alta de cuentas nuevas | No se transfieren por inferencia a una cuenta administrada Academy |
| Factura personal cero | No implica consumo cero de créditos académicos |

No se descuenta ningún beneficio del cálculo. La
[API Free Tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-free-tier-api.html)
y las [condiciones de cuenta](https://aws.amazon.com/free/free-tier-faqs/)
se deben contrastar con el laboratorio real. La
[guía pública Academy de 2021](https://d1.awsstatic.com/AWS%20Academy%20Learner%20Lab%20Educator%20Guide.pdf)
es histórica, no permite sustituir los USD 50 indicados ni deducir cuotas actuales.

## Configuración mínima propuesta

Región de **referencia económica**: `us-east-1`; región permitida aún desconocida.
Tres VMs Ubuntu 24.04 amd64 sin Pro/Marketplace, imagen Canonical fijada antes
de crear; cada una CN+DN+etcd y volumen propio. Inicialmente una AZ permitida:
demuestra caída de VM, no de zona. S/S exclusivamente por IP privada en una VPC.

`t3.medium`: 2 vCPU/4 GiB por host. `t3a.medium` ahorra aproximadamente 10 % y
mantiene amd64; elegirla solo si tipo/cuota/AMI están permitidos y disponibles.
No introducir ARM (etcd/artefactos preparados amd64), Spot ni suscripciones.
Una micro de 1 GiB o small de 2 GiB no ofrece margen frente a techos combinados
CN 768 MiB + DN 1024 MiB + etcd 768 MiB, SO, buffers y administración.
4 GiB es candidato mínimo prudente, no consumo demostrado del host.

Modo **Standard explícito**: 24 créditos CPU/h, base de 20 % por vCPU en estos
medium. Sin créditos puede ralentizar preparación/pruebas. No habilitar Unlimited
para cumplir un tiempo: su cargo Linux publicado de USD 0,05/vCPU-h puede sumar
hasta USD 0,30 por hora de seis vCPU suplementarias, según consumo facturable.
La parada por plazo se mantiene aunque las pruebas no hayan terminado.
Fuentes: [T3/T3a, tamaños/tarifas](https://aws.amazon.com/ec2/instance-types/t3/),
[modo Standard](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-standard-mode.html).

Por VM: **16 GiB raíz + 12 GiB datos gp3 cifrados**, 3000 IOPS/125 MiB/s incluidos;
total **84 GiB**. Raíz para SO/Python/wheel/binarios/logs; datos para etcd (cuota
1 GiB), inventario, bloques, staging y margen. Cuota DN de 4 GiB: un archivo
512 MiB replicado deja ~512 MiB por host más versiones retenidas y temporales;
presupuestar al menos 2 GiB para staging/retención y revisar `df`/reservas. Esto
no es dimensionamiento E10 ni permite acumular indefinidamente demos/snapshots.
No eliminar referencias para liberar espacio: abortar/controlar nuevas pruebas.

Tres IPv4 públicas **automáticas**, sin Elastic IP retenidas, DNS de pago ni
NAT Gateway/balanceador/Kubernetes/RDS. Las IPv4 se cobran mientras se usan y
se liberan al detener la VM; pueden cambiar al iniciar. Acceso SSH y TLS C/S
limitado a /32 autorizadas. Security group interno por grupo propio; nftables
con IP privadas reales. No modificar grupos, rutas o discos de otros trabajos.
Confirmar subred pública con ruta a Internet Gateway antes de reutilizarla.

## Estimación concreta, sin descuentos

Consulta de fuentes públicas: **2026-10-02**. Precios USD, Linux On-Demand,
referencia N. Virginia. El precio publicado T3 es **0,0418**, T3a **0,0376**;
no se sustituyó por 0,0416 recordado de otras tablas. EBS/transferencia/snapshot
son tarifas de referencia que deben recotizarse para la región efectivamente
permitida; no hay una cotización autenticada de la cuenta. Mes de 30 días/720 h
para comparación, sin impuestos. No se verificó saldo actualizado.

| Recurso | Cantidad/tamaño | Tarifa de referencia | Gratis verificado | 2 h | 8 h |
| --- | --- | --- | --- | ---: | ---: |
| Cómputo | 3 t3.medium; 6 / 24 horas-instancia | 0,0418/VM-h | Ninguno | 0,2508 | 1,0032 |
| EBS gp3 | 84 GiB, seis discos | 0,08/GiB-mes | Ninguno | 0,0187 | 0,0747 |
| IPv4 automáticas | 3 | 0,005/IP-h | Ninguno | 0,0300 | 0,1200 |
| Entrada desde Internet | Archivo/delta y provisión | Tarifa pública de entrada 0 | No descuento de cuenta | 0 | 0 |
| Salida a Internet | Previsión conservadora 10 GB totales, también backup externo | 0,09/GB provisional, sin franquicia descontada | Ninguno | 0,9000 | 0,9000 |
| S/S privado misma AZ | Replicación/etcd | 0 para flujo EC2 privado misma AZ | Condición de red aún no ejecutada | 0 | 0 |
| Snapshot AWS | Ninguno en plan base | Opcional 0,05/GiB-mes | Ninguno | 0 | 0 |
| Backup | Archivo cifrado en disco local existente del custodio | Incluido en 10 GB salida; capacidad local a verificar | No nuevo almacenamiento AWS | 0 | 0 |
| Otros | Sin NAT/LB/EIP/servicios administrados/licencias/monitorización detallada | Ninguno aprovisionado | No aplica | 0 | 0 |
| **Total sesión, almacenamiento durante esas horas** | **Tres VMs** | **Estimación, no límite garantizado** | **Sin descuentos** | **1,1995** | **2,0979** |

Fuentes: [T3](https://aws.amazon.com/ec2/instance-types/t3/),
[gp3](https://aws.amazon.com/ebs/volume-types/),
[EBS/snapshots](https://aws.amazon.com/ebs/pricing/),
[IPv4](https://aws.amazon.com/vpc/pricing/),
[transferencia EC2](https://aws.amazon.com/ec2/pricing/on-demand/),
[transferencias entre AZ](https://aws.amazon.com/blogs/architecture/overview-of-data-transfer-costs-for-common-architectures/).

La provisión de 10 GB no es un medidor ni un límite de red; incluye varias
descargas, backup y diagnóstico. Medir consumo; cada GB adicional cuesta según
tarifa efectiva. No fijar salida sin medida como si fuera tráfico observado.
Multi-AZ conserva mismas VMs/discos pero agrega transferencia interzona: ejemplo
10 GB S/S a 0,01 por extremo = USD 0,20 adicionales; etcd/replicación/reintentos
también cuentan. No intercambiar IP públicas para S/S. Las zonas se deben permitir
y no hacen que una sola prueba de caída de VM demuestre tolerancia de zona.

| VMs detenidas, recursos conservados | 7 días adicionales | 30 días adicionales |
| --- | ---: | ---: |
| 84 GiB EBS | 1,5680 | 6,7200 |
| IPv4 automáticas liberadas | 0 | 0 |
| **Residual base** | **1,5680** | **6,7200** |
| Snapshot AWS opcional de 3 GiB facturables | +0,0350 | +0,1500 |
| Tres EIP si se decidiera retenerlas (no propuestas) | +2,5200 | +10,8000 |

Los snapshots se cobran por bloques efectivamente almacenados, no solo por el
tamaño lógico de un archivo. En 30 días los discos consumen ~13,44 % de los
USD 50 generales: es importante retirarlos después de backup verificado y
autorización explícita; el verificador no lo hará. Un cuarto host opcional
igualmente dimensionado por dos horas agrega ~USD 0,0998 de cómputo/IP/disco,
más tráfico y USD 0,5227 si se conserva su disco siete días. No está incluido.

**Propuesta para autorizar, no concedida:** tres VMs, una AZ, cuatro horas máximas
incluyendo creación/instalación/pruebas/cierre, parada automática, conservación de
discos hasta revisión a siete días y **tope operativo recomendado USD 4**.
Estimación 4 h = USD 1,4989 + siete días USD 1,5680 = **USD 3,0669**, margen ~0,93.
No es techo garantizado por AWS; detener ante desviaciones, no extender solo.
Reservar al menos USD 40 del presupuesto indicado para E10/correcciones/demo.
Dos horas (USD 1,1995 más retención) permiten primera instalación/health/parada,
pero no prometen completar E9: tres instalaciones, PKI, medición, fallo, retorno,
quórum y restauración pueden superar ese plazo con CPU Standard. Ocho horas son
solo comparación, no solicitud vigente ni autorización. Revisar precios y saldo
antes de aprobar; si región cambia, recalcular.

## Plan de lanzamiento listo para completar con observaciones reales

`academy_plan.py` **solo escribe solicitudes**, nunca llama RunInstances. Exige
cuenta/perfil/AMI/subred/grupo/SSH/deadline explícitos y rechaza REPLACE. La imagen
debe ser Canonical Ubuntu amd64 sin product codes/licencias, raíz mínima ≤16 GiB.
No ejecutarlo con identificadores de pruebas; inventario real todavía vacío.

```powershell
Copy-Item deploy/cloud/academy-plan.example.json .runtime/academy/plan.json
# Completar desde preflight y la ventana AUTORIZADA, no desde ejemplos inventados.
.\.venv-win\Scripts\python.exe scripts/academy_plan.py --plan .runtime/academy/plan.json --output .runtime/academy/launch
# Lectura/validacion de permisos; --dry-run no crea las VMs:
aws ec2 run-instances --profile academy --region REGION_PERMITIDA --cli-input-json file://.runtime/academy/launch/a.json --user-data file://.runtime/academy/launch/window/user-data.yaml --dry-run
```

Repetir dry-run b/c. AWS devuelve DryRunOperation con salida no cero si el permiso
es válido: distinguirlo de UnauthorizedOperation. Nada de eso fue ejecutado aquí.
Se necesitan seis vCPU On-Demand Standard disponibles y volúmenes/red/cifrado
permitidos. Las AMI, nombres de keypair y subredes no se inventan.

Si no existe grupo propio, **tras autorización** crear uno en la VPC seleccionada,
etiquetarlo DFShaDeployment y aplicar `academy-ingress.example.json` completado.
Comandos preparados, NO EJECUTADOS:

```powershell
aws ec2 create-security-group --profile academy --region REGION_PERMITIDA --vpc-id VPC_VERIFICADA --group-name dfsha-UUID --description "DFSha E9 private servers" --tag-specifications file://.runtime/academy/security-tags.json
aws ec2 authorize-security-group-ingress --profile academy --region REGION_PERMITIDA --group-id SG_PROPIO --ip-permissions file://.runtime/academy/ingress.json
# Solo despues de autorizar recursos/coste/duracion y revisar los tres JSON:
aws ec2 run-instances --profile academy --region REGION_PERMITIDA --cli-input-json file://.runtime/academy/launch/a.json --user-data file://.runtime/academy/launch/window/user-data.yaml
aws ec2 run-instances --profile academy --region REGION_PERMITIDA --cli-input-json file://.runtime/academy/launch/b.json --user-data file://.runtime/academy/launch/window/user-data.yaml
aws ec2 run-instances --profile academy --region REGION_PERMITIDA --cli-input-json file://.runtime/academy/launch/c.json --user-data file://.runtime/academy/launch/window/user-data.yaml
```

El YAML se pasa explícitamente con `--user-data file://...`; AWS CLI hace la
codificación del argumento, no se pasa texto ya codificado a ese parámetro.
Verificar `describe-instance-attribute --attribute userData`: tras decodificar
una vez debe empezar por `#cloud-config` y contener el deadline previsto.
Referencia: [CLI RunInstances](https://docs.aws.amazon.com/cli/latest/reference/ec2/run-instances.html).
Tokens de cliente distintos por slot, estables por despliegue: no repetir con
otro token para resolver respuesta perdida; consultar etiqueta/resultado primero.
Cambiar el deadline en un request ya enviado requiere revisión, no relanzamiento.
Inventariar IDs, mapping volúmenes, AZ, direcciones y hashes. No reutilizar ni
recrear automáticamente un clúster previo. Raíz/datos cifrados, DeleteOnTermination
false, protección de terminación, IMDSv2, crédito Standard, apagado OS=stop;
sin IAM credenciales AWS en VMs. El runbook de [despliegue](despliegue.md) continúa
con montaje verificado, instalación, secretos por rol, etcd/RBAC, activación y
verificador externo. Nunca formatear un disco existente sin identificarlo.

## Parada independiente de esta terminal

El plan lleva cloud-init **sin secretos** con deadline UTC absoluto. Instala una
unidad/timer systemd persistente en cada VM, chequeo al arrancar y antes de
servicios, más revisión cada 30 s. Al vencer, ejecuta `systemctl poweroff`:
con `InstanceInitiatedShutdownBehavior=stop` detiene **la VM entera** y sus tres
roles. No termina instancias ni borra EBS/backups/claves. No depende de credenciales
temporales AWS ni de que Windows/Codex siga abierto. El SDK no amplía la ventana.

No es parada cloud acreditada: solo lógica probada localmente. Antes de iniciar
la carga, verificar `describe-instance-attribute` para apagado=stop, API stop no
bloqueada y conservación EBS; `describe-instance-credit-specifications` Standard;
en cada Linux `cloud-init status --wait`, `systemctl status dfsha-window.timer`,
`systemctl list-timers`, UTC/NTP. Probar primero plazo corto sobre los tres hosts
aislados, observar por API que quedan **stopped** y los volúmenes existen, y reanudar
con nueva ventana aprobada. Si cloud-init/timer fallan, detener desde consola/API
antes de iniciar pruebas. Un SO bloqueado o reloj erróneo puede impedir puntualidad:
el timer no garantiza máximo monetario. La prueba no ha sido sustituida por mocks.

Reanudación: mientras las VMs están **stopped**, generar un nuevo window con
deadline aprobado, actualizar **solo user-data** mediante `modify-instance-attribute
--user-data file://...` (JSON `Value` base64 de user-data.yaml), luego
`start-instances` con sus tres IDs verificados. El bootcmd persistido consulta
user-data por IMDSv2 y actualiza solo el deadline; si sigue vencido vuelve a
apagarse. No regenera PKI, bases o identidades ni cambia época compartida.
Sin renovar explícitamente la ventana, reinicios no conceden otras cuatro horas.
El chequeo periódico cubre el deadline nuevo aunque el OnCalendar original sea viejo.
Confirmar el mecanismo en VM; no declarar arranque desatendido todavía.

No se usan ASG, automatismos de recuperación EC2 (disabled) ni schedulers de pago.
La política del panel Academy puede detener/reanudar recursos por su cuenta;
revisarla y conservar la guardia local. Una alarma de saldo no reemplaza esta
parada. Detener antes manualmente: `aws ec2 stop-instances --profile academy
--region REGION_PERMITIDA --instance-ids IDS_VERIFICADOS`. Recoger evidencia antes
del deadline; si queda incompleta, registrar interrupción, no éxito.

### IP y certificado al reanudar

Preferencia económica: IP automática y procedimiento explícito. Consultar las
IP públicas nuevas; conservar privadas e IDs. Reemitir hojas usando **la misma
CA** con SAN público nuevo y privado conservado (`issue_certificate.py --ip ...`),
sin recrear CA/KEK. Actualizar inventario, listener anunciado en CN/DN, allowlist
administrativa idéntica en los tres controles y endpoints de entrada del cliente.
Reiniciar controles uno a uno y DN afectado con generación nueva; el registro
reconcilia ubicaciones en el control. Nunca editar mapas de bloques en cliente.
Si están las tres detenidas, hacer actualización antes de habilitar la carga.
Probar TLS/SAN, snapshots y hashes después; DNS estable existente puede evitar
reemitir por cambio de IP, pero no se supone un dominio disponible ni se compra.

## Pendientes de aceptación

Una vez autorizada y validada la ventana: usuario ordinario externo, RF1/2/3,
512 MiB/4 KiB, hashes, bytes C↔DN/S/S y cero contenido CN, tres copias reales,
fallo de VM durante operación, resultado incierto/failover W2, regreso R3,
quórum, backup cifrado externo/restauración y cierre observado. El backup cloud
adaptado sigue pendiente de completar y probar; no lo acredita un snapshot EBS.
E9 sigue parcial, E10 no se ejecutó. Ningún recurso nuevo está encendido o generando
coste; se desconoce el coste de recursos ajenos de una cuenta sin acceso.
