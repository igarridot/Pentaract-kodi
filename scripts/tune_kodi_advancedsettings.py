#!/usr/bin/env python3

import argparse
import os
import xml.etree.ElementTree as ET


def ensure_child(parent, tag):
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    return child


def indent(element, level=0):
    prefix = "\n" + "    " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = prefix + "    "
        for child in element:
            indent(child, level + 1)
        if not element[-1].tail or not element[-1].tail.strip():
            element[-1].tail = prefix
    elif level and (not element.tail or not element.tail.strip()):
        element.tail = prefix


def parse_args():
    parser = argparse.ArgumentParser(description="Adjust Kodi advancedsettings.xml network timeouts.")
    parser.add_argument("--file", required=True, help="Path to advancedsettings.xml")
    parser.add_argument("--client-timeout", type=int, default=120, help="Value for curlclienttimeout")
    parser.add_argument("--low-speed-time", type=int, default=120, help="Value for curllowspeedtime")
    return parser.parse_args()


def main():
    args = parse_args()
    settings_path = os.path.abspath(args.file)
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)

    if os.path.exists(settings_path):
        tree = ET.parse(settings_path)
        root = tree.getroot()
    else:
        root = ET.Element("advancedsettings")
        tree = ET.ElementTree(root)

    network = ensure_child(root, "network")
    ensure_child(network, "curlclienttimeout").text = str(args.client_timeout)
    ensure_child(network, "curllowspeedtime").text = str(args.low_speed_time)

    indent(root)
    tree.write(settings_path, encoding="utf-8", xml_declaration=False)
    print(
        "Updated %s: curlclienttimeout=%s curllowspeedtime=%s"
        % (settings_path, args.client_timeout, args.low_speed_time)
    )


if __name__ == "__main__":
    main()
