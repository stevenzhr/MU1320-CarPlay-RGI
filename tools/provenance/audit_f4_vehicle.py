#!/usr/bin/env python3
"""Audit the returned F4 renderer trial (run4) against the trial's acceptance checks.

Reads resource/private/vehicle-dump/f4-render-v1-run4/ and writes reports/f4-render-vehicle-v1.json.
Photos are judged by the user's OBSERVATIONS file; this script checks the machine evidence
(dmdt snapshots, renderer/feeder logs, sloginfo) and that it agrees with those observations.
"""
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DUMP = BASE.parent / 'resource/private/vehicle-dump/f4-render-v1-run4'
OUT = BASE / 'reports/f4-render-vehicle-v1.json'
STOCK = '20 102 101 33'
TEST = '98 102 101 33'
SNAPS = ['baseline-stock', 'registered-not-composed', 'idle-transparent', 'grid', 'turn-right', 'turn-left',
         'roundabout', 'uturn', 'arrived', 'after-link-loss', 'renderer-exited', 'restarted',
         'renderer-killed', 'restored-stock']
# expected (cluster context, displayable 98 present) per snapshot
EXPECT = {'baseline-stock': ('74', False), 'registered-not-composed': ('74', True),
          'renderer-exited': ('80', False), 'renderer-killed': ('80', False), 'restored-stock': ('74', False)}


def parse_gs(text):
    ctx, lst, main, state = None, [], None, 0
    for line in text.splitlines():
        f = line.split()
        if f[:2] == ['terminal:', 'LVDS1']:
            state = 'main'
        elif f[:2] == ['terminal:', 'LVDS2']:
            state = 'cl'
        elif f[:2] == ['context', 'id:']:
            if state == 'main':
                main = f[2]
            elif state == 'cl':
                ctx = f[2]
                state = 'list'
        elif state == 'list' and f and re.fullmatch(r'-?\d+', f[0]) and len(f) > 1 and f[1].startswith('('):
            lst.append(f[0])
        elif state == 'list':
            state = 'done'
    return ctx, ' '.join(lst), main


def parse_gd(text):
    rows = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 5 and re.fullmatch(r'-?\d+', f[0]) and f[3] == 'x':
            rows[f[0]] = f'{f[1]} {f[2]}x{f[4]}'
    return rows


