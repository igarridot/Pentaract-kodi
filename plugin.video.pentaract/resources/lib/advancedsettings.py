"""Kodi advancedsettings.xml helpers.

Kodi gives an HTTP source 20 seconds (``curllowspeedtime``) to deliver data
before it drops the connection and the player gives up. After a seek,
Pentaract has to download and decrypt a whole ~20 MB chunk from Telegram
before it can send the first byte, which on a slow Telegram link takes
longer than that. The only knob is Kodi's own advancedsettings.xml, which
no addon setting can replace, so this module edits that file in place while
preserving whatever else it already holds.
"""

import xml.etree.ElementTree as ET

DEFAULT_CLIENT_TIMEOUT_SECONDS = 120
DEFAULT_LOW_SPEED_TIME_SECONDS = 120


def _ensure_child(parent, tag):
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    return child


def _indent(element, level=0):
    prefix = "\n" + "    " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = prefix + "    "
        for child in element:
            _indent(child, level + 1)
        if not element[-1].tail or not element[-1].tail.strip():
            element[-1].tail = prefix
    elif level and (not element.tail or not element.tail.strip()):
        element.tail = prefix


def _parse(xml_text):
    if not xml_text or not xml_text.strip():
        return ET.Element("advancedsettings")
    root = ET.fromstring(xml_text)
    if root.tag != "advancedsettings":
        raise ValueError("not an advancedsettings.xml document: root is <%s>" % root.tag)
    return root


def read_network_timeouts(xml_text):
    """Return ``(curlclienttimeout, curllowspeedtime)`` as ints, or None for each missing value."""
    root = _parse(xml_text)
    network = root.find("network")
    values = []
    for tag in ("curlclienttimeout", "curllowspeedtime"):
        node = network.find(tag) if network is not None else None
        try:
            values.append(int((node.text or "").strip()) if node is not None else None)
        except ValueError:
            values.append(None)
    return tuple(values)


def timeouts_are_sufficient(xml_text, client_timeout=DEFAULT_CLIENT_TIMEOUT_SECONDS, low_speed_time=DEFAULT_LOW_SPEED_TIME_SECONDS):
    current_client_timeout, current_low_speed_time = read_network_timeouts(xml_text)
    return (
        current_client_timeout is not None
        and current_low_speed_time is not None
        and current_client_timeout >= client_timeout
        and current_low_speed_time >= low_speed_time
    )


def tune_network_timeouts(xml_text, client_timeout=DEFAULT_CLIENT_TIMEOUT_SECONDS, low_speed_time=DEFAULT_LOW_SPEED_TIME_SECONDS):
    """Return ``xml_text`` with ``<network>`` timeouts set, keeping every other setting."""
    root = _parse(xml_text)
    network = _ensure_child(root, "network")
    _ensure_child(network, "curlclienttimeout").text = str(int(client_timeout))
    _ensure_child(network, "curllowspeedtime").text = str(int(low_speed_time))
    _indent(root)
    return ET.tostring(root, encoding="unicode") + "\n"
