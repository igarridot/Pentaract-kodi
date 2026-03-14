# Pentaract Kodi

Addon para Kodi 21 que actua como cliente de `pentaract`.

## Que incluye

- `plugin.video.pentaract`: addon de video para navegar storages, carpetas y ficheros.
- `repository.pentaract`: addon de repositorio para instalar el cliente desde Kodi.
- `scripts/build_repository.py`: genera `repository/` y `docs/` localmente para pruebas y publicacion.

`docs/` y `repository/` son artefactos generados. Se usan en local, pero ya no se versionan en Git para evitar conflictos de merge con ZIPs y contenido publicado.

## Publicacion automatica

Cada merge a `master` dispara `.github/workflows/release.yml`, que hace esto automaticamente:

1. Calcula la siguiente version semantica estable (`vX.Y.Z`).
2. Actualiza solo la version de `plugin.video.pentaract`.
3. Valida la sintaxis Python.
4. Genera `repository/addons.xml`, `repository/addons.xml.md5` y los ZIPs.
5. Regenera `docs/` con una fuente web navegable y ZIPs estables.
6. Sube los ZIPs y metadatos como artefacto del workflow.
7. Sube `docs/` como artifact de GitHub Pages y lo despliega con `deploy-pages`.
8. Hace commit solo del `addon.xml` de `plugin.video.pentaract`.
9. Crea y publica un tag Git estandar.
10. Publica una GitHub Release con los ZIPs y metadatos.

La logica de versionado esta en `scripts/version.py`. Si no existe ningun tag semantico previo, la primera release usa la version actual de `plugin.video.pentaract`. A partir de ahi, cada merge incrementa automaticamente el patch del addon de video. `repository.pentaract` mantiene su version hasta que necesites cambiar manualmente el propio addon de repositorio.

## Instalacion en Kodi

1. Asegura que GitHub Actions puede escribir en `master`, crear tags y desplegar GitHub Pages.
2. Activa GitHub Pages una sola vez en `Settings > Pages` usando `GitHub Actions` como fuente.
3. Haz merge a `master` y espera a que termine la release automatica.
4. En Kodi ve a `Settings > File Manager > Add source`.
5. Como ruta introduce exactamente `https://igarridot.github.io/Pentaract-kodi/`.
6. Ponle el nombre que quieras, por ejemplo `Pentaract`.
7. Ve a `Add-ons > Install from ZIP file`, entra en la fuente `Pentaract` y selecciona `repository.pentaract.zip`.
8. Ve a `Add-ons > Install from repository > Pentaract Repository > Video add-ons > Pentaract`.
9. Al abrir el addon, Kodi pedira:
   - URL base de `pentaract`
   - usuario o email
   - contrasena

## URLs exactas publicadas

- Repositorio GitHub: `https://github.com/igarridot/Pentaract-kodi`
- Pagina de releases: `https://github.com/igarridot/Pentaract-kodi/releases`
- Fuente web para Kodi: `https://igarridot.github.io/Pentaract-kodi/`
- ZIP estable del repositorio para `Install from ZIP file`: `https://igarridot.github.io/Pentaract-kodi/repository.pentaract.zip`
- ZIP estable del addon de video: `https://igarridot.github.io/Pentaract-kodi/plugin.video.pentaract.zip`
- Feed `addons.xml`: `https://igarridot.github.io/Pentaract-kodi/repository/addons.xml`
- Checksum del feed: `https://igarridot.github.io/Pentaract-kodi/repository/addons.xml.md5`
- Base de ZIPs del repositorio: `https://igarridot.github.io/Pentaract-kodi/repository/zips/`
- ZIP actual del addon de repositorio: `https://igarridot.github.io/Pentaract-kodi/repository/zips/repository.pentaract/repository.pentaract-1.0.2.zip`
- ZIP actual del addon de video: `https://igarridot.github.io/Pentaract-kodi/repository/zips/plugin.video.pentaract/plugin.video.pentaract-1.0.2.zip`

Cuando haya nuevas releases, el patron de las URLs versionadas seguira este formato:

- `https://github.com/igarridot/Pentaract-kodi/releases/download/vX.Y.Z/repository.pentaract-A.B.C.zip`
- `https://github.com/igarridot/Pentaract-kodi/releases/download/vX.Y.Z/plugin.video.pentaract-X.Y.Z.zip`
- `https://igarridot.github.io/Pentaract-kodi/repository/zips/repository.pentaract/repository.pentaract-A.B.C.zip`
- `https://igarridot.github.io/Pentaract-kodi/repository/zips/plugin.video.pentaract/plugin.video.pentaract-X.Y.Z.zip`

