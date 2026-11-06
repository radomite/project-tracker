"""Exercise deployment ordering/failure recovery with fake Docker and no network."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
REVISION='a'*40

FAKE_DOCKER=r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args=sys.argv[1:]
state=Path(os.environ['FAKE_STATE'])
with (state/'calls').open('a') as f:f.write(json.dumps(args)+'\n')
if args==['info'] or args==['compose','version']:sys.exit(0)
if args[0]=='inspect':print('old-image');sys.exit(0)
if args[0]=='run':
    if os.environ.get('FAIL_BACKUP')=='1':sys.exit(1)
    sys.stdout.write('fake-consistent-backup');sys.exit(0)
index=next(i for i,a in enumerate(args) if a in ['config','pull','ps','stop','start','up','port'])
cmd=args[index:]
if cmd[:2]==['config','--services']:print('app\nlatex')
elif cmd[0]=='ps' and cmd[-1]=='app' and os.environ.get('HAS_OLD')=='1':print('old-app-container')
elif cmd[0]=='pull' and os.environ.get('FAIL_PULL')=='1':sys.exit(1)
elif cmd[0]=='up' and os.environ.get('FAIL_HEALTH')=='1':sys.exit(1)
elif cmd[0]=='port':print('127.0.0.1:18765')
'''

FAKE_CURL=r'''#!/usr/bin/env python3
import os, shutil, sys
shutil.copyfile(os.environ['FAKE_ARCHIVE'],sys.argv[sys.argv.index('-o')+1])
'''


@unittest.skipUnless(os.name=='posix' and shutil.which('bash'), 'Linux installer checks run on GitHub CI')
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.bin=self.root/'bin';self.bin.mkdir()
        for name,source in [('docker',FAKE_DOCKER),('curl',FAKE_CURL)]:
            p=self.bin/name;p.write_text(source,encoding='utf-8');p.chmod(0o755)
        self.archive=self.root/'release.tar.gz'
        with tarfile.open(self.archive,'w:gz') as archive:
            content=b'services: {}\n'
            entry=tarfile.TarInfo('release/deploy/compose.yaml');entry.size=len(content)
            archive.addfile(entry,io.BytesIO(content))
        self.install=self.root/'install'
        self.env={**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],
            'FAKE_ARCHIVE':str(self.archive),'FAKE_STATE':str(self.root)}

    def old_release(self):
        self.install.mkdir()
        previous=self.install/'releases'/('b'*40)
        (previous/'deploy').mkdir(parents=True)
        (previous/'deploy/compose.yaml').write_text('services: {}\n')
        (previous/'deployment.env').write_text('IMAGE_TAG='+'b'*40+'\n')
        (self.install/'current').symlink_to(previous,target_is_directory=True)
        self.env['HAS_OLD']='1'
        return previous

    def run_installer(self):
        result=subprocess.run(['bash',str(ROOT/'deploy/install.sh'),'example/project-tracker',REVISION,
            str(self.install),'project.example.org','18765'],env=self.env,capture_output=True,text=True,timeout=20)
        calls=[json.loads(line) for line in (self.root/'calls').read_text().splitlines()]
        return result,calls

    def test_first_install_uses_exact_images_and_keeps_setup_key_out_of_logs(self):
        result,calls=self.run_installer()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.install/'current').resolve().name,REVISION)
        key=(self.install/'secrets/setup-token').read_text()
        self.assertEqual(len(key),64)
        self.assertNotIn(key,result.stdout+result.stderr)
        self.assertIn('127.0.0.1:18765',(self.install/'Caddyfile').read_text())
        self.assertFalse(any('build' in call for call in calls))

    def test_update_pulls_then_stops_then_backs_up_then_starts(self):
        self.old_release()
        result,calls=self.run_installer()
        self.assertEqual(result.returncode,0,result.stderr)
        pull=next(i for i,c in enumerate(calls) if 'pull' in c)
        stop=next(i for i,c in enumerate(calls) if 'stop' in c)
        backup=next(i for i,c in enumerate(calls) if c[0]=='run')
        up=next(i for i,c in enumerate(calls) if 'up' in c)
        self.assertLess(pull,stop);self.assertLess(stop,backup);self.assertLess(backup,up)
        self.assertEqual(len(list((self.install/'backups').glob('*/data.tar.gz'))),1)

    def test_failed_pull_leaves_existing_stack_and_current_untouched(self):
        previous=self.old_release();self.env['FAIL_PULL']='1'
        result,calls=self.run_installer()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.install/'current').resolve(),previous)
        self.assertFalse(any('stop' in c or 'up' in c for c in calls))

    def test_failed_backup_restarts_previous_stack_without_running_new_image(self):
        previous=self.old_release();self.env['FAIL_BACKUP']='1'
        result,calls=self.run_installer()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.install/'current').resolve(),previous)
        self.assertTrue(any('start' in c for c in calls))
        self.assertFalse(any('up' in c for c in calls))

    def test_failed_new_health_check_retains_backup_and_previous_release_pointer(self):
        previous=self.old_release();self.env['FAIL_HEALTH']='1'
        result,calls=self.run_installer()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.install/'current').resolve(),previous)
        self.assertEqual(len(list((self.install/'backups').glob('*/data.tar.gz'))),1)
        self.assertTrue((self.install/'failed-or-interrupted-deployment').exists())
        before=len(calls)
        retry,retry_calls=self.run_installer()
        self.assertNotEqual(retry.returncode,0)
        self.assertFalse(any('pull' in c or 'stop' in c or 'up' in c for c in retry_calls[before:]))
