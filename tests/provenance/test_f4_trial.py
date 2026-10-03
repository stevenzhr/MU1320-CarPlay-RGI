"""Host tests for the F4 renderer trial (feeder protocol + SD scripts with fake QNX tools)."""
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
STAGE = BASE / 'mu1320-f4-render-v1'
UPSTREAM = BASE.parent / 'mib2q-carplay-rgi'
FEED_SRC = BASE / 'f4-src/f4_feed.c'

FAKE_DMDT = r'''#!/usr/bin/env python3
import atexit, fcntl, io, json, os, sys, time
state_path = os.environ['F4_FAKE_STATE']
# Real dmdt leaves via _Exit() without flushing stdio: redirected output keeps only whole
# 10240-byte blocks unless the f4_unbuf.so shim is preloaded (seen on the car in v1).
_real, _buf = sys.stdout, io.StringIO()
sys.stdout = _buf
def _emit():
    data = _buf.getvalue()
    unbuffered = 'f4_unbuf.so' in os.environ.get('LD_PRELOAD', '') and not os.environ.get('F4_FAKE_NO_SHIM')
    if not unbuffered:
        data = data[:len(data) // 10240 * 10240]
    _real.write(data); _real.flush()
atexit.register(_emit)
NAMES = {16: 'DISPLAYABLE_HMI', 19: 'DISPLAYABLE_MAPVIEWER', 20: 'DISPLAYABLE_MAP_ROUTE_GUIDANCE',
         33: 'DISPLAYABLE_KOMBI_MAP_VIEW', 51: 'DISPLAYABLE_STREETVIEW'}
BASE_GD = [(-123, 'Overlay', 1024, 480), (16, 'Software', 1024, 480), (19, 'Software', 1024, 436),
           (20, 'Software', 328, 181), (33, 'Software', 1440, 455), (51, 'Software', 1024, 480),
           (101, 'Image', 210, 153), (102, 'Image', 210, 153)]
def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    out = os.popen('ps -o stat= -p %d' % pid).read().strip()
    return not out.startswith('Z')
with open(state_path + '.lock', 'w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    st = json.load(open(state_path))
    args = sys.argv[1:]
    st.setdefault('log', []).append(args)
    hang = st.get('hang')
    # 'dead' = displaymanager stops answering after this many calls (car: after "dmdt ts")
    dead = st.get('dead_after')
    calls = len(st['log'])
    if (hang and args and args[0] == hang) or (dead is not None and calls > dead) \
            or (args and args[0] == 'ts'):
        json.dump(st, open(state_path, 'w'))
        fcntl.flock(lock, fcntl.LOCK_UN)
        time.sleep(60)
    cmd = args[0] if args else ''
    ctxs = st['contexts']
    if cmd == 'gs':
        if st.get('revert_after') is not None and st['cluster'] != '74':
            st['revert_after'] -= 1
            if st['revert_after'] < 0:
                st['cluster'] = '74'; st['revert_after'] = None
        print('displaymanager reports the following system information:')
        print('\tnumber of displayables: 8\n\tnumber of displays: 2\n')
        print('\tdisplay: Main Display\n\tterminal: LVDS1\n\tsize: 1024 x 480\n\tcontext id: %s' % st.get('main', '10'))
        print('\t\t16 (DISPLAYABLE_HMI)\n')
        print('\tdisplay: Cluster Display\n\tterminal: LVDS2\n\tsize: 1440 x 542')
        print('\tcontext id: %s' % st['cluster'])
        for d in ctxs[st['cluster']]:
            print('\t\t%d (%s)' % (d, NAMES.get(d, '--')))
    elif cmd == 'gd':
        rows = list(BASE_GD)
        pid = st.get('d98_pid')
        if pid and alive(pid):
            rows.append((98, 'Software', 328, 181))
        print('displaymanager knows %d displayables:' % len(rows))
        print('\tID:\ttype:\t\tsize:\t\t\tdsi-name (guessed using ID & dsi 2.11.27):')
        print('-' * 60)
        for i, t, w, h in rows:
            print('\t%-4d\t%s\t%-4d x %-4d\t\t%s' % (i, t, w, h, NAMES.get(i, '--')))
    elif cmd == 'gc':
        print('displaymanager knows %d contexts:' % len(ctxs))
        print('ID:  | n')
        print('-----------------------------------')
        for cid in sorted(ctxs, key=int):
            print('%-4s  | %-4d ' % (cid, len(ctxs[cid])))
            for d in ctxs[cid]:
                print('\t%d (%s)' % (d, NAMES.get(d, '--')))
    elif cmd == 'dc':
        ctxs[args[1]] = [int(x) for x in args[2:]]
    elif cmd == 'sc':
        # internal display ids: 0 = main, 4 = cluster; anything else is silently ignored (car, v1 run3)
        if args[1] == '0':
            st['main'] = args[2]
        elif args[1] == '4' and args[2] in ctxs:
            st['cluster'] = args[2]
            if st.get('sc_hits_main'):
                st['main'] = '99'
            if args[2] == '80' and st.get('revert_once'):
                st['revert_after'] = st.pop('revert_once')
    else:
        print('unknown arguments. exiting')
        json.dump(st, open(state_path, 'w'))
        sys.exit(1)
    json.dump(st, open(state_path, 'w'))
'''

