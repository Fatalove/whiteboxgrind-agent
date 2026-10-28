"""Task and delivery regressions using synthetic fixtures, not recovery proof."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from wbg.cases import prepare, _abi
from wbg.config import UnsupportedConfig
from wbg.delivery import recovery

SOURCE=b'void AES_128_encrypt(unsigned char *out, unsigned char *in) { out[0]=in[0]; }'

class TaskTests(unittest.TestCase):
    def test_unique_source_and_move_preserve_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'case';(root/'input').mkdir(parents=True)
            (root/'input/target.c').write_bytes(SOURCE)
            first=prepare(root)
            before=(root/'task.json').read_bytes()
            moved=root.rename(Path(temp)/'renamed')
            second=prepare(moved)
            self.assertEqual(first['seed'],second['seed'])
            self.assertEqual(before,(moved/'task.json').read_bytes())
            self.assertEqual((moved/'input/target.c').read_bytes(),SOURCE)

    def test_multiple_sources_require_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'input').mkdir()
            for name in ('a.c','b.c'):(root/'input'/name).write_bytes(SOURCE)
            self.assertEqual(prepare(root)['status'],'needs_selection')
            self.assertFalse((root/'task.json').exists())
            self.assertEqual(prepare(root,'a.c')['status'],'prepared')

    def test_comments_literals_and_prototypes_do_not_claim_support(self):
        for data in (b'/* '+SOURCE+b' */', b'const char*x="'+SOURCE+b'";',
                     b'void AES_128_encrypt(char *out,char *in);'):
            with self.assertRaises(UnsupportedConfig):_abi(data)
        self.assertEqual(_abi(b'void AES_128_encrypt(char *out,char *in) {}'),'char-pointer')

    def test_example_and_changed_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.assertEqual(prepare(root,example=True)['status'],'prepared')
            self.assertEqual(json.loads((root/'task.json').read_text())['inputs']['trace_count'],100)
            target=root/'input/ordinary-aes128.c';target.write_bytes(target.read_bytes()+b'\n')
            with self.assertRaises(Exception):prepare(root)

    def test_elf_and_escape_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'input').mkdir()
            (root/'input/binary').write_bytes(b'\x7fELF'+b'\0'*60)
            with self.assertRaises(UnsupportedConfig):prepare(root)
            (root/'input/binary').unlink()
            (root/'input/a.c').write_bytes(SOURCE)
            with self.assertRaises((ValueError,FileNotFoundError)):prepare(root,'../outside.c')

    def test_symlink_source_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'input').mkdir()
            target=root/'outside.c';target.write_bytes(SOURCE)
            try:(root/'input/link.c').symlink_to(target)
            except OSError:self.skipTest('symlinks unavailable')
            with self.assertRaises(ValueError):prepare(root)

class DeliveryTests(unittest.TestCase):
    def test_verified_record_requires_this_candidate_and_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);csv=root/'cpa.csv';csv.write_bytes(b'synthetic CPA fixture')
            candidate={'key_hex':'00'*16,'cpa_csv_sha256':hashlib.sha256(csv.read_bytes()).hexdigest()}
            file=root/'candidate.json';file.write_text(json.dumps(candidate))
            (root/'validation.json').write_text(json.dumps({'verified':True,'passed_count':16,'holdout_count':16,
                'verifier_selftest_passed':True,'candidate_sha256':hashlib.sha256(file.read_bytes()).hexdigest()}))
            result={'run_id':'synthetic','status':'verified'}
            record=recovery(root,result)
            self.assertEqual(record['status'],'verified');self.assertEqual(record['key_type'],'aes128_master_key')
            csv.write_bytes(b'changed')
            with self.assertRaises(ValueError):recovery(root,result)

    def test_failure_without_candidate_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            record=recovery(Path(temp),{'run_id':'synthetic','status':'cancelled'})
            self.assertIsNone(record['key_hex']);self.assertEqual(record['status'],'not_recovered')
