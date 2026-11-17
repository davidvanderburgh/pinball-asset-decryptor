#!/usr/bin/env python3
"""Qualify the Spike 2 SSH adapter on a real source image, without a cabinet.

Run from the checkout with its Python dependencies installed::

    python scripts/validate_card_ssh.py --source /path/to/factory.raw \
        --work-dir /path/shared/with/podman/ssh-test --engine podman

Requires ssh/ssh-keygen/sftp and an existing PAD Spike 2 emulator container
image. Creates disposable keys, full image copies and a dedicated container.
Never accesses your SSH agent/private keys. The work directory must be new.
This tests guest userspace and the installed boot hook under QEMU, not a full
kernel boot or cabinet hardware. Run the resulting card in the game emulator
as well before marking an adapter qualified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pinball_decryptor.core import card_extras, ssh_card  # noqa: E402
from pinball_decryptor.plugins.stern.pipeline import SternWritePipeline  # noqa: E402

BOOT = r'''#!/bin/bash
set -euo pipefail
mkdir -p /guest /work/persistent-data
debugfs -R 'rdump / /guest' /work/rootfs.img >/work/rdump.log 2>&1
mkdir -p /guest/dev /guest/proc /guest/var/run /guest/data
mount --bind /dev /guest/dev
mount -t proc proc /guest/proc
mount --bind /work/persistent-data /guest/data
cp /usr/bin/qemu-arm-static /guest/usr/bin/
if [ -L /guest/etc/rc5.d/S30sshd ]; then
  chroot /guest /usr/bin/qemu-arm-static /bin/sh /etc/rc5.d/S30sshd start
  echo SSH-BOOT-HOOK-STARTED
else
  echo SSH-BOOT-HOOK-DISABLED
fi
exec tail -f /dev/null
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', required=True)
    ap.add_argument('--work-dir', required=True)
    ap.add_argument('--engine', default='podman')
    ap.add_argument('--container-image', default='docker.io/library/pad-spike2-emu:c2977305564')
    ap.add_argument('--port', type=int, default=22392)
    args = ap.parse_args()
    source, work = Path(args.source).resolve(), Path(args.work_dir).resolve()
    if work.exists():
        ap.error('--work-dir must be new; old test keys/results are never reused')
    if not source.is_file() or not 1024 <= args.port <= 65535:
        ap.error('Provide a source file and a nonprivileged TCP port')
    info = ssh_card.inspect_image(str(source))
    if info.get('platform') != 'stern-spike2':
        ap.error(info.get('reason') or 'Not a recognized Spike 2 image')
    if shutil.disk_usage(work.parent).free < source.stat().st_size + (2 << 30):
        ap.error('Not enough space for an output image and filesystem scratch files')
    work.mkdir(mode=0o700)
    project = work / 'project'; project.mkdir()
    output = work / 'ssh-card.raw'
    name = 'pad-ssh-qualify-' + uuid.uuid4().hex[:12]
    results = []
    def passed(text):
        results.append(text); print('PASS ' + text, flush=True)
    def run(argv, **kw):
        return subprocess.run(argv, check=True, capture_output=True, text=True, **kw)
    names = ['ed25519-a', 'ed25519-b', 'rsa', 'ec256', 'ec384', 'ec521']
    for kind, bits, key in [('ed25519',None,'ed25519-a'),('ed25519',None,'ed25519-b'),
                            ('ed25519',None,'denied'),('rsa','2048','rsa'),
                            ('ecdsa','256','ec256'),('ecdsa','384','ec384'),('ecdsa','521','ec521')]:
        argv = ['ssh-keygen','-q','-t',kind,'-N','','-f',str(work/key)]
        if bits: argv += ['-b',bits]
        run(argv)
    keys = ''.join((work/(n+'.pub')).read_text() for n in names)
    (work/'boot.sh').write_text(BOOT)
    # Qualification is deliberately allowed only in this test process; this
    # does not change the production allowlist or bypass image identification.
    ssh_card.QUALIFIED_PLATFORMS = {'stern-spike2'}
    def build(enabled, text):
        card_extras.save(str(project), enabled, text)
        done = []
        with (work/'pipeline.log').open('a') as log:
            p = SternWritePipeline(str(source), str(project), str(output),
                lambda msg,level='info': print(level,msg,file=log,flush=True),
                lambda *a: None, lambda *a: None, lambda ok,msg: done.append((ok,msg)), update=False)
            p.run()
        if not done or not done[-1][0]:
            raise RuntimeError('Pipeline failed; see pipeline.log: ' + str(done))
        _,_,offset,size = ssh_card.inspect_image(str(output))['partition']
        with output.open('rb') as src, (work/'rootfs.img').open('wb') as dst:
            src.seek(offset)
            while size:
                block=src.read(min(size,1<<20))
                if not block: raise RuntimeError('Truncated partition')
                dst.write(block);size-=len(block)
    def stop():
        subprocess.run([args.engine,'rm','-f',name],capture_output=True)
    def boot():
        stop()
        run([args.engine,'run','-d','--name',name,'--user','0','--privileged',
             '-p',f'127.0.0.1:{args.port}:22','-v',str(work)+':/work',
             '--entrypoint','/bin/bash',args.container_image,'/work/boot.sh'])
    opts=['-o','IdentitiesOnly=yes','-o','IdentityAgent=none','-o','BatchMode=yes',
          '-o','StrictHostKeyChecking=accept-new','-o','UserKnownHostsFile='+str(work/'known_hosts'),
          '-o','ConnectTimeout=3']
    def ssh(key='ed25519-a', command='id -u', extra=()):
        return subprocess.run(['ssh','-p',str(args.port),*opts,'-i',str(work/key),*extra,
                               'root@127.0.0.1',command],capture_output=True,text=True,timeout=15)
    def ready(key='ed25519-a'):
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            p=ssh(key)
            if p.returncode==0 and p.stdout.strip()=='0':return
            time.sleep(1)
        raise RuntimeError('Guest SSH startup/login failed: '+p.stderr)
    def identity():
        return {p.name:ssh_card._hash_file(p) for p in (work/'persistent-data/dropbear').glob('*_host_key')}
    try:
        build(True,keys);passed('SSH-only card built through the real PAD pipeline')
        boot();ready()
        first_identity=identity()
        assert len(first_identity)==3
        for key in names:
            p=ssh(key);assert p.returncode==0 and p.stdout.strip()=='0',(key,p.stderr)
        passed('All authorized key types authenticate as root through installed boot hook')
        p=ssh('denied');assert p.returncode==255 and 'Permission denied (publickey)' in p.stderr,p.stderr
        p=ssh(extra=['-o','PubkeyAuthentication=no','-o','NumberOfPasswordPrompts=0'])
        assert p.returncode==255 and 'Permission denied (publickey)' in p.stderr,p.stderr
        passed('Unknown key and password-only authentication refused; only publickey advertised')
        content=bytes(range(256))*16;(work/'upload.bin').write_bytes(content)
        run(['sftp','-P',str(args.port),*opts,'-i',str(work/'ed25519-b'),'-b','-',
             'root@127.0.0.1'],input=f'put {work}/upload.bin /tmp/pad-ssh.bin\nget /tmp/pad-ssh.bin {work}/download.bin\n')
        assert (work/'download.bin').read_bytes()==content
        passed('SFTP upload/download is byte-identical')
        p=ssh(command='/etc/init.d/sshd restart');assert p.returncode==0,p.stderr
        ready();assert identity()==first_identity
        passed('Service restart preserves persistent host identity')
        stop();build(True,(work/'ed25519-b.pub').read_text());boot();ready('ed25519-b')
        p=ssh();assert p.returncode==255 and 'Permission denied (publickey)' in p.stderr,p.stderr
        assert identity()==first_identity
        passed('Changed key list replaces earlier keys; host identity survives image reboot')
        stop();build(False,keys);boot()
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            logs=run([args.engine,'logs',name]).stdout
            if 'SSH-BOOT-HOOK-DISABLED' in logs:break
            time.sleep(1)
        else: raise RuntimeError('Disabled guest did not finish starting')
        p=subprocess.run([args.engine,'exec','--user','0',name,'pgrep','-x','dropbear'],capture_output=True)
        assert p.returncode==1 and ssh('ed25519-b').returncode==255
        assert identity()==first_identity
        passed('Disabled card has no startup hook, daemon or login; host keys retained')
        stop();build(True,keys)
        # Check source preservation and every output byte outside the system
        # partition in bounded chunks; include MBR, games, scores and logs.
        _,_,start,size=ssh_card.inspect_image(str(output))['partition']
        with source.open('rb') as a, output.open('rb') as b:
            for lo,hi in [(0,start),(start+size,source.stat().st_size)]:
                a.seek(lo);b.seek(lo);left=hi-lo
                while left:
                    n=min(left,1<<20);assert a.read(n)==b.read(n),'Non-system bytes changed';left-=n
        passed('All bytes outside system partition match source')
        record={'source':str(source),'output':str(output),'platform':'stern-spike2',
                'source_sha256':ssh_card._hash_file(source),'output_sha256':ssh_card._hash_file(output),
                'rootfs_sha256':ssh_card._hash_file(work/'rootfs.img'),
                'container_image':args.container_image,'payload_sha256':ssh_card.HASHES,
                'checks':results,'scope':'Guest rootfs/QEMU service emulation, not a complete kernel boot'}
        (work/'results.json').write_text(json.dumps(record,indent=2)+'\n')
        print('Results: '+str(work/'results.json'),flush=True)
    finally:
        p=subprocess.run([args.engine,'logs',name],capture_output=True,text=True)
        (work/'container.log').write_text(p.stdout+p.stderr)
        stop()


if __name__=='__main__':
    main()
