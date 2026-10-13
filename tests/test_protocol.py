"""Tests that do not require Home Assistant to be installed."""

import importlib.util
import sys
import unittest
from pathlib import Path

PROTOCOL_PATH = (
    Path(__file__).parents[1] / "custom_components" / "kiturami_multi" / "protocol.py"
)
SPEC = importlib.util.spec_from_file_location("kiturami_multi_protocol", PROTOCOL_PATH)
protocol = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = protocol
assert SPEC.loader is not None
SPEC.loader.exec_module(protocol)


class ProtocolTest(unittest.TestCase):
    def test_room_list_uses_multi_manager_fields(self):
        payload = {
            "deviceInfoList": [
                {
                    "parentId": "1",
                    "deviceTopic": "12010100:12:345678",
                    "eachRoomID": "03",
                    "deviceAlias": "우리집",
                    "roomName": "거실",
                }
            ]
        }

        devices = protocol.room_devices_from_response(payload)

        self.assertEqual(1, len(devices))
        self.assertEqual("12010100:12:345678", devices[0].node_id)
        self.assertEqual("03", devices[0].room_id)
        self.assertEqual("거실", devices[0].name)

    def test_room_list_deduplicates_node_and_room(self):
        item = {
            "deviceTopic": "node",
            "eachRoomID": "1",
            "deviceAlias": "우리집",
        }
        devices = protocol.room_devices_from_response({"deviceInfoList": [item, item]})
        self.assertEqual(1, len(devices))
        self.assertEqual("01", devices[0].room_id)
        self.assertEqual("우리집 (각방 01)", devices[0].name)

    def test_legacy_multiroom_discovery(self):
        member_payload = {
            "memberDeviceList": [
                {
                    "parentId": "1",
                    "nodeId": "legacy-node",
                    "deviceAlias": "우리집",
                }
            ]
        }
        nodes = protocol.device_nodes_from_response(member_payload)
        self.assertEqual(1, len(nodes))

        detail_payload = {
            "deviceSlaveInfo": [
                {"slaveId": "01", "alias": "거실"},
                {"slaveId": "02", "alias": "안방"},
            ]
        }
        devices = protocol.legacy_room_devices_from_response(detail_payload, nodes[0])

        self.assertEqual(["01", "02"], [device.room_id for device in devices])
        self.assertEqual(["거실", "안방"], [device.name for device in devices])
        self.assertTrue(all(device.node_id == "legacy-node" for device in devices))

    def test_nested_legacy_multiroom_discovery(self):
        member_payload = {
            "data": {
                "groups": [
                    {"devices": [{"nodeID": "nested-node", "deviceName": "보일러"}]}
                ]
            }
        }
        nodes = protocol.device_nodes_from_response(member_payload)
        self.assertEqual("nested-node", nodes[0].node_id)

        detail_payload = {
            "result": {
                "rooms": {
                    "items": [
                        {"roomID": "1", "deviceAlias": "거실"},
                        {"roomID": "2", "deviceAlias": "안방"},
                    ]
                }
            }
        }
        devices = protocol.legacy_room_devices_from_response(detail_payload, nodes[0])
        self.assertEqual(["01", "02"], [device.room_id for device in devices])
        self.assertEqual(["거실", "안방"], [device.name for device in devices])

    def test_power_action(self):
        self.assertEqual(("0101", "030000000001"), protocol.power_action("03", True))
        self.assertEqual(("0101", "030000000002"), protocol.power_action("03", False))

    def test_indoor_heat_action(self):
        self.assertEqual(
            ("0102", "030000001600"),
            protocol.indoor_heat_action("03", 22),
        )
        with self.assertRaises(ValueError):
            protocol.indoor_heat_action("03", 46)

    def test_away_action(self):
        self.assertEqual(("0106", "030200000000"), protocol.away_action("03"))

    def test_temperature_hex_round_trip(self):
        encoded = protocol.temperature_to_hex(24)
        self.assertEqual("18", encoded)
        self.assertEqual(24.0, protocol.temperature_from_hex(encoded))

    def test_mode_info_selects_requested_room(self):
        payload = {
            "detailItemList": [
                {"eachRoomID": "01", "currentTemp": "15"},
                {"eachRoomID": "03", "currentTemp": "18", "currentValue": "16"},
            ]
        }
        result = protocol.mode_info_from_response(payload, "03")
        self.assertEqual("18", result["currentTemp"])
        self.assertEqual("16", result["currentValue"])


if __name__ == "__main__":
    unittest.main()