Notas:

- `plugin.video.pentaract` incrementa su version automaticamente en cada merge a `master`.
- `repository.pentaract` solo cambia de version cuando se modifica manualmente el propio addon de repositorio.

## Test local con Docker Compose

Hay dos modos de probar el addon en local, ambos sin levantar `pentaract` desde este repo.

### Modo 1: probar el flujo real de instalacion

Este modo levanta:

- `repo`: un `nginx` sirviendo `docs/` en `http://localhost:18080`
- `kodi`: Kodi Omega con `noVNC` en `http://localhost:18000`

Pasos:

1. En este repo ejecuta:
   - `make local-up`
2. Abre Kodi en `http://localhost:18000`
3. En Kodi ve a `Settings > File Manager > Add source`
4. Como fuente usa exactamente `http://repo/`
   - Ese nombre funciona porque `make local-build` genera el feed apuntando a `http://repo/` y Kodi resuelve el servicio `repo` dentro de la red de `docker compose`
5. Ve a `Add-ons > Install from ZIP file` e instala `repository.pentaract.zip`
6. Después instala `Pentaract` desde `Pentaract Repository`
7. Dentro del addon configura como URL base de `pentaract`

URL base recomendada:

- Si tu `pentaract` está en la misma máquina y publica el puerto `8000`: `http://host.docker.internal:8000`
- Si está en otra máquina o en otro entorno: usa la URL real alcanzable desde el contenedor Kodi

### Modo 2: desarrollo rapido montando el addon

Si quieres iterar sin reinstalar el ZIP cada vez, usa también el override `docker-compose.local.dev.yml`:

- `make local-dev-up`

Eso monta directamente [plugin.video.pentaract](/Volumes/SUNEAST/workspace/Pentaract-kodi/plugin.video.pentaract) dentro de Kodi en `/data/.kodi/addons/plugin.video.pentaract`.

Notas:

- Para streams lentos desde `pentaract`, puedes subir el timeout HTTP de Kodi:
  - `make local-kodi-http-timeout`
  - después `make local-restart`
- El propio addon incluye una acción en el menú raíz:
  - `[ Aplicar ajuste de streaming recomendado ]`
  - modifica `advancedsettings.xml` con confirmación explícita y luego pide reiniciar Kodi
- Tras cambiar código Python del addon, reinicia Kodi para recargarlo:
  - `make local-dev-restart`
- Para apagar el stack local:
  - `make local-down`
- Para ver logs:
  - `make local-logs`
- Esta imagen de Kodi funciona mejor recreando el contenedor que usando `restart`; por eso `make local-restart` y `make local-dev-restart` hacen `down` + `up`
- Los datos persistentes de Kodi quedan en `local-testing/kodi-data/`
- `advancedsettings.xml` lo generará Kodi en el primer arranque dentro de `local-testing/kodi-data/.kodi/userdata/`
- El contenedor expone también:
  - webserver Kodi: `http://localhost:18081`
  - JSON-RPC: `tcp://localhost:19090`
  - VNC: `localhost:15900`

## Nota sobre permisos de GitHub

Si `master` esta protegida, la GitHub Action debe tener permiso para hacer push a la rama y crear tags. Si la politica del repositorio no lo permite con `GITHUB_TOKEN`, necesitarias autorizar bypass para GitHub Actions o usar un token dedicado. GitHub Pages debe quedar configurado para desplegar desde `GitHub Actions`.

## Comportamiento del addon

- Lista los storages accesibles para el usuario autenticado.
- Permite navegar carpetas usando `/api/storages/{storageID}/files/tree/*`.
- Los ficheros de video compatibles se reproducen en streaming usando `/api/storages/{storageID}/files/download/*?inline=1`.
- Los ficheros no video pueden verse como entrada informativa si la opcion correspondiente esta activa.

## Nota importante sobre videos largos

`pentaract` usa JWT con expiracion. Si la reproduccion de videos largos falla tras unos 30 minutos, aumenta `ACCESS_TOKEN_EXPIRE_IN_SECS` en el servidor para dar mas margen a Kodi durante el streaming.
