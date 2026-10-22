import importlib.util
import io
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("host", ROOT / "native/host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class Invocation:
    def return_value(self, value):
        self.value = value

    def return_dbus_error(self, name, message):
        raise AssertionError(f"{name}: {message}")


class HostTests(unittest.TestCase):
    def test_protocol_round_trip(self):
        stream = io.BytesIO()
        message = {"action": "tray", "available": True}
        host.send_message(message, stream)
        stream.seek(0)
        self.assertEqual(host.read_message(stream), message)

    def test_partial_reads_and_eof(self):
        class ShortReads(io.BytesIO):
            def read(self, size):
                return super().read(min(size, 2))
        stream = io.BytesIO()
        host.send_message({"action": "show"}, stream)
        self.assertEqual(host.read_message(ShortReads(stream.getvalue())), {"action": "show"})
        with self.assertRaises(EOFError):
            host.read_message(io.BytesIO(b"\x10\x00"))

    def test_size_limit(self):
        with self.assertRaises(ValueError):
            host.read_message(io.BytesIO(struct.pack("=I", 65537)))

    def test_interfaces_and_all_properties_match_dbus_signatures(self):
        h = host.Host()
        for xml in (host.SNI_XML, host.MENU_XML):
            interface = host.Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
            for prop in interface.properties:
                value = h.get_property(None, None, None, interface.name, prop.name)
                self.assertEqual(value.get_type_string(), prop.signature)

    def test_menu_layout_filters_and_child_depth(self):
        h = host.Host()
        packed = host.GLib.Variant("(u(ia{sv}av))", (1, h.layout(0, -1, [])))
        revision, layout = packed.unpack()
        self.assertEqual(revision, 1)
        self.assertEqual(len(layout[2]), 3)
        self.assertEqual(layout[2][0][1]["label"], "显示 Thunderbird")
        self.assertEqual(h.layout(0, 0, [])[2], [])
        self.assertEqual(set(h.layout(1, 0, ["label"])[1]), {"label"})

    def test_menu_actions_and_unknown_items(self):
        h = host.Host()
        with patch.object(h, "send") as send:
            for item, action in ((1, "show"), (2, "hide"), (3, "quit")):
                self.assertTrue(h.event(item, "clicked"))
                send.assert_called_with(action)
            send.reset_mock()
            self.assertFalse(h.event(99, "clicked"))
            h.event(1, "hovered")
            send.assert_not_called()

    def test_menu_method_return_values(self):
        h = host.Host()
        cases = [
            ("GetLayout", "(iias)", (0, -1, []), "(u(ia{sv}av))"),
            ("GetGroupProperties", "(aias)", ([], []), "(a(ia{sv}))"),
            ("GetProperty", "(is)", (1, "label"), "(v)"),
            ("AboutToShow", "(i)", (0,), "(b)"),
            ("AboutToShowGroup", "(ai)", ([0, 1, 99],), "(aiai)"),
            ("EventGroup", "(a(isvu))", ([(99, "clicked", host.GLib.Variant("i", 0), 0)],), "(ai)"),
        ]
        for method, signature, args, expected in cases:
            with self.subTest(method=method):
                invocation = Invocation()
                h.method(None, None, None, "com.canonical.dbusmenu", method,
                         host.GLib.Variant(signature, args), invocation)
                self.assertEqual(invocation.value.get_type_string(), expected)

    def test_watcher_disappearance_revokes_hide_permission(self):
        h = host.Host()
        with patch.object(h, "send") as send:
            h.watcher_owner = ":1.2"
            h.vanished(None, "org.kde.StatusNotifierWatcher")
            self.assertIsNone(h.watcher_owner)
            send.assert_called_once_with("tray", available=False)

    def test_manifest_only_allows_our_addon(self):
        manifest = json.loads((ROOT / "addon/manifest.json").read_text())
        self.assertEqual(manifest["permissions"], ["nativeMessaging"])
        gecko = manifest["browser_specific_settings"]["gecko"]
        self.assertEqual(gecko["strict_min_version"], "156.0")
        self.assertEqual(gecko["strict_max_version"], "*")


if __name__ == "__main__":
    unittest.main()
