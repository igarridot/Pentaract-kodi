.PHONY: help test local-build local-up local-dev-up local-down local-restart local-dev-restart local-logs local-ps local-kodi-http-timeout

COMPOSE_LOCAL = docker compose -f docker-compose.local.yml
COMPOSE_LOCAL_DEV = docker compose -f docker-compose.local.yml -f docker-compose.local.dev.yml
LOCAL_REPOSITORY_BASE_URL = http://repo/

help:
	@printf '%s\n' \
		'Available targets:' \
		'  make test              Run addon unit tests' \
		'  make local-build       Regenerate repository/ and docs/' \
		'  make local-up          Start Kodi + local repo for installation flow testing' \
		'  make local-dev-up      Start Kodi + local repo with the addon mounted live' \
		'  make local-down        Stop the local Kodi stack' \
		'  make local-restart     Recreate the local Kodi stack' \
		'  make local-dev-restart Recreate the stack with the live-mounted addon' \
		'  make local-kodi-http-timeout Increase Kodi HTTP timeouts in advancedsettings.xml' \
		'  make local-logs        Show Kodi and repo logs' \
		'  make local-ps          List local stack containers'

test:
	python3 -m unittest discover -s tests -p 'test_*.py'

local-build:
	PENTARACT_KODI_PUBLIC_BASE_URL=$(LOCAL_REPOSITORY_BASE_URL) python3 scripts/build_repository.py

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
