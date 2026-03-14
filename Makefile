.PHONY: help local-build local-up local-dev-up local-down local-restart local-dev-restart local-logs local-ps local-kodi-http-timeout

COMPOSE_LOCAL = docker compose -f docker-compose.local.yml
COMPOSE_LOCAL_DEV = docker compose -f docker-compose.local.yml -f docker-compose.local.dev.yml

help:
	@printf '%s\n' \
		'Targets disponibles:' \
		'  make local-build       Regenera repository/ y docs/' \
		'  make local-up          Levanta Kodi + repo local para probar instalacion' \
		'  make local-dev-up      Levanta Kodi + repo local montando el addon en vivo' \
		'  make local-down        Apaga el stack local de Kodi' \
		'  make local-restart     Reinicia el stack local de Kodi' \
		'  make local-dev-restart Reinicia el stack con el addon montado' \
		'  make local-kodi-http-timeout Sube timeouts HTTP de Kodi en advancedsettings.xml' \
		'  make local-logs        Muestra logs de Kodi y repo' \
		'  make local-ps          Lista los contenedores del stack local'

local-build:
	python3 scripts/build_repository.py

local-up: local-build
	$(COMPOSE_LOCAL) up -d

local-dev-up: local-build
	$(COMPOSE_LOCAL_DEV) up -d

local-down:
	$(COMPOSE_LOCAL_DEV) down

local-restart:
	$(COMPOSE_LOCAL) down
	$(COMPOSE_LOCAL) up -d

local-dev-restart:
	$(COMPOSE_LOCAL_DEV) down
	$(COMPOSE_LOCAL_DEV) up -d

local-kodi-http-timeout:
	python3 scripts/tune_kodi_advancedsettings.py --file local-testing/kodi-data/.kodi/userdata/advancedsettings.xml --client-timeout 120 --low-speed-time 120

local-logs:
	$(COMPOSE_LOCAL) logs -f kodi repo

local-ps:
	$(COMPOSE_LOCAL) ps