def main():
    if not DUMP.exists():
        print('missing', DUMP)
        return 2
    run = next(DUMP.glob('run-*'))
    log = next(DUMP.glob('action-run-*.txt')).read_text()
    checks = {}

    def check(name, ok, detail=''):
        checks[name] = {'pass': bool(ok), 'detail': detail}

    check('run_completed', 'F4_RUN_COMPLETE' in log and 'CONTROL_EXIT=0' in log and 'STOP:' not in log)
    check('restore_result_stock', 'RESTORE_RESULT: STOCK_CLUSTER context=74 main=10' in log)
    check('no_stock_reversions', 'STOCK_CONTEXT_REVERSIONS: 0' in log)
    check('photo_prompts_13', 'PHOTO_PROMPTS: 13' in log)
    check('declared_test_context', f'DECLARED: 80 list=[{TEST}] gc_format=parsed' in log)
    check('switch_enter_and_back', f'SWITCHED_TO: 80 list=[{TEST}]' in log and f'SWITCHED_TO: 74 list=[{STOCK}]' in log)

    snaps = {}
    snap_dirs = [p for p in run.iterdir() if re.match(r's\d+-', p.name)]
    for d in sorted(snap_dirs, key=lambda p: int(re.match(r's(\d+)-', p.name).group(1))):
        name = d.name.split('-', 1)[1]
        ctx, lst, mainctx = parse_gs((d / 'gs.txt').read_text())
        gd = parse_gd((d / 'gd.txt').read_text())
        snaps[name] = {'ctx': ctx, 'list': lst, 'main': mainctx, 'd98': gd.get('98'), 'gd_ids': sorted(gd, key=int)}
    check('snapshot_sequence', list(snaps) == SNAPS, ' '.join(snaps))
    bad = []
    for name, s in snaps.items():
        ctx, d98 = EXPECT.get(name, ('80', True))
        want_list = STOCK if ctx == '74' else TEST
        if s['ctx'] != ctx or s['list'] != want_list or (s['d98'] is not None) != d98 or s['main'] != '10':
            bad.append(name)
        if d98 and s['d98'] != 'Software 328x181':
            bad.append(name + ':geometry')
    check('snapshots_match_expected_state', not bad, ', '.join(bad))

    feeds = re.findall(r'FEED_(\d+): exit=(\d+) F4FEED_RESULT scene=(\S+) rc=(\d+) ready=(\d+) frame_ready=(\d+)', log)
    check('feeders_all_ok', len(feeds) == 8 and all(f[1] == '0' and f[3] == '0' for f in feeds),
          ' '.join(f'{f[2]}:{f[1]}' for f in feeds))
    check('renderer_exit_codes', 'RENDERER_1_EXIT: 0' in log and 'RENDERER_2_EXIT: 137' in log)

    rlogs = ''.join(p.read_text() for p in sorted(run.glob('renderer-*.log')))
    check('renderer_egl_up', rlogs.count('maneuver_render: ready') == 2 and 'Adreno' in rlogs)
    check('renderer_rendered_all_icons',
          all(f'reveal from clear icon={i}' in rlogs for i in (2, 3, 6, 7)) and 'grid=ON' in rlogs and 'grid=OFF' in rlogs)
    check('renderer_self_clears_on_link_loss', rlogs.count('peer closed — clearing') >= 5)
    check('renderer_releases_window_on_shutdown', 'displayable 98 released' in rlogs)
    check('no_renderer_watchdog', 'watchdog TIMEOUT' not in rlogs)

    slog = next(DUMP.glob('collect-after-*/sloginfo.txt')).read_text()
    opened = len(re.findall(r'DisplayManager: new window available 98', slog))
    closed = len(re.findall(r'DisplayManager: window closed: 98', slog))
    check('displaymanager_adopt_release_98', opened == 2 and closed == 2, f'open={opened} closed={closed}')

    after = next(DUMP.glob('action-collect-after-*.txt')).read_text()
    check('after_run_stock_hmi_still_switches', 'DM_CLUSTER_CONTEXT: 72 list=[33] main=10' in after
          and 'DM_CONTEXT_80: DECLARED' in after and 'd98=ABSENT' in after,
          'stock HMI moved the cluster to 72 after the run; context 80 stays declared until reboot')
    restored = next(DUMP.glob('action-collect-restored-*.txt')).read_text()
    check('reboot_restores_baseline', 'F4_RESTORED_BASELINE: PASS' in restored
          and 'DM_CONTEXT_80: ABSENT gc_format=parsed (86/86)' in restored)

    obs = next(DUMP.glob('OBSERVATIONS*.txt')).read_text()
    check('user_idle_transparent', 'transparent when idle' in obs)
    check('user_grid_top_left_origin', 'TOP-LEFT corner' in obs and 'origin (0,0)' in obs)
    check('user_after_reboot_normal', 'After reboot: everything normal? (y/n) y' in obs)

    passed = all(c['pass'] for c in checks.values())
    result = {
        'status': 'F4_RENDERER_LAYER_AND_ROLLBACK_VERIFIED' if passed else 'F4_AUDIT_FAILED',
        'source': str(DUMP.relative_to(BASE.parent)),
        'checks': checks,
        'snapshots': snaps,
        'geometry': {
            'displayable_98': '328x181 Software, placed at cluster origin (0,0), unscaled (DisplayManager default; no Java setPosition/setCropping)',
            'grid_visible_cells_bottom_to_top': {'row1': '1(partial)-8', 'row2': '2-8', 'row3': '3-8', 'row4': '4/5-8',
                                                 'row5': '6-8 (5 sliver)', 'row6': 'none'},
            'clipping': 'VC top edge and curved top-left corner mask; bottom and right edges complete',
            'orientation_and_colour': 'correct (no flip, no R/B swap), alpha 0.6 blends over the map',
            'readable_scenes': ['turn-right', 'restarted turn-right'],
            'clipped_scenes': ['turn-left (head cut)', 'roundabout (ring cut)', 'uturn (arc cut)', 'arrived (marker cut)'],
        },
        'limitations': [
            'Position/cropping not set (needs DSI setPosition/setCropping from Java) -> F5.',
            'HUD not driven by F4; stock nav arrow after the run only believed OK, not exercised with an active route.',
            'Cluster update rate was whatever stock context 74 uses; no setUpdateRate call was needed for 98 to reach the VC.',
        ],
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    for name, c in checks.items():
        print(('PASS ' if c['pass'] else 'FAIL ') + name + (f'  [{c["detail"]}]' if c['detail'] and not c['pass'] else ''))
    print(result['status'])
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
