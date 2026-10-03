#!/usr/bin/env python3
import json,hashlib
from pathlib import Path
from audit_native import inspect
from audit_native_probe import check_binary
BASE=Path(__file__).resolve().parents[1];RESOURCE=BASE.parent/'resource'
def main():
    files=sorted(RESOURCE.glob('lib*.so*'))+sorted((RESOURCE/'native-libs').rglob('*.so*'))+sorted((RESOURCE/'cinemo').glob('*.so'))
    inventory={str(p.relative_to(RESOURCE)):inspect(p) for p in files if p.is_file()}
    result={n:check_binary(BASE/'stage3'/n,inventory) for n in ['mount_state','libcarplay_hook.so']}
    assert all(r['status']=='STATIC_PASS' for r in result.values())
    report=dict(status='STATIC_PASS',artifacts=result,mount_helper_build=dict(image_id='sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d',compiler='arm-unknown-nto-qnx6.5.0eabi-gcc',flags=['-O2','-std=gnu99','-Wall','-Wextra','-Werror'],source_sha256=hashlib.sha256((BASE/'stage3/mount_state.c').read_bytes()).hexdigest()),vehicle_runtime_tested=False)
    (BASE/'reports/stage3-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: Stage3 ELF architecture, dependency closure and symbol versions; actual interposition untested.')
if __name__=='__main__':main()