FAKE_RENDERER = r'''#!/usr/bin/env python3
import fcntl, json, os, signal, socket, struct, sys, time
state_path = os.environ['F4_FAKE_STATE']
mode = os.environ.get('F4_FAKE_RENDER', '')
port = int(os.environ.get('F4_FEED_PORT', '19800'))
rec = open(os.environ['F4_FAKE_RECORD'], 'a')
def update(**kw):
    with open(state_path + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        st = json.load(open(state_path))
        st.update(kw)
        json.dump(st, open(state_path, 'w'))
def out(msg):
    sys.stderr.write(msg + '\n'); sys.stderr.flush()
rec.write('START pid=%d cwd_atlas=%s graphics=%s ld=%s\n' % (
    os.getpid(), os.path.exists('flag_atlas.rgba'), os.environ.get('GRAPHICS_ROOT'),
    'set' if os.environ.get('LD_LIBRARY_PATH') else 'unset'))
rec.flush()
out('maneuver_render: starting 328x181')
if mode == 'init-fail':
    out('platform_qnx: FAIL eglInitialize'); sys.exit(1)
def term(*_):
    update(d98_pid=None); out('platform_qnx: caught SIGTERM'); sys.exit(0)
signal.signal(signal.SIGTERM, term)
update(d98_pid=os.getpid())
out('cluster_surface: window id=98 328x181 fmt=8 usage=0x20 nbuf=2 managed')
out('maneuver_render: ready, waiting for commands on :19800')
def pkt(code):
    return bytes([code]) + bytes(47)
while True:
    try:
        s = socket.create_connection(('127.0.0.1', port), timeout=0.3)
    except OSError:
        time.sleep(0.2); continue
    s.settimeout(0.2)
    s.sendall(pkt(0x81))
    announced = False; buf = b''; last_hb = time.time()
    while True:
        if time.time() - last_hb > 1:
            try: s.sendall(pkt(0x80))
            except OSError: break
            last_hb = time.time()
        try:
            data = s.recv(512)
        except socket.timeout:
            continue
        except OSError:
            break
        if not data:
            out('server: peer closed'); break
        buf += data
        while len(buf) >= 48:
            p, buf = buf[:48], buf[48:]
            rec.write('CMD ' + p.hex() + '\n'); rec.flush()
            if p[0] == 0x01 and mode != 'no-frame':
                if not announced:
                    announced = True; s.sendall(pkt(0x82))
            elif p[0] == 0x07:
                announced = False; s.sendall(pkt(0x83))
            elif p[0] == 0x03:
                update(d98_pid=None); out('engine: shutdown command received'); s.close(); sys.exit(0)
    s.close()
'''

FAKE_PIDIN = r'''#!/bin/sh
if [ "$1" = -p ]; then ps -o command= -p "$2"; exit $?; fi
ps -axo pid,ppid,command
'''


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def cksum_pair(path):
    out = subprocess.check_output(['cksum', str(path)], text=True).split()
    return out[0], out[1]


