#!/usr/bin/env python3

import hashlib
import shutil
import xml.dom.minidom
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent.parent
ADDON_DIRS = [
    ROOT / "plugin.video.pentaract",
    ROOT / "repository.pentaract",
]
OUTPUT_DIR = ROOT / "repository"
ZIPS_DIR = OUTPUT_DIR / "zips"
DOCS_DIR = ROOT / "docs"
PAGES_URL = "https://igarridot.github.io/Pentaract-kodi/"
REPO_URL = "https://github.com/igarridot/Pentaract-kodi"


def parse_addon(addon_dir):
    tree = ET.parse(addon_dir / "addon.xml")
    addon = tree.getroot()
    normalize_xml(addon)
    return {
        "dir": addon_dir,
        "id": addon.attrib["id"],
        "version": addon.attrib["version"],
        "xml": addon,
    }


def clean_output():
    if ZIPS_DIR.exists():
        shutil.rmtree(ZIPS_DIR)
    ZIPS_DIR.mkdir(parents=True, exist_ok=True)


def build_zip(addon):
    target_dir = ZIPS_DIR / addon["id"]
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir / ("%s-%s.zip" % (addon["id"], addon["version"]))
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for file_path in sorted(addon["dir"].rglob("*")):
            if not file_path.is_file():
                continue
            if "__pycache__" in file_path.parts or file_path.name == ".DS_Store":
                continue
            archive.write(
                file_path,
                str(Path(addon["dir"].name) / file_path.relative_to(addon["dir"])),
            )
    addon["zip_path"] = zip_path


def build_addons_xml(addons):
    root = ET.Element("addons")
    for addon in addons:
        root.append(addon["xml"])
    xml_bytes = ET.tostring(root, encoding="utf-8")
    pretty_xml = xml.dom.minidom.parseString(xml_bytes).toprettyxml(indent="  ", encoding="utf-8")
    addons_xml_path = OUTPUT_DIR / "addons.xml"
    addons_xml_path.write_bytes(pretty_xml)
    checksum = hashlib.md5(pretty_xml).hexdigest()
    (OUTPUT_DIR / "addons.xml.md5").write_text(checksum, encoding="utf-8")


def normalize_xml(element):
    if element.text is not None and not element.text.strip():
        element.text = None
    if element.tail is not None and not element.tail.strip():
        element.tail = None
    for child in list(element):
        normalize_xml(child)


def clean_docs():
    generated_paths = [
        DOCS_DIR / "repository",
        DOCS_DIR / "repository.pentaract.zip",
        DOCS_DIR / "plugin.video.pentaract.zip",
        DOCS_DIR / "index.html",
        DOCS_DIR / ".nojekyll",
    ]
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for path in generated_paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def publish_pages(addons):
    clean_docs()
    shutil.copytree(OUTPUT_DIR, DOCS_DIR / "repository")

    latest_repo_zip = next(addon["zip_path"] for addon in addons if addon["id"] == "repository.pentaract")
    latest_plugin_zip = next(addon["zip_path"] for addon in addons if addon["id"] == "plugin.video.pentaract")

    shutil.copy2(latest_repo_zip, DOCS_DIR / "repository.pentaract.zip")
    shutil.copy2(latest_plugin_zip, DOCS_DIR / "plugin.video.pentaract.zip")
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (DOCS_DIR / "index.html").write_text(build_pages_index(addons), encoding="utf-8")


def build_pages_index(addons):
    repo_addon = next(addon for addon in addons if addon["id"] == "repository.pentaract")
    plugin_addon = next(addon for addon in addons if addon["id"] == "plugin.video.pentaract")
    repo_zip_name = repo_addon["zip_path"].name
    plugin_zip_name = plugin_addon["zip_path"].name

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pentaract Kodi Hub</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f6f2;
      --panel: #ffffff;
      --text: #182126;
      --muted: #5e6b73;
      --link: #0a6e78;
      --border: #d7dedf;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: linear-gradient(180deg, #eef4f1 0%, var(--bg) 45%, #f5efe7 100%);
      color: var(--text);
    }}
    main {{
      max-width: 820px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 24px;
      box-shadow: 0 12px 40px rgba(24, 33, 38, 0.08);
      margin-bottom: 18px;
    }}
    h1, h2 {{
      margin-top: 0;
    }}
    p, li {{
      line-height: 1.6;
    }}
    a {{
      color: var(--link);
      text-decoration: none;
      font-weight: 600;
    }}
    a:hover {{
      text-decoration: underline;
    }}
    code {{
      background: #eef2f3;
      border-radius: 6px;
      padding: 0.15em 0.4em;
    }}
    ul, ol {{
      padding-left: 22px;
    }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>Pentaract Kodi Hub</h1>
      <p>Fuente web para instalar el repositorio y el addon de Pentaract en Kodi, al estilo de los tutoriales con "Add source".</p>
      <p><strong>Fuente para Kodi File Manager:</strong> <code>{PAGES_URL}</code></p>
    </section>
    <section class="panel">
      <h2>Descargas rápidas</h2>
      <ul>
        <li><a href="repository.pentaract.zip">repository.pentaract.zip</a> - alias estable al ZIP actual del repositorio.</li>
        <li><a href="plugin.video.pentaract.zip">plugin.video.pentaract.zip</a> - alias estable al ZIP actual del addon.</li>
        <li><a href="repository/zips/repository.pentaract/{repo_zip_name}">{repo_zip_name}</a></li>
        <li><a href="repository/zips/plugin.video.pentaract/{plugin_zip_name}">{plugin_zip_name}</a></li>
      </ul>
    </section>
    <section class="panel">
      <h2>Instalación en Kodi</h2>
      <ol>
        <li>Ve a <strong>Settings &gt; File Manager &gt; Add source</strong>.</li>
        <li>Introduce exactamente <code>{PAGES_URL}</code> y ponle un nombre, por ejemplo <code>Pentaract</code>.</li>
        <li>Ve a <strong>Add-ons &gt; Install from ZIP file</strong> y entra en la fuente que acabas de crear.</li>
        <li>Selecciona <a href="repository.pentaract.zip"><code>repository.pentaract.zip</code></a>. Es la opción recomendada porque permite actualizaciones automáticas.</li>
        <li>Después ve a <strong>Install from repository &gt; Pentaract Repository &gt; Video add-ons &gt; Pentaract</strong>.</li>
      </ol>
      <p>Si instalas <a href="plugin.video.pentaract.zip"><code>plugin.video.pentaract.zip</code></a> directamente, el addon se instala, pero no seguirá el flujo normal de autoactualización mediante repositorio.</p>
    </section>
    <section class="panel">
      <h2>Publicación</h2>
      <p>El repositorio fuente está en <a href="{REPO_URL}">{REPO_URL}</a>. Las releases versionadas siguen publicándose en GitHub Releases y en el feed de Kodi dentro de <a href="repository/addons.xml"><code>repository/addons.xml</code></a>.</p>
    </section>
  </main>
</body>
</html>
"""


def main():
    addons = [parse_addon(addon_dir) for addon_dir in ADDON_DIRS]
    clean_output()
    for addon in addons:
        build_zip(addon)
    build_addons_xml(addons)
    publish_pages(addons)


if __name__ == "__main__":
    main()
