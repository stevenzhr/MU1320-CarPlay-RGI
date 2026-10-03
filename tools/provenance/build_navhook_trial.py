#!/usr/bin/env python3
"""Create and build an isolated navigation hook with a process one-shot gate."""
import difflib
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PRIVATE = BASE.parent / "private-data" / "mu1320-rgi"
SOURCE = PRIVATE / 'stage1-build/src'
BUILD = PRIVATE / 'navhook-v1-build'
REPORT = BASE / 'reports/navhook-trial-build.json'
IMAGE = 'sha256:e52565b1f62dab0f93f12532d52611b94e90b89e4da04f972b11f54eaeb6a05d'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)

def main():
    assert not BUILD.exists(), 'Preserve an existing private build; use a new version.'
    stage1 = json.loads((BASE / 'reports/stage1-build.json').read_text())
    assert stage1['image_id'] == IMAGE
    assert sha(SOURCE / 'build/libcarplay_hook.so') == stage1['artifacts']['libcarplay_hook.so']['sha256']
    shutil.copytree(SOURCE, BUILD / 'src')
    framework = BUILD / 'src/hook/framework/hook_framework.c'
    original = framework.read_text()
    text = once(original, '#include "hook_framework.h"\n', '#include "hook_framework.h"\n#include "trial_gate.h"\n')
    text = once(text, 'int CinemoCreateIAP(void* args) {\n    void* new_iap',
                'int CinemoCreateIAP(void* args) {\n    int trial_active = trial_gate_active();\n    void* new_iap')
    text = once(text, '    ret = g_fw.real_cinemo_create_iap(args);\n    if (ret != 0',
                '    ret = g_fw.real_cinemo_create_iap(args);\n    if (!trial_active) return ret;\n    if (ret != 0')
    text = once(text, 'int _ZN14NmeIAP2Message6DecodeEPKhi(void* self, const uint8_t* buf, int len) {\n    if (!g_fw.initialized',
                'int _ZN14NmeIAP2Message6DecodeEPKhi(void* self, const uint8_t* buf, int len) {\n    int trial_active = trial_gate_active();\n    if (trial_active && (!g_fw.initialized')
    text = once(text, '(!g_fw.bus_started && !g_fw.bus_disabled))\n        hook_framework_init();\n    resolve_functions();\n\n    int ret = 0;',
                '(!g_fw.bus_started && !g_fw.bus_disabled)))\n        hook_framework_init();\n    resolve_functions();\n\n    int ret = 0;')
    text = once(text, '    if (g_fw.real_decode) ret = g_fw.real_decode(self, buf, len);\n\n    if (ret != 0',
                '    if (g_fw.real_decode) ret = g_fw.real_decode(self, buf, len);\n    if (!trial_active) return ret;\n\n    if (ret != 0')
    text = once(text, 'int _ZNK14NmeIAP2Message6EncodeER8NmeArrayIhE(const void* self, void* out_array) {\n    if (!g_fw.initialized',
                'int _ZNK14NmeIAP2Message6EncodeER8NmeArrayIhE(const void* self, void* out_array) {\n    int trial_active = trial_gate_active();\n    if (trial_active && (!g_fw.initialized')
    # The same textual init condition occurs in Send/Recv; replace only the
    # first remaining occurrence here and each explicit function below.
    text = once(text, 'int _ZN12NmeTransport4SendEPKhjPj(void* self, const uint8_t* buf, unsigned int len, unsigned int* sent) {\n    iap2_frame_t frame;\n    bool have_frame = false;\n    int ret;\n\n    if (!g_fw.initialized',
                'int _ZN12NmeTransport4SendEPKhjPj(void* self, const uint8_t* buf, unsigned int len, unsigned int* sent) {\n    iap2_frame_t frame;\n    bool have_frame = false;\n    int ret;\n    int trial_active = trial_gate_active();\n\n    if (trial_active && (!g_fw.initialized')
    text = once(text, 'int _ZN12NmeTransport4RecvER8NmeArrayIhE(void* self, void* out_array) {\n    if (!g_fw.initialized',
                'int _ZN12NmeTransport4RecvER8NmeArrayIhE(void* self, void* out_array) {\n    int trial_active = trial_gate_active();\n    if (trial_active && (!g_fw.initialized')
    # Close the three newly parenthesized active conditions plus Encode.
    text = text.replace('if (trial_active && (!g_fw.initialized || (!g_fw.bus_started && !g_fw.bus_disabled))\n        hook_framework_init();',
                        'if (trial_active && (!g_fw.initialized || (!g_fw.bus_started && !g_fw.bus_disabled)))\n        hook_framework_init();')
    assert text.count('if (trial_active && (!g_fw.initialized') == 4
    text = once(text, '    if (g_fw.real_encode) ret = g_fw.real_encode(self, out_array);\n    if (ret != 0)',
                '    if (g_fw.real_encode) ret = g_fw.real_encode(self, out_array);\n    if (!trial_active) return ret;\n    if (ret != 0)')
    text = once(text, '    ret = g_fw.real_transport_send(self, buf, len, sent);\n    if (ret != 0',
                '    ret = g_fw.real_transport_send(self, buf, len, sent);\n    if (!trial_active) return ret;\n    if (ret != 0')
    text = once(text, '    int ret = g_fw.real_transport_recv(self, out_array);\n\n    uint8_t* data',
                '    int ret = g_fw.real_transport_recv(self, out_array);\n    if (!trial_active) return ret;\n\n    uint8_t* data')
    text = once(text, 'static void hook_lib_fini(void) {\n    hook_framework_shutdown();\n}',
                'static void hook_lib_fini(void) {\n    if (trial_gate_was_active()) hook_framework_shutdown();\n}')
    framework.write_text(text)
    shutil.copyfile(BASE / 'navhook-src/trial_gate.c', BUILD / 'src/hook/framework/trial_gate.c')
    shutil.copyfile(BASE / 'navhook-src/trial_gate.h', BUILD / 'src/hook/framework/trial_gate.h')
    build_script = BUILD / 'src/scripts/build_hook.sh'
    script = build_script.read_text()
    script = once(script, 'framework/iap2_protocol.c framework/hook_framework.c',
                  'framework/iap2_protocol.c framework/trial_gate.c framework/hook_framework.c')
    build_script.write_text(script)
    result = subprocess.run(['/bin/bash', str(build_script)], capture_output=True, text=True)
    (BUILD / 'build.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    artifact = BUILD / 'src/build/libcarplay_hook.so'
    diff = ''.join(difflib.unified_diff(original.splitlines(True), text.splitlines(True),
                                        fromfile='stage1/hook_framework.c', tofile='navhook/hook_framework.c'))
    (BASE / 'reports/navhook-trial-gate.diff').write_text(diff)
    report = {'image_id': IMAGE, 'compiler_version': '4.9.4',
              'base_stage1_hook_sha256': stage1['artifacts']['libcarplay_hook.so']['sha256'],
              'scope': 'navigation-only hook with process-local one-shot activation; replacement DIO is passive',
              'constructor_added': False, 'coverart_compiled': False,
              'sources': {'trial_gate.c': sha(BASE / 'navhook-src/trial_gate.c'),
                          'trial_gate.h': sha(BASE / 'navhook-src/trial_gate.h'),
                          'hook_framework.c': sha(framework), 'build_hook.sh': sha(build_script)},
              'artifact': {'sha256': sha(artifact), 'size': artifact.stat().st_size},
              'vehicle_tested': False}
    REPORT.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['artifact'], indent=2))
if __name__ == '__main__': main()