class F4Fixture:
    def __init__(self, test):
        self.root = Path(tempfile.mkdtemp(prefix='f4t')).resolve()
        test.addCleanup(self.close)
        self.sd_root = self.root / 'fs/sda0'
        self.sd = self.sd_root / 'mu1320-f4-render-v1'
        self.vehicle = self.root / 'vehicle'
        self.cmds = self.root / 'cmds'
        self.cmds.mkdir()
        shutil.copytree(STAGE, self.sd, ignore=shutil.ignore_patterns('out'))
        self.state = self.root / 'dm-state.json'
        self.record = self.root / 'renderer-record.txt'
        self.record.touch()
        self.sdflag = self.root / 'sd.flag'
        self.sdflag.write_text('ro\n')
        self.port = free_port()
        self.write_state()

        dmdt = self.vehicle / 'mnt/app/eso/bin/apps/dmdt'
        dmdt.parent.mkdir(parents=True)
        dmdt.write_text(FAKE_DMDT)
        dmdt.chmod(0o755)
        for rel in ('proc/boot/libc.so.3', 'proc/boot/libm.so.2', 'lib/libsocket.so.3',
                    'proc/boot/libscreen.so.1', 'proc/boot/libEGL.so.1', 'proc/boot/libGLESv2.so.1'):
            path = self.vehicle / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fake ' + rel + '\n')
        (self.vehicle / 'tmp').mkdir()

        renderer = self.sd / 'maneuver_render'
        renderer.write_text(FAKE_RENDERER)
        renderer.chmod(0o755)
        feed = self.sd / 'f4_feed'
        subprocess.check_call(['cc', '-std=gnu99', '-O2', '-Wall', '-Werror', str(FEED_SRC), '-o', str(feed)])
        mount_state = self.sd / 'mount_state'
        mount_state.write_text('#!/bin/sh\ncat "$SD_FLAG"\n')
        mount_state.chmod(0o755)

        self.fake('id', '#!/bin/sh\necho 0\n')
        self.fake('uname', '#!/bin/sh\necho "QNX mmx 6.5.0 2018/02/05-11:11:12CET APQ8064_65536_MMX2_Rev:1 armle"\n')
        self.fake('pidin', FAKE_PIDIN)
        self.fake('sloginfo', '#!/bin/sh\necho "fake slog"\n')
        self.fake('sleep', '#!/bin/sh\nexec /bin/sleep "$(awk "BEGIN{print $1 * 0.1}")"\n')
        self.fake('mount', '#!/bin/sh\ncase "$1" in -uw) echo rw > "$SD_FLAG" ;; -ur) echo ro > "$SD_FLAG" ;; '
                           '*) exit 1 ;; esac\n')

        self.control = self.sd / 'control.sh'
        self.control.write_text(self.pin(self.rewrite(self.control.read_text())))
        wrapper = self.sd / 'f4_trial.sh'
        text = self.rewrite(wrapper.read_text())
        text = text.replace('/fs/sda0/*) sd=/fs/sda0', f'{self.sd_root}/*) sd={self.sd_root}')
        text = text.replace("'2952412687'", "'%s'" % cksum_pair(mount_state)[0])
        text = text.replace("'7302'", "'%s'" % cksum_pair(mount_state)[1])
        old = re.search(r"\[ \"\$\{1:-\}\" = '(\d+)' \] && \[ \"\$\{2:-\}\" = '(\d+)' \] \|\| fail 'control", text)
        new = cksum_pair(self.control)
        text = text.replace(f"'{old.group(1)}' ] && [ \"${{2:-}}\" = '{old.group(2)}'",
                            f"'{new[0]}' ] && [ \"${{2:-}}\" = '{new[1]}'")
        wrapper.write_text(text)
        self.wrapper = wrapper

    def close(self):
        subprocess.run(['pkill', '-f', str(self.sd / 'maneuver_render')], check=False)
        shutil.rmtree(self.root, ignore_errors=True)

    def fake(self, name, text):
        path = self.cmds / name
        path.write_text(text)
        path.chmod(0o755)

    def write_state(self, **kw):
        st = {'cluster': '74', 'contexts': {'0': [16], '72': [20, 33], '74': [20, 102, 101, 33]},
              'd98_pid': None, 'log': []}
        st.update(kw)
        self.state.write_text(json.dumps(st))

    def read_state(self):
        return json.loads(self.state.read_text())

    def rewrite(self, text):
        text = re.sub(r'^PATH=.*$', f'PATH={self.cmds}:/usr/bin:/bin', text, flags=re.M)
        text = re.sub(r'/mnt/app|/proc/boot|/lib/libsocket\.so\.3|/tmp',
                      lambda m: str(self.vehicle / m.group().lstrip('/')), text)
        text = text.replace('HOLD=20', 'HOLD=1').replace('SETTLE=3', 'SETTLE=1')
        text = text.replace('FEED_MARGIN=10', 'FEED_MARGIN=1')
        return text

    def pin(self, text):
        def repl(match):
            raw = match.group(4)
            path = Path(raw.replace('$stage_dir', str(self.sd)).replace(
                '$DMDT', str(self.vehicle / 'mnt/app/eso/bin/apps/dmdt')))
            c, n = cksum_pair(path)
            return f'check {c} {n} {match.group(3)}{raw}{match.group(3)}'
        return re.sub(r'check (\d+) (\d+) ("?)([^"\s]+)\3', repl, text)

    def env(self, **extra):
        env = dict(os.environ, F4_FAKE_STATE=str(self.state), F4_FAKE_RECORD=str(self.record),
                   F4_FEED_PORT=str(self.port), SD_FLAG=str(self.sdflag))
        env.update(extra)
        return env

    def trial(self, *args, timeout=240, **extra):
        return subprocess.run(['/bin/sh', str(self.wrapper), *args], env=self.env(**extra),
                              capture_output=True, text=True, timeout=timeout)

    def control_run(self, *args, **extra):
        (self.sd / 'out').mkdir(exist_ok=True)
        return subprocess.run(['/bin/sh', str(self.control), *args], env=self.env(**extra),
                              capture_output=True, text=True, timeout=120)

    def dm_commands(self):
        return [a[0] for a in self.read_state()['log']]

    def logs(self, pattern):
        return sorted((self.sd / 'out').glob(pattern))


