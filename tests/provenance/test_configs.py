import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from formats import config
from prepare_configs import add_ids, prepare


class ConfigTests(unittest.TestCase):
    def test_real_vehicle_delta_and_idempotence(self):
        text = (Path(__file__).resolve().parents[2]/'resource/dio_manager.json').read_text()
        a, b = config(text), config(add_ids(text))
        want = copy.deepcopy(a)
        want['iap2']['MessagesSentByAccessory'] += ['0x5200', '0x5203']
        want['iap2']['MessagesReceivedFromDevice'] += ['0x5201', '0x5202', '0x5204']
        self.assertEqual(want, b)
        self.assertEqual(add_ids(text), add_ids(add_ids(text)))
        self.assertEqual([x for x in text.splitlines() if x.lstrip().startswith('#')],
                         [x for x in add_ids(text).splitlines() if x.lstrip().startswith('#')])

    def test_string_hash_and_escaped_quote(self):
        self.assertEqual(config('{"x":"a#b\\\"c" # comment\n}'), {'x': 'a#b"c'})

    def test_duplicate_key_rejected(self):
        with self.assertRaises(ValueError): config('{"x":1,"x":2}')

    def test_duplicate_id_rejected(self):
        with self.assertRaises(ValueError):
            add_ids('{"iap2":{"MessagesSentByAccessory":["0x5200","0X5200"],"MessagesReceivedFromDevice":[]}}')

    def test_empty_lists_and_existing_mixed_case(self):
        text = '{"iap2":{"MessagesSentByAccessory":["0X5200"],"MessagesReceivedFromDevice":[]}}'
        result = config(add_ids(text))['iap2']
        self.assertEqual(result['MessagesSentByAccessory'], ['0X5200', '0x5203'])
        self.assertEqual(result['MessagesReceivedFromDevice'], ['0x5201', '0x5202', '0x5204'])

    def test_ambiguous_names_rejected(self):
        with self.assertRaises(ValueError):
            add_ids('{"other":{"MessagesSentByAccessory":[]},"iap2":{"MessagesSentByAccessory":[],"MessagesReceivedFromDevice":[]}}')

    def test_changed_vehicle_baseline_rejected_without_output(self):
        base = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            source, dest = Path(folder)/'source', Path(folder)/'output'
            source.mkdir()
            (source/'dio_manager.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'differs from audited baseline'):
                prepare(source, dest, base/'reports/input-manifest.json')
            self.assertFalse(dest.exists())


if __name__ == '__main__': unittest.main()
