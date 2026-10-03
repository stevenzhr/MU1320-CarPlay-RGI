#!/usr/bin/env python3
"""Summarize supplied read-only transcripts; never grants installation readiness."""
import hashlib
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
RESOURCE = BASE.parent / 'resource'


def parse_preflight(transcript, script):
    rows = script.split("done <<'BASELINE_CKSUMS'\n", 1)[1].split('\nBASELINE_CKSUMS', 1)[0]
    expected = [line.split(maxsplit=2)[2] for line in rows.splitlines()]
    lines = transcript.splitlines()
    files = {path: lines.count('PASS: ' + path) == 1 for path in expected}
    configs = {name: 'PASS: config contents identical: ' + name +
               ' (does not prove path aliases)' in lines
               for name in ('dio_manager.json', 'smartphone_integrator.json')}
    exits = re.findall(r'(?:^|\n)preflight_exit=(\d+)(?=\D|$)', transcript)
    failed = any(line.startswith(('FAIL:', 'STOP:', 'BASELINE_CHECK_FAILED')) for line in lines)
    passed = (bool(files) and all(files.values()) and all(configs.values()) and
              'PASS: QNX 6.5 ARM platform string' in lines and
              sum(line.startswith('BASELINE_CHECK_PASSED:') for line in lines) == 1 and
              exits == ['0'] and not failed)
    return {'status': 'PASS' if passed else 'FAIL_OR_INCOMPLETE',
            'file_checks': files, 'configuration_content_checks': configs,
            'exit_codes': exits, 'failure_marker_found': failed,
            'path_alias_proven': False, 'installation_readiness_proven': False}


def command_output(transcript, command):
    # The supplied terminal prompt is root@mmx:<cwd>>. Do not execute any text.
    pattern = r'(?:^|\n)root@mmx:[^\n>]*> ' + re.escape(command) + r'\r?\n'
    match = re.search(pattern, transcript)
    if not match:
        return None
    return re.split(r'\r?\nroot@mmx:[^\n>]*> ', transcript[match.end():], maxsplit=1)[0].strip()


def parse_recovery(transcript):
    entries = {}
    for path in ('/etc/inetd.conf', '/mnt/system/etc/inetd.conf'):
        output = command_output(transcript, 'cat ' + path)
        entries[path] = bool(output and re.search(
            r'^ssh\s+stream\s+tcp\s+nowait\s+root\s+'
            r'/net/mmx/mnt/app/eso/hmi/engdefs/scripts/ssh/usr/sbin/start_sshd\s+in\.sshd$',
            output, re.M))
    wrapper = command_output(transcript, 'cat /net/mmx/mnt/app/eso/hmi/engdefs/scripts/ssh/usr/sbin/start_sshd')
    mount_output = command_output(transcript, 'mount')
    return {'inetd_ssh_entries': entries,
            'wrapper_invokes_sshd_in_inetd_mode': bool(wrapper and
                '${SSD_DIR}/usr/sbin/sshd -i -f ${SSD_DIR}/etc/sshd_config' in wrapper),
            'mount_output_present': bool(mount_output),
            'inetd_boot_origin_proven': False,
            'hmi_failure_recovery_verified': False}


def main():
    paths = {name: RESOURCE / 'private/vehicle-dump' / name
             for name in ('preflight.txt', 'recovery_readonly.txt')}
    result = {
        'date': '2026-09-22',
        'inputs': {name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                          'size': path.stat().st_size} for name, path in paths.items()},
        'preflight': parse_preflight(paths['preflight.txt'].read_text(),
                                    (BASE / 'preflight/preflight.sh').read_text()),
        'recovery': parse_recovery(paths['recovery_readonly.txt'].read_text()),
        'user_observation': {
            'source': 'User report in this task; not inferred from terminal output',
            'cold_start_root_ssh_without_engineering_menu_or_toolbox': True,
            'network': 'Vehicle Wi-Fi hotspot',
            'hmi_failed_during_test': False,
            'carplay_phone_absence_explicitly_confirmed': False},
        'vehicle_writes_performed_by_assistant': False,
        'limitations': ['Transcript evidence, not a live connection or cryptographic attestation.',
                        'Normal cold-start hotspot/SSH success is not HMI-failure recovery.',
                        'No mount output was supplied in this recovery transcript.']}
    (BASE / 'reports/vehicle-preflight-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Preflight:', result['preflight']['status'])
    print('Expected file checks:', len(result['preflight']['file_checks']))
    print('inetd entries:', all(result['recovery']['inetd_ssh_entries'].values()))
    print('Mount output present:', result['recovery']['mount_output_present'])
    return 0 if result['preflight']['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
