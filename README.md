# Pentaract Kodi

Kodi 21 addon and repository for browsing Pentaract storages and streaming supported video files.

## Components

- `plugin.video.pentaract`: Kodi video addon that authenticates against `pentaract`, lists storages, browses folders, and plays supported media.
- `repository.pentaract`: Kodi repository addon used for standard installation and automatic updates.
- `scripts/build_repository.py`: generates `repository/` metadata plus the GitHub Pages-friendly `docs/` site and stable ZIP aliases.

## Current Features

- Login with Pentaract base URL plus user or email credentials
- Storage listing and folder navigation through the Pentaract API
- Direct playback of supported video files
- Optional listing of non-video files as informational entries
- Local streaming proxy with configurable buffer profiles
- Optional direct streaming mode that bypasses the local proxy
- Playback buffer overlay handled entirely by the addon
- Repository packaging for Kodi "Install from ZIP file" and "Install from repository" flows
- Docker Compose setup for real-install testing and fast live addon iteration

## Release Automation

Each merge to `master` triggers [.github/workflows/release.yml](/Volumes/SUNEAST/workspace/Pentaract-kodi/.github/workflows/release.yml), which:

1. Resolves the next stable semantic version (`vX.Y.Z`).
2. Updates the video addon version in `plugin.video.pentaract/addon.xml`.
3. Validates Python syntax.
4. Generates `repository/addons.xml`, `repository/addons.xml.md5`, and all release ZIP files.
5. Regenerates `docs/` with a browsable GitHub Pages source and stable ZIP aliases.
6. Uploads ZIPs and metadata as workflow artifacts.
7. Publishes `docs/` to GitHub Pages.
8. Commits the version bump for `plugin.video.pentaract/addon.xml`.
9. Creates and pushes the Git tag.
10. Publishes the GitHub Release with ZIPs and repository metadata attached.

Version logic lives in `scripts/version.py`. If no previous semantic tag exists, the first automated release keeps the current addon version. After that, each merge increments the patch version of `plugin.video.pentaract`. `repository.pentaract` only changes when you update the repository addon itself.

## Install In Kodi

1. Make sure GitHub Actions can push to `master`, create tags, and deploy GitHub Pages.
2. Enable GitHub Pages once in `Settings > Pages` with `GitHub Actions` as the source.
3. Merge to `master` and wait for the automated release to finish.
4. In Kodi, go to `Settings > File Manager > Add source`.
5. Enter `https://igarridot.github.io/Pentaract-kodi/` exactly as the path.
6. Give it any name you want, for example `Pentaract`.
7. Go to `Add-ons > Install from ZIP file`, open that source, and install `repository.pentaract.zip`.
8. Go to `Add-ons > Install from repository > Pentaract Repository > Video add-ons > Pentaract`.
9. Open the addon and configure:
   - Pentaract base URL
   - user or email
   - password

## Published URLs

- GitHub repository: `https://github.com/igarridot/Pentaract-kodi`
- GitHub releases: `https://github.com/igarridot/Pentaract-kodi/releases`
- GitHub Pages source for Kodi: `https://igarridot.github.io/Pentaract-kodi/`
- Stable repository ZIP: `https://igarridot.github.io/Pentaract-kodi/repository.pentaract.zip`
- Stable video addon ZIP: `https://igarridot.github.io/Pentaract-kodi/plugin.video.pentaract.zip`
- `addons.xml` feed: `https://igarridot.github.io/Pentaract-kodi/repository/addons.xml`
- `addons.xml.md5`: `https://igarridot.github.io/Pentaract-kodi/repository/addons.xml.md5`
- Repository ZIP base: `https://igarridot.github.io/Pentaract-kodi/repository/zips/`

Versioned release URLs follow these patterns:

- `https://github.com/igarridot/Pentaract-kodi/releases/download/vX.Y.Z/repository.pentaract-A.B.C.zip`
- `https://github.com/igarridot/Pentaract-kodi/releases/download/vX.Y.Z/plugin.video.pentaract-X.Y.Z.zip`
- `https://igarridot.github.io/Pentaract-kodi/repository/zips/repository.pentaract/repository.pentaract-A.B.C.zip`
- `https://igarridot.github.io/Pentaract-kodi/repository/zips/plugin.video.pentaract/plugin.video.pentaract-X.Y.Z.zip`

## Local Testing With Docker Compose

The repo supports two local workflows without starting `pentaract` from this project.

### Mode 1: Full installation flow

This mode starts:

- `repo`: an `nginx` container serving `docs/` at `http://localhost:18080`
- `kodi`: Kodi Omega with `noVNC` at `http://localhost:18000`

Steps:

1. Run `make local-up`.
2. Open Kodi at `http://localhost:18000`.
3. In Kodi, go to `Settings > File Manager > Add source`.
4. Use `http://repo/` exactly as the source URL.
   The generated repository feed points to `http://repo/`, and Kodi can resolve that service name inside the Docker Compose network.
5. Go to `Add-ons > Install from ZIP file` and install `repository.pentaract.zip`.
6. Install `Pentaract` from `Pentaract Repository`.
7. Configure the addon with the base URL of your running `pentaract` instance.

Recommended base URL:

- If `pentaract` runs on the same machine and exposes port `8000`: `http://host.docker.internal:8000`
- Otherwise: use the real URL reachable from the Kodi container

### Mode 2: Fast development with the addon mounted live

Run `make local-dev-up` to start the same stack with `docker-compose.local.dev.yml`, mounting [plugin.video.pentaract](/Volumes/SUNEAST/workspace/Pentaract-kodi/plugin.video.pentaract) directly into Kodi at `/data/.kodi/addons/plugin.video.pentaract`.

Useful notes:

- The addon can stream through its own local proxy, so buffering and request timeouts stay local to the addon.
- It does not modify `advancedsettings.xml`, `filecache.*`, or Kodi-wide buffering settings.
- Buffer profiles and advanced buffering live under `Addon settings > Playback`.
- The playback buffer overlay can be toggled in `Addon settings > Playback > Show buffer overlay`.
- Restart Kodi after changing Python code so the addon reloads cleanly: `make local-dev-restart`.
- Shut down the local stack with `make local-down`.
- View logs with `make local-logs`.
- The provided Kodi image behaves more reliably when recreated instead of restarted in place, which is why `make local-restart` and `make local-dev-restart` do `down` + `up`.
- Persistent Kodi data is stored in `local-testing/kodi-data/`.
- The container also exposes:
  - Kodi webserver: `http://localhost:18081`
  - JSON-RPC: `tcp://localhost:19090`
  - VNC: `localhost:15900`

## Addon Behavior

- Lists the storages available to the authenticated user.
- Browses folders via `/api/storages/{storageID}/files/tree/*`.
- Streams supported video files via `/api/storages/{storageID}/files/download/*?inline=1`.
- Uses either direct backend URLs or the addon-managed local proxy, depending on the selected playback mode.
- Can show a buffer overlay driven by the addon proxy prebuffer state.
- Can expose non-video files as informational items when that setting is enabled.

## GitHub Permissions Note

If `master` is protected, GitHub Actions must be allowed to push commits and tags. If repository policy does not allow that through `GITHUB_TOKEN`, you need either a bypass rule for GitHub Actions or a dedicated token. GitHub Pages must remain configured to deploy from `GitHub Actions`.

## Long Playback Note

`pentaract` uses expiring JWT access tokens. If very long videos fail after roughly 30 minutes, increase `ACCESS_TOKEN_EXPIRE_IN_SECS` on the server so Kodi has a longer streaming window.
