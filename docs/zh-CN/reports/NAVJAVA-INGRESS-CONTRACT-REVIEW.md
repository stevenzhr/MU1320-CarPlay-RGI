# Native -> Java RGI ingress contract review

Date: 2026-09-24

Scope: the smallest controlled integration step after native RGI reception was
verified on vehicle. This review deliberately stops at Java receive, validate,
and privacy-safe logging. It does not authorize BAP publication, renderer
integration, navigation ownership changes, display changes, input changes, or
cover-art changes.

## Transport and frame contract

| Item | Contract used by the trial |
| --- | --- |
| Transport | TCP loopback, Java server on `127.0.0.1:19810`, native hook as client |
| Frame size | 16-byte header plus payload |
| Byte order | Big-endian |
| Magic | `CPHB` |
| Event | `EVT_RGD_UPDATE` (`0x20`) |
| Payload | UTF-8, NUL-free, maximum 64 KiB |
| Delivery | Latest RGI state is sticky and replayed after Java reconnect |

The Java trial listener uses the same Stage2-proven `CarplayBus` classes as the
existing disabled Stage2 artifact. Every reused class is byte-identical to that
artifact; only the application entry point and receive-only parser are new.

## Payload contract

The accepted payload starts with `@routeguidance` and contains only the native
hook's documented key families:

- top-level: `state`, `maneuver_count`, `source_flag`, `turn_icondisplay`
- maneuver slots 0..31: `symbol`, `distance`, `distance_unit`, `turn_angle`,
  `exit_number`, `junction_type`, `road_name`, `signpost_info`
- lane slots 0..7: `lane_direction`, `lane_direction_highlight`

Values must carry the expected native type code. Numeric fields are parsed as
bounded signed or unsigned decimal values; lane vectors must contain exactly
eight entries; the navigation state is limited to the documented 0..6 range;
unknown or duplicate fields are rejected. Road names and signpost strings are
never emitted in the Java log.

The native lifecycle contract remains authoritative: session loss emits a
clear/off-route update, and a reconnect can replay the latest sticky state.
The Java layer does not synthesize navigation state.

## Compatibility and isolation decisions

- `NavActiveIgnore.jar` stays installed at its original path and is neither
  replaced nor shadowed by the new JAR.
- The trial JAR has no class-name overlap with `NavActiveIgnore.jar`.
- Its original hash is pinned, backed up before installation, checked during
  the trial, and byte-compared during rollback.
- The trial entry point reports `isActive() == false`; it does not claim the
  navigation application role.
- The listener-ready marker must be observed before the native one-shot gate
  can be armed.
- Rollback restores SI first, removes the trial JAR from the recursive scan
  tree, and leaves `NavActiveIgnore.jar` intact.

## Verification completed off vehicle

- exact parser harness: pass
- missing-reference/class-version/forbidden-reference audit: pass
- reused Stage2 class byte comparison: pass
- six transaction simulations, including partial-install rollback: pass
- package hash and manifest audit: pass
- bundled native hook is byte-identical to the vehicle-verified v1.2 hook

Evidence is in `navjava-ingress-*.json`, `navjava-ingress-*.txt`, and
`navjava-ingress-*.diff` in this directory.

## Remaining proof

No Java ingress code from this package has run on the vehicle. The next proof is
one controlled run that captures, for the same route-guidance update:

1. the native one-shot gate receipt and hook `EMIT` line;
2. the Java `PARSE_OK` line;
3. rollback success with the original `NavActiveIgnore.jar` hash restored;
4. the SD-wrapper terminal footer containing `SD_MOUNT_RESTORED`,
   `CONTROL_EXIT`, and `OUTER_EXIT`.

Only after that evidence passes should the project consider a separately scoped
NavActiveIgnore isolation or BAP/renderer trial.
