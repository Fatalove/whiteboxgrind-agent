"""Status remains key-free and respects completed retention decisions."""
import contextlib,io,json,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from wbg import cli

class StatusTests(unittest.TestCase):
    def test_no_key_in_status_and_no_repeated_choice_after_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'result.json').write_text(json.dumps({'status':'verified','recovery':{'status':'verified','key_hex':'SHOULD_NOT_LEAK'}}))
            (root/'retention.json').write_text('{"status":"completed"}')
            output=io.StringIO()
            with patch.object(cli,'_run_path',return_value=root),contextlib.redirect_stdout(output):
                code=cli.main(['status','--run-id','synthetic','--json'])
            self.assertEqual(code,0)
            self.assertNotIn('SHOULD_NOT_LEAK',output.getvalue())
            self.assertFalse(json.loads(output.getvalue())['retention']['decision_required'])
