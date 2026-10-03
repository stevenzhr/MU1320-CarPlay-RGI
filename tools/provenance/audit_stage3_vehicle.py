#!/usr/bin/env python3
"""Classify Stage3 file operations separately from actual native execution."""
import hashlib,json,re
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];DUMP=BASE.parent/'resource/private/vehicle-dump'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    names=['stage3-install.txt','stage3-stock.txt','stage3-hook.txt','stage3-rollback.txt']
    logs={n:(DUMP/n).read_text() for n in names}
    for name,action in [('stage3-install.txt','install'),('stage3-rollback.txt','rollback')]:
        assert f'STAGE3_{action}_FILES_PASSED' in logs[name] and f'{action}_exit=0' in logs[name]
        assert 'MOUNTS_RESTORED: app=ro system=ro' in logs[name]
    hook=logs['stage3-hook.txt']
    assert 'TOKEN: PRESENT' in hook and 'NO_LOG' in hook
    assert 'STAGE3_HOOK_ONCE' not in hook and 'STAGE3_STOCK' not in hook
    assert not re.search(r'^\s*\d+\s+\S*dio_manager(?:\s|$)',hook,re.M)
    root=DUMP/'stage3-backup/mu1320-rgi-stage3-v1'
    expected={'backup/smartphone_integrator.json':BASE.parent/'resource/smartphone_integrator.json','carplay_startup.sh':BASE/'stage3/carplay_startup.sh','libcarplay_hook.so':BASE/'stage3/libcarplay_hook.so','config/dio_manager.json':BASE/'stage3/dio_manager.json','IDENTITY':BASE/'stage3/IDENTITY'}
    for name,original in expected.items():assert sha(root/name)==sha(original)
    report=dict(status='NATIVE_EXECUTION_NOT_CONFIRMED_TOKEN_UNCONSUMED',package_version=1,
        input_sha256={n:sha(DUMP/n) for n in names},returned_file_sha256={n:sha(root/n) for n in expected},
        install_file_checks_passed=True,rollback_file_checks_passed=True,mounts_restored_ro=True,
        system_and_active_si_contents_matched_stage3=True,arm_exit=0,token_still_present_at_collection=True,
        wrapper_log_present=False,native_log_present=False,dio_process_present_in_snapshot=False,
        original_si_backup_matches=True,payload_matches_delivered_files=True,
        connection_observation='User confirmed direct USB reconnect before and after arm; CarPlay was normal',
        post_rollback_reboot_confirmed=True,
        post_rollback_observation='User confirmed normal operation after rollback and restart',
        limitations=['USB connection and normal CarPlay were confirmed by user, but files contain no timestamps proving the child launch sequence.','No logs cannot distinguish no launch, launcher failure or early wrapper exit/logging failure.','Matching active config bytes do not prove a running SI parsed them.','stage3-stock.txt contains status only, not the reported pre-arm collect.'],
        next_step='Clarify connection method and timing; read-only inspect permissions, SI credentials/environment and system log; do not advance to VC/HUD.')
    (BASE/'reports/stage3-vehicle-v1.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status']+': install/rollback checks passed; no wrapper/native log; no dio in snapshot.')
if __name__=='__main__':main()