class FeedProtocolTests(unittest.TestCase):
    def test_constants_match_upstream_protocol(self):
        proto = (UPSTREAM / 'maneuver_render/protocol.h').read_text()
        maneuver = (UPSTREAM / 'maneuver_render/maneuver.h').read_text()
        feed = FEED_SRC.read_text()
        for name in ('CMD_MANEUVER', 'CMD_SHUTDOWN', 'CMD_DEBUG', 'CMD_CLEAR', 'EVT_HEARTBEAT',
                     'EVT_READY', 'EVT_FRAME_READY', 'EVT_FRAME_CLEARED', 'MAN_FLAG_BARGRAPH'):
            up = re.search(r'#define %s\s+(0x[0-9A-Fa-f]+|\d+)' % name, proto).group(1)
            mine = re.search(r'#define %s\s+(0x[0-9A-Fa-f]+|\d+)' % name, feed).group(1)
            self.assertEqual(int(up, 0), int(mine, 0), name)
        for name in ('ICON_TURN', 'ICON_UTURN', 'ICON_ROUNDABOUT', 'ICON_ARRIVED'):
            up = re.search(r'#define %s\s+(\d+)' % name, maneuver).group(1)
            mine = re.search(r'#define %s\s+(\d+)' % name, feed).group(1)
            self.assertEqual(up, mine, name)
        self.assertIn('#define CR_PKT_SIZE         48', proto)
        self.assertIn('#define CR_TCP_PORT         19800', proto)
        self.assertIn('payload[0] == 2', (UPSTREAM / 'maneuver_render/main.c').read_text())

    def test_every_scene_against_fake_renderer(self):
        fx = F4Fixture(self)
        feed = fx.sd / 'f4_feed'
        proc = subprocess.Popen([str(fx.sd / 'maneuver_render')], env=fx.env(), cwd=fx.root,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        expected = {
            ('turn', '90', '8'): '0201005a',   # icon 2, dir +1, angle 90 (payload[0..3])
            ('turn', '-90'): '02ffffa6',
            ('roundabout', '135'): '06010087',
            ('uturn',): '03ff00b4',
            ('arrived',): '07000000',
        }
        for scene, head in expected.items():
            fx.record.write_text('')
            res = subprocess.run([str(feed), '1', *scene], env=fx.env(), capture_output=True,
                                 text=True, timeout=30)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn('rc=0 ready=1 frame_ready=1', res.stdout)
            cmds = [l.split()[1] for l in fx.record.read_text().splitlines() if l.startswith('CMD ')]
            self.assertEqual(cmds[0][:2], '01')
            self.assertEqual(cmds[0][4:12], head, scene)
            if scene[0] == 'turn' and len(scene) == 3:
                self.assertEqual(cmds[0][2:4], '02')              # MAN_FLAG_BARGRAPH
                self.assertEqual(cmds[0][(2 + 44) * 2:(2 + 46) * 2], '0801')
            if scene[0] == 'roundabout':
                payload = bytes.fromhex(cmds[0])[2:]
                self.assertEqual(payload[5], 4)
                self.assertEqual([int.from_bytes(payload[6 + 2 * i:8 + 2 * i], 'big', signed=True)
                                  for i in range(4)], [-90, 0, 90, 180])
        fx.record.write_text('')
        res = subprocess.run([str(feed), '1', 'grid'], env=fx.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stdout)
        cmds = [l.split()[1][:6] for l in fx.record.read_text().splitlines() if l.startswith('CMD ')]
        self.assertEqual(cmds, ['050002', '010002', '050002', '070000'])   # grid on, turn, grid off, clear
        self.assertIn('cleared=1', res.stdout)
        res = subprocess.run([str(feed), '1', 'clear'], env=fx.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stdout)
        res = subprocess.run([str(feed), '5', 'shutdown'], env=fx.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn('peer_closed=1', res.stdout)
        proc.wait(timeout=5)
        self.assertEqual(proc.returncode, 0)

    def test_usage_and_accept_timeout_codes(self):
        fx = F4Fixture(self)
        feed = str(fx.sd / 'f4_feed')
        for bad in (['0', 'idle'], ['1', 'turn'], ['1', 'turn', '200'], ['1', 'turn', '9', '17'],
                    ['1', 'nope'], ['1', 'idle', 'x'], ['121', 'idle']):
            self.assertEqual(subprocess.run([feed, *bad], capture_output=True).returncode, 2, bad)
        with socket.socket() as busy:
            busy.bind(('127.0.0.1', fx.port))
            busy.listen(1)
            res = subprocess.run([feed, '1', 'idle'], env=fx.env(), capture_output=True, text=True)
            self.assertEqual(res.returncode, 3, res.stdout)


class F4TrialTests(unittest.TestCase):
    def setUp(self):
        self.fx = F4Fixture(self)

    def assert_restored(self):
        st = self.fx.read_state()
        self.assertEqual(st['cluster'], '74')
        pid = st.get('d98_pid')
        if pid:   # SIGKILLed fake cannot unregister; DisplayManager drops a dead client's window
            self.assertNotEqual(subprocess.run(['kill', '-0', str(pid)], capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(['pgrep', '-f', str(self.fx.sd / 'maneuver_render')],
                                        capture_output=True).returncode, 1)

    def test_status_reports_stock_baseline(self):
        res = self.fx.trial('status')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn('DM_CLUSTER_CONTEXT: 74 list=[20 102 101 33] main=10', res.stdout)
        self.assertIn('d98=ABSENT', res.stdout)
        self.assertIn('DM_CONTEXT_80: ABSENT gc_format=parsed (3/3) stock74=[20 102 101 33]', res.stdout)
        self.assertIn('F4_RENDERER: ABSENT', res.stdout)
        self.assertIn('SD_MOUNT_RESTORED', res.stdout)
        self.assertIn('F4_TRIAL_ACTION_PASSED', res.stdout)
        self.assertEqual(self.fx.sdflag.read_text().strip(), 'ro')
        self.assertEqual(set(self.fx.dm_commands()), {'gs', 'gd', 'gc'})

    def test_full_run_passes_and_restores(self):
        res = self.fx.trial('run')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        live = res.stdout
        self.assertIn('F4_TRIAL_ACTION_PASSED', live)
        self.assertIn('F4_RUN_COMPLETE', live)
        self.assertIn('RESTORE_RESULT: STOCK_CLUSTER context=74 main=10', live)
        self.assertIn('BASELINE_CONTEXT: 74 list=[20 102 101 33] main=10', live)
        self.assertEqual(len(re.findall(r'^PHOTO \d+ ', live, re.M)), 13)
        log = self.fx.logs('action-run-*.txt')[0].read_text()
        self.assertIn('CONTROL_EXIT=0', log)
        self.assertIn('STOCK_CONTEXT_REVERSIONS: 0', log)
        self.assertIn('RENDERER_1_EXIT: 0', log)
        self.assertRegex(log, r'RENDERER_2_EXIT: (137|265)')
        self.assertIn('DECLARED: 80 list=[98 102 101 33] gc_format=parsed', log)
        self.assertEqual(len(re.findall(r'FEED_\d+: exit=0 F4FEED_RESULT', log)), 8)
        self.assertNotIn('STOP:', log)
        self.assert_restored()
        st = self.fx.read_state()
        self.assertEqual(st['contexts']['80'], [98, 102, 101, 33])
        self.assertEqual([a for a in st['log'] if a[0] == 'sc'], [['sc', '4', '80'], ['sc', '4', '74']])
        self.assertEqual(st.get('main', '10'), '10')
        run = self.fx.logs('run-*')[0]
        snaps = sorted(p.name for p in run.iterdir() if re.match(r's\d+-', p.name))
        self.assertEqual(len(snaps), 14)
        grid = next(run / s for s in snaps if s.endswith('-grid'))
        self.assertIn('context id: 80', (grid / 'gs.txt').read_text())
        self.assertNotIn('ts', self.fx.dm_commands())
        rec = self.fx.record.read_text()
        self.assertEqual(rec.count('START '), 2)
        self.assertIn('cwd_atlas=True graphics=', rec)
        self.assertTrue((run / 'flag_atlas.rgba').is_file())
        self.assertEqual(list((self.fx.vehicle / 'tmp').iterdir()), [])
        self.assertEqual(self.fx.sdflag.read_text().strip(), 'ro')

    def test_preflight_stops_before_any_change(self):
        cases = [
            (dict(cluster='73', contexts={'0': [16], '73': [20, 101, 102], '74': [20, 102, 101, 33]}),
             'cluster context 73 [20 101 102] has no map (33)'),
            (dict(contexts={'0': [16], '74': [20, 102, 101, 33], '80': [1]}), 'context 80 already declared'),
            (dict(cluster='80', contexts={'0': [16], '74': [20, 102, 101, 33], '80': [98, 33]}),
             'already on context 80'),
        ]
        for state, message in cases:
            with self.subTest(message=message):
                self.fx.write_state(**state)
                res = self.fx.trial('run')
                self.assertNotEqual(res.returncode, 0)
                self.assertRegex(res.stdout + res.stderr, 'STOP: .*' + re.escape(message))
                self.assertFalse({'dc', 'sc'} & set(self.fx.dm_commands()))
                self.assertNotIn('START ', self.fx.record.read_text())
                self.assertRegex(res.stdout, r'RESTORE_RESULT: (UNCHANGED|STOCK_CLUSTER)')
        live = subprocess.Popen(['/bin/sleep', '30'])
        self.addCleanup(live.kill)
        self.fx.write_state(d98_pid=live.pid)
        res = self.fx.trial('run')
        self.assertIn('STOP: displayable 98 already exists', res.stdout + res.stderr)
        self.assertFalse({'dc', 'sc'} & set(self.fx.dm_commands()))

    def test_stock_reversion_is_reasserted_and_counted(self):
        self.fx.write_state(revert_once=3)
        res = self.fx.trial('run')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn('STOCK_CONTEXT_CHANGE', res.stdout)
        log = self.fx.logs('action-run-*.txt')[0].read_text()
        self.assertIn('STOCK_CONTEXT_REVERSIONS: 1', log)
        self.assert_restored()

    def test_renderer_init_failure_never_switches(self):
        res = self.fx.trial('run', F4_FAKE_RENDER='init-fail')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('STOP: renderer 1 exited during init', res.stdout)
        self.assertIn('RESTORE_RESULT: STOCK_CLUSTER', res.stdout)
        self.assertNotIn('sc', self.fx.dm_commands())
        self.assert_restored()

    def test_failure_after_switch_restores_stock(self):
        res = self.fx.trial('run', F4_FAKE_RENDER='no-frame')
        self.assertNotEqual(res.returncode, 0)
        self.assertRegex(res.stdout, r'STOP: feeder 1(: no| ended before) EVT_FRAME_READY')
        self.assertIn('RUN_ABORTED', res.stdout)
        self.assertIn('RESTORE: cluster on context 80 -> switching to 74', self.fx.logs('action-run-*.txt')[0].read_text())
        self.assertIn('RESTORE_RESULT: STOCK_CLUSTER', res.stdout)
        self.assert_restored()

    def test_restore_switches_back_only_from_ours(self):
        self.fx.write_state(cluster='72')
        res = self.fx.trial('restore')
        self.assertEqual(res.returncode, 1)
        self.assertNotIn('sc', self.fx.dm_commands())
        self.assertIn('RESTORE_RESULT: NOT_STOCK', res.stdout)
        ctxs = {'0': [16], '74': [20, 102, 101, 33], '80': [98, 102, 101, 33]}
        self.fx.write_state(cluster='80', contexts=ctxs)
        res = self.fx.trial('restore')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(['sc', '4', '74'], self.fx.read_state()['log'])
        self.assertIn('RESTORE_RESULT: STOCK_CLUSTER', res.stdout)

    def test_restore_stops_leftover_renderer(self):
        proc = subprocess.Popen([str(self.fx.sd / 'maneuver_render')], env=self.fx.env(),
                                cwd=self.fx.root, stderr=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        (self.fx.vehicle / 'tmp/mu1320-f4-v1.renderer.pid').write_text(f'{proc.pid}\n')
        for _ in range(50):
            if self.fx.read_state().get('d98_pid'):
                break
            time.sleep(0.1)
        res = self.fx.trial('restore')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        proc.wait(timeout=5)
        self.assertIn('RESTORE: stopping renderer', self.fx.logs('action-restore-*.txt')[0].read_text())
        self.assert_restored()

    def test_collect_restored_detects_leftover_context(self):
        res = self.fx.trial('collect', 'restored')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn('F4_RESTORED_BASELINE: PASS', res.stdout)
        self.assertTrue(self.fx.logs('collect-restored-*/sloginfo.txt'))
        self.fx.write_state(contexts={'0': [16], '74': [20, 102, 101, 33], '80': [98, 102, 101, 33]})
        res = self.fx.trial('collect', 'restored')
        self.assertIn('F4_RESTORED_BASELINE: FAIL', res.stdout)

    def test_baseline_72_is_recorded_and_restored(self):
        self.fx.write_state(cluster='72', contexts={'0': [16], '72': [20, 33], '74': [20, 102, 101, 33]})
        res = self.fx.trial('run')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn('BASELINE_CONTEXT: 72 list=[20 33] main=10', res.stdout)
        self.assertIn('RESTORE_RESULT: STOCK_CLUSTER context=72', res.stdout)
        self.assertEqual(self.fx.read_state()['cluster'], '72')
        self.assertFalse((self.fx.vehicle / 'tmp/mu1320-f4-v1.base').exists())

    def test_restore_after_interrupted_run_uses_recorded_baseline(self):
        ctxs = {'0': [16], '72': [20, 33], '74': [20, 102, 101, 33], '80': [98, 102, 101, 33]}
        self.fx.write_state(cluster='80', contexts=ctxs)
        (self.fx.vehicle / 'tmp/mu1320-f4-v1.base').write_text('72 20 33\n')
        res = self.fx.trial('restore')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn(['sc', '4', '72'], self.fx.read_state()['log'])
        self.assertIn('RESTORE_RESULT: STOCK_CLUSTER context=72', res.stdout)

    def test_main_display_change_stops_and_is_restored(self):
        self.fx.write_state(sc_hits_main=True)
        res = self.fx.trial('run')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('STOP: main display context changed to 99 (was 10) after sc 4 80', res.stdout)
        st = self.fx.read_state()
        self.assertIn(['sc', '0', '10'], st['log'])
        self.assertEqual((st['main'], st['cluster']), ('10', '74'))
        self.assert_restored()

    def test_missing_stdout_shim_is_detected_before_any_change(self):
        # Reproduces the v1 car failure: gs/gd empty, gc cut at a 10240-byte boundary.
        ctxs = {str(i): [16, 20 + i % 30] for i in range(-10, 400)}
        ctxs['74'] = [20, 102, 101, 33]
        self.fx.write_state(contexts=ctxs)
        res = self.fx.trial('run', F4_FAKE_NO_SHIM='1')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('STOP: dmdt gd output incomplete (0/?)', res.stdout)
        self.assertFalse({'dc', 'sc'} & set(self.fx.dm_commands()))
        gc = self.fx.logs('run-*')[0] / 'p0-before/gc.txt'
        self.assertGreater(gc.stat().st_size, 0)
        self.assertEqual(gc.stat().st_size % 10240, 0)
        res = self.fx.trial('status', F4_FAKE_NO_SHIM='1')
        self.assertIn('gc_format=incomplete', res.stdout)
        res = self.fx.trial('status')
        self.assertIn('gc_format=parsed (410/410)', res.stdout)
        self.assertIn('complete=yes (8/8)', res.stdout)

    def test_displaymanager_going_silent_after_preflight_stops_before_renderer(self):
        # v1 run2 on the car: displaymanager stopped answering right after preflight.
        # p0 query uses 3 calls; the 4th (first snapshot gs) hangs.
        self.fx.write_state(dead_after=3)
        start = time.time()
        res = self.fx.trial('run', timeout=120)
        self.assertLess(time.time() - start, 60)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('STOP: displaymanager did not answer dmdt gs within 10 s', res.stdout)
        self.assertNotIn('START ', self.fx.record.read_text())
        self.assertNotIn('PHOTO 1', res.stdout)
        self.assertFalse({'dc', 'sc'} & set(self.fx.dm_commands()))

    def test_dmdt_hang_is_bounded(self):
        self.fx.write_state(hang='gs')
        start = time.time()
        res = self.fx.trial('run', timeout=120)
        self.assertLess(time.time() - start, 60)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('STOP: displaymanager did not answer dmdt gs within 10 s', res.stdout + res.stderr)
        self.assertFalse((self.fx.vehicle / 'tmp/mu1320-f4-v1.base').exists())
        self.assertFalse({'dc', 'sc'} & set(self.fx.dm_commands()))

    def test_wrapper_rejects_modified_control(self):
        with self.fx.control.open('a') as stream:
            stream.write('# tampered\n')
        res = self.fx.trial('status')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('STOP: control checksum', res.stdout + res.stderr)


class F4StaticTests(unittest.TestCase):
    def test_parsers_on_real_car_dmdt_output(self):
        dump = BASE.parent / 'resource/private/vehicle-dump'
        car_gc = dump / 'f4-render-v1/run-8614015/p0-before/gc.txt'
        if not (dump / 'dmdt_gs.txt').exists() or not car_gc.exists():
            self.skipTest('vehicle dump not present')
        control = (STAGE / 'control.sh').read_text()
        funcs = ['CTX=80']
        for name in ('parse_gs', 'parse_gd', 'parse_gc', 'ctx_declared'):
            start = control.index(name + '() {')
            funcs.append(control[start:control.index('\n}\n', start) + 3])
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / 'p.sh'
            lib.write_text('\n'.join(funcs))
            # complete gc = the car's 10240-byte capture cut before the partial context 77
            text = car_gc.read_text()
            text = text[:text.rfind('\n\t77 ')] + '\n'
            full = Path(tmp) / 'gc.txt'
            full.write_text(text.replace('knows 86 contexts', 'knows 84 contexts'))
            script = (f'. {lib}; parse_gs {dump}/dmdt_gs.txt; echo "$CL_CTX [$CL_LIST]"; '
                      f'parse_gd {dump}/dmdt_gd.txt; echo "$GD_COMPLETE $GD_COUNT [$GD_IDS]"; '
                      f'parse_gc {car_gc}; echo "$GC_FORMAT $GC_COUNT"; '
                      f'parse_gc {full}; echo "$GC_FORMAT $GC_COUNT [$GC_STOCK]"; '
                      f'if ctx_declared {full}; then echo declared; else echo absent; fi')
            out = subprocess.check_output(['/bin/sh', '-c', script], text=True).splitlines()
        self.assertEqual(out, ['74 [20 102 101 33]', 'yes 8/8 [-123 16 19 20 33 51 101 102]',
                               'incomplete 85/86', 'parsed 84/84 [20 102 101 33]', 'absent'])

    def test_staged_folder_matches_manifest_and_prepare(self):
        files = sorted(p.name for p in STAGE.iterdir() if p.is_file())
        self.assertEqual(files, ['OBSERVATIONS-TEMPLATE.txt', 'README.md', 'SHA256SUMS', 'control.sh',
                                 'f4_feed', 'f4_feed.c', 'f4_trial.sh', 'f4_unbuf.c', 'f4_unbuf.so',
                                 'flag_atlas.rgba', 'maneuver_render', 'mount_state', 'mount_state.c'])
        res = subprocess.run(['shasum', '-a', '256', '-c', 'SHA256SUMS'], cwd=STAGE, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'stage'
            subprocess.check_call(['python3', str(BASE / 'scripts/prepare_f4_trial.py'), '--output', str(out),
                                   '--report', str(Path(tmp) / 'r.json')], stdout=subprocess.DEVNULL)
            for name in files:
                self.assertEqual((out / name).read_bytes(), (STAGE / name).read_bytes(), name)
        build = json.loads((BASE / 'reports/f4-render-build.json').read_text())
        self.assertTrue(build['renderer_matches_2026_09_22_native_probe'])
        self.assertEqual((STAGE / 'mount_state').read_bytes(), (BASE / 'mu1320-f3-bap-v2/mount_state').read_bytes())

    def test_vehicle_scripts_avoid_known_qnx_traps_and_persistent_writes(self):
        for name in ('control.sh', 'f4_trial.sh'):
            text = (STAGE / name).read_text()
            for number, line in enumerate(text.splitlines(), 1):
                code = line.split('#', 1)[0] if not line.lstrip().startswith('#') else ''
                if '&&' in code and '||' not in code and not re.match(r'\s*(if|while|elif)\b', code) \
                        and 'cd "$stage_dir" && pwd' not in code:
                    self.fail(f'{name}:{number}: bare && under set -e: {line}')
                self.assertNotIn('IFS= read', code, f'{name}:{number}')
                self.assertNotRegex(code, r'\b(awk|sed|tee)\b', f'{name}:{number}')
            body = '\n'.join(l for l in text.splitlines() if not l.startswith('PATH='))
            self.assertNotRegex(body, r'(mkdir|cp|mv|chmod|rm)[^\n]*/mnt/(app|system)')
            self.assertNotRegex(text, r'mkdir[^\n]*(\$PREFIX|/tmp)')
            self.assertNotIn('mount -uw /mnt', text)
        control = (STAGE / 'control.sh').read_text()
        code = '\n'.join(l for l in control.splitlines() if not l.lstrip().startswith('#') and not l.startswith('PATH='))
        self.assertEqual(re.findall(r'/mnt/app[^\s:"]*', code),
                         ['/mnt/app/eso/bin/apps/dmdt'])
        self.assertIn("TEST_LIST='98 102 101 33'", control)
        self.assertIn('CTX=80', control)
        self.assertIn('DISPLAY_ID=4\nMAIN_ID=0', control)
        self.assertNotRegex(control, r'dm [^\n]* ts ')
        self.assertIn('LD_PRELOAD=$stage_dir/f4_unbuf.so LD_LIBRARY_PATH=/proc/boot:/lib exec "$DMDT"', control)
        self.assertEqual(control.count('f4_unbuf.so'), 3)   # checksum, comment, dmdt only


if __name__ == '__main__':
    unittest.main()
