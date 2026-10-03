#!/usr/bin/env python3
"""Audit supplied Stage2 evidence; do not infer post-rollback boot from file status."""
import hashlib,json
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
DUMP=BASE.parent/'resource/private/vehicle-dump'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    names=['stage2-install.txt','stage2-after-boot.txt','stage2-collect.txt','stage2-rollback.txt']
    logs={n:(DUMP/n).read_text() for n in names}
    for text in logs.values():assert 'STOP:' not in text and '[CP/E]' not in text
    for n,action in [('stage2-install.txt','install'),('stage2-rollback.txt','rollback')]:
        text=logs[n]
        marks=['MOUNT_INITIAL: /mnt/app ro','MOUNT_RESTORED: /mnt/app ro',f'STAGE2_{action}_FILES_PASSED',f'{action}_exit=0']
        positions=[text.index(m) for m in marks];assert positions==sorted(positions)
    boot=logs['stage2-after-boot.txt']
    assert 'MU1320-STAGE2-JAVA-PASSIVE-V1 component init reached' in boot
    assert 'CarPlay activation observed; no module takeover' in boot
    assert '一切正常' in boot
    assert 'FILES: STAGE2_INSTALLED' in logs['stage2-collect.txt'] and 'collect_exit=0' in logs['stage2-collect.txt']
    root=DUMP/'stage2-backup/mu1320-rgi-stage2-v2'
    assert (root/'IDENTITY').read_text().strip()=='MU1320-STAGE2-PASSIVE-V2'
    assert (root/'phase.txt').read_text().strip()=='STAGE2_INSTALLED'
    original=BASE.parent/'resource/jars/NavActiveIgnore.jar'
    for name in ['backup/NavActiveIgnore.jar','quarantine/NavActiveIgnore.jar']:
        assert sha(root/name)==sha(original)
    report=dict(status='PASS_WITH_STATED_EVIDENCE_LIMITS',package_version=2,java_build_id='MU1320-STAGE2-JAVA-PASSIVE-V1',
        input_sha256={n:sha(DUMP/n) for n in names},backup_sha256={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()},
        java_initialization_observed=True,carplay_activation_observed=True,user_reports_basic_functions_normal=True,
        installation_exit=0,rollback_exit=0,mount_restored_ro=True,backup_matches_baseline=True,
        backup_snapshot_phase='pre-rollback STAGE2_INSTALLED',post_rollback_restart='User explicitly confirmed normal restart and original functions normal in chat',
        limits=['No post-rollback file download: restoration is supported by successful script checks and user confirmation.','Java log does not prove native hook or TCP transport; native and renderer remain untested.','Android Auto was not explicitly reported.'])
    (BASE/'reports/stage2-vehicle-v2.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print('PASS: Java init/activation observed, normal functions reported, backup matches, rollback exit 0 and restart confirmed.')
if __name__=='__main__':main()
